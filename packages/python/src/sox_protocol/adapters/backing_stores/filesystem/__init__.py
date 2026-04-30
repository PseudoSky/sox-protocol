# SPDX-License-Identifier: Apache-2.0
"""Directory-per-channel, file-per-message backing-store adapter."""

from sox_protocol.adapters.backing_stores.filesystem.store import FilesystemStore

__all__ = ["FilesystemStore"]
