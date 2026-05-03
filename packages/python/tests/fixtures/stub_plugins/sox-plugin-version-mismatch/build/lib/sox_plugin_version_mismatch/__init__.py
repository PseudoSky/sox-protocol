# SPDX-License-Identifier: Apache-2.0
"""Version-mismatch stub: declares protocol_version >=2.0,<3.0 (incompatible with host 1.0.0)."""

from __future__ import annotations

from .middleware import VersionMismatchMiddleware


def make_middleware() -> "VersionMismatchMiddleware":
    return VersionMismatchMiddleware()


__all__ = ["VersionMismatchMiddleware", "make_middleware"]
