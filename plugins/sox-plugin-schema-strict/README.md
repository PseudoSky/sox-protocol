# sox-plugin-schema-strict

Reference plugin for the [SOX Protocol](https://pypi.org/project/sox-protocol/) — strict JSON-Schema validation of message bodies on the wire.

The plugin registers a `transformer`-kind middleware (id `io.sox.schema-strict`) that validates every operation's `input` body against the canonical schema in `spec/operations/<op>.input.schema.json`. Requests that fail validation are short-circuited with a structured `error_code` envelope before they reach the backing store.

It is the canonical proof-of-concept that the SOX plugin contract works end-to-end. Most SOX deployments will install this plugin alongside the core; the recommended install line is:

```bash
pip install sox-protocol sox-plugin-schema-strict
```

> **Install non-editable.** The plugin's `sox-plugin.yaml` manifest is registered as setuptools `package-data`; editable installs (`pip install -e`) do not expose that data file via `importlib.resources` and the SOX MCP server will fail plugin discovery at boot. Use plain `pip install`.

## What it validates

- `channels__send` body shape (must be a JSON object, not a string).
- `channels__recv` channel filter list shape and `max_messages` range.
- `channels__subscribe` / `channels__unsubscribe` channel patterns.
- `channels__replay` `since` / `until` cursors and `limit` bounds.
- `channels__heartbeat` status enum.
- `group__create` / `group__invite` / `group__join` / `group__leave` / `group__list_members` argument shapes.

If you skip the plugin, SOX core accepts any well-typed body — useful for prototyping but unsafe for shared deployments.

## Pipeline placement

Schema-strict registers as the first middleware in the pipeline (before auth, before store dispatch). Validation failures emit:

```json
{ "error_code": "schema_invalid", "details": { ... } }
```

with HTTP status `400` (HTTP transport) or as a structured tool error envelope (stdio transport).

## License

Apache 2.0 — see the [SOX Protocol repository](https://github.com/your-org/sox-protocol) for the full license and patent grant.
