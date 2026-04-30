# Decision: webapp-deployment-model

**Status:** Resolved — 2026-04-30
**Source question:** bucket-classification result.md Q2 (webapp-deployment-model)

## Context
The `sox-ui` web app is the post-v1 showpiece demo for visitors who won't run a terminal. It needs a deployment model: a static build calling the SOX HTTP endpoint directly (Option A), a thin Node proxy that serves assets and forwards API calls (Option B), or assets bundled with and served by the SOX Python server itself (Option C). The primary deployment scenario is local — a developer running `sox` on localhost — but the public docs site also needs a hostable build.

## Decision
**Option A — Static build (Vite + React), with a hybrid distribution strategy.** The web app is built as a static SPA that talks directly to the SOX HTTP endpoint. The build is published two ways: (1) standalone npm package + hosted on the docs site/CDN for the public demo, configured against a public read-only SOX endpoint or local-first instructions; (2) a built copy is bundled into the Python wheel under `sox_protocol/ui/static/`, and `sox ui` boots the HTTP transport and serves those assets from the SOX server itself at `/ui/` (a thin static file route, not a framework). The SOX HTTP transport advertises permissive CORS for `localhost` and explicitly-configured origins. No separate Node process is introduced.

## Rationale
This combines Option A's portability with Option C's "Just Works" local UX without taking on Option B's operational cost. A pure static build is the most portable artifact (CDN, GitHub Pages, Vercel, self-host all trivial); bundling it into the Python wheel for `sox ui` is just a static-file route on the existing HTTP transport — not a coupling, just packaging. Option B (Node proxy) adds a second runtime, a second deploy target, and a second auth boundary for negligible benefit when CORS for `localhost` is already a non-issue. Option C alone would force every user to run the Python server to see the demo, killing the docs-site landing page experience. Trade-off accepted: CORS configuration is now a real spec concern for the HTTP transport (must be documented and defaulted sanely), and auth tokens travel in browser-visible headers — acceptable because the primary deployment is local-first and the HTTP transport's auth model is already a deployment concern, not a protocol guarantee.

## Consequences
- Positive: One build artifact serves both the public demo (CDN) and local use (`sox ui`).
- Positive: No second process, no proxy auth layer, no Node runtime in the Python distribution.
- Positive: Standalone npm publish allows self-hosters and SOX-on-prem operators to pin their own version.
- Negative: HTTP transport must implement CORS handling (preflight, allow-list config). Becomes a hard requirement of the `http-transport` engagement.
- Negative: Auth tokens in browser localStorage / headers — fine for local dev, requires a documented "don't expose this to the public internet without a reverse proxy" warning.
- Negative: Bundling built assets into the Python wheel adds a build-time step (npm build → copy into Python package); CI must orchestrate it. Modest complexity.
- Spec impact: `ports/transport.md` HTTP binding gains a CORS section — required headers, preflight behavior, configurable origin allow-list, sane localhost default. No envelope or core-protocol changes.

## Open questions for follow-up
- Exact CORS default — `http://localhost:*` and `http://127.0.0.1:*` only, with explicit config for anything else? Decide during `http-transport` planning.
- Where does the public-demo landing page point its API calls — a hosted demo SOX instance, or a WASM-embedded one, or a "download and run locally" CTA? Decide during `chat-webapp` execution; not blocking.
- Auth posture for the public demo: read-only viewer token with rate limits, or full credentials with a warning? Decide alongside identity-primitive resolution.
- If a user wants the webapp without the Python package (e.g. running a Rust SOX server), the standalone npm build covers it; document this path in the webapp README.
