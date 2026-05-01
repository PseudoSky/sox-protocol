---
slug: chat-webapp
target: React+TS web app showcasing SOX. Static-deployable; also `sox ui` CLI subcommand. Public-facing demo at the docs site.
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
orchestrator_protocol: v1
---

# chat-webapp — engagement state (post-v1)

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-plan | Component tree + state plan | `DONE` | sox-cto-system:planner | 1 | 2026-04-30T00:00:00Z |
| 02-build | Build app + integrate SDK | `READY` | react-specialist | 0 | 2026-04-30T00:00:00Z |
| 03-polish | Visual polish + a11y review | `BLOCKED` | ui-designer | 0 | 2026-04-29T00:00:00Z |

## Currently next action

`02-build` is `READY`. Spawn `react-specialist`.

## Termination targets

- [ ] All phases DONE
- [ ] `packages/ui/` workspace shipping
- [ ] `sox ui` CLI subcommand starts the HTTP transport and opens the browser
- [ ] Static deployable (Vercel/Cloudflare/GitHub Pages compatible)
- [ ] Demo recording for the project landing page
- [ ] Lighthouse score acceptable; basic a11y (keyboard nav, ARIA)
