# SPDX-License-Identifier: Apache-2.0
"""Sequence-number state persistence for the SOX reference agent.

Spec reference: spec/primitives/sequence-numbers.md

The recovery pattern requires that an agent remember the last seq it
successfully processed on each channel, so it can call replay(since=N)
after a restart and receive only messages it has not yet handled.

This module provides atomic JSON file I/O so that a crash between
processing a message and persisting its seq cannot cause double-delivery
after replay: we only update the file AFTER the message is fully handled.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class SeqState:
    """Persist and load {channel: last_seq} mapping to/from a JSON file.

    The file is written atomically via a temp-file + rename so a crash
    mid-write never leaves a partial or empty file on disk.

    Usage::

        state = SeqState(Path("/var/lib/my-agent/seq.json"))
        mapping = state.load()          # read current state (or {} if absent)
        state.update("ticket:ENGI-1", 42)  # update one channel in-place
        state.save({"ticket:ENGI-1": 42})  # or overwrite the whole mapping
    """

    # Path to the JSON file where {channel: last_seq} is stored.
    def __init__(self, path: Path) -> None:
        # Store the resolved path so callers need not worry about cwd.
        self._path = path.resolve()

    def load(self) -> dict[str, int]:
        """Load the persisted state from disk.

        Returns an empty dict if the file does not exist or is corrupt.
        Corrupt-file recovery is intentional: a partially-written file
        is equivalent to no state, and the agent will replay from seq=0.
        """
        # If the file does not exist, start fresh — no crash.
        if not self._path.exists():
            return {}
        try:
            # Parse the JSON; any decode error returns empty (corrupt = reset).
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
            # Validate that every value is an integer (defensive against drift).
            return {str(k): int(v) for k, v in data.items()}
        except (json.JSONDecodeError, ValueError, TypeError):
            # Corrupt file: treat as empty so replay starts from the beginning.
            return {}

    def save(self, state: dict[str, int]) -> None:
        """Atomically overwrite the state file with *state*.

        Uses a sibling temp file + os.replace() so the directory entry
        switches atomically on POSIX; no partial read is ever possible.
        """
        # Ensure the parent directory exists before writing.
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file in the same directory so os.replace is atomic.
        fd, tmp_path = tempfile.mkstemp(
            dir=self._path.parent,
            prefix=".seq-",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                # Pretty-print for human inspectability during debugging.
                json.dump(state, fh, indent=2, sort_keys=True)
                fh.write("\n")
            # Atomic replace: if the process dies before this line the old
            # file is untouched; if it dies after, the new file is complete.
            os.replace(tmp_path, self._path)
        except Exception:
            # Clean up the temp file on any error to avoid stale files.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def update(self, channel: str, seq: int) -> None:
        """Update the last-seen seq for *channel* and persist.

        Reads the current state, sets state[channel] = seq, then writes
        atomically.  This is the hot path called after each message is
        processed; keeping it in one method ensures load-modify-save is
        always done together.
        """
        # Load, modify in memory, then write back atomically.
        current = self.load()
        current[channel] = seq
        self.save(current)
