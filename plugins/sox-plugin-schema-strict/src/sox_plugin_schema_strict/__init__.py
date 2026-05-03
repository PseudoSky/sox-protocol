# SPDX-License-Identifier: Apache-2.0
"""sox-plugin-schema-strict — reference SOX Protocol transformer plugin.

Exports the factory function registered as the entry-point::

    [project.entry-points."sox_protocol.plugins"]
    "io.sox.schema-strict" = "sox_plugin_schema_strict:factory"

The factory is called by the host's ``MiddlewareRegistry.load_plugins()``
to obtain a fresh ``SchemaStrictMiddleware`` instance.
"""

from __future__ import annotations

from sox_plugin_schema_strict.middleware import SchemaStrictMiddleware


def factory() -> SchemaStrictMiddleware:
    """Entry-point factory for the schema-strict plugin.

    Called once at host startup by the plugin loader.

    Returns:
        A fresh :class:`SchemaStrictMiddleware` instance with schemas_dir
        resolved from the environment or CWD search.
    """
    return SchemaStrictMiddleware()


__all__ = ["SchemaStrictMiddleware", "factory"]
