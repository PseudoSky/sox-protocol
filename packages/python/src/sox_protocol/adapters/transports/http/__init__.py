# SPDX-License-Identifier: Apache-2.0
"""SOX Protocol HTTP transport adapter.

Public entrypoint; re-exports :class:`HttpTransport` and :func:`create_app`.

Spec reference: ``spec/ports/transport.md §2.1``
"""

from sox_protocol.adapters.transports.http.server import HttpTransport, create_app

__all__ = ["HttpTransport", "create_app"]
