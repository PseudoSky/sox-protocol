# SPDX-License-Identifier: Apache-2.0
"""HTTP transport configuration.

Loaded from environment variables:
- SOX_HTTP_HOST: bind host (default: 127.0.0.1)
- SOX_HTTP_PORT: bind port (default: 8765)
- SOX_HTTP_CORS_ORIGINS: comma-separated allowed origins
- SOX_HTTP_BUFFER_LIMIT: outbound buffer limit (default: 1000)
- SOX_HTTP_RECONNECT_MAX_S: max reconnect backoff seconds (default: 30)

Spec reference: ``spec/ports/transport.md §2``
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _parse_origins(raw: str) -> list[str]:
    """Parse a comma-separated origins string into a list."""
    return [o.strip() for o in raw.split(",") if o.strip()]


@dataclass
class HttpConfig:
    """Pydantic-free config model for the HTTP transport.

    All values are loaded from environment variables with sensible defaults.

    Attributes:
        host: Bind host for the uvicorn server.
        port: Bind port for the uvicorn server.
        cors_origins: Allowed CORS origins list.
        buffer_limit: Max outbound message buffer size before overflow error.
        reconnect_max_s: Maximum reconnect back-off seconds.
    """

    host: str = field(default_factory=lambda: os.environ.get("SOX_HTTP_HOST", "127.0.0.1"))
    port: int = field(
        default_factory=lambda: int(os.environ.get("SOX_HTTP_PORT", "8765"))
    )
    cors_origins: list[str] = field(
        default_factory=lambda: _parse_origins(
            os.environ.get(
                "SOX_HTTP_CORS_ORIGINS",
                "http://localhost,http://127.0.0.1",
            )
        )
    )
    buffer_limit: int = field(
        default_factory=lambda: int(os.environ.get("SOX_HTTP_BUFFER_LIMIT", "1000"))
    )
    reconnect_max_s: int = field(
        default_factory=lambda: int(os.environ.get("SOX_HTTP_RECONNECT_MAX_S", "30"))
    )

    @classmethod
    def from_env(cls) -> HttpConfig:
        """Construct config from current environment variables.

        Returns:
            A fully populated :class:`HttpConfig` instance.
        """
        return cls()
