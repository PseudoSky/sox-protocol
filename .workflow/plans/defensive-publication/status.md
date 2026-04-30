---
slug: defensive-publication
state: initialized
bucket: pitch
stream: D
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
priority: high
unblocks: []
depends_on: []
soft_depends_on: [spec-extraction]
---

# Engagement: defensive-publication

## Objective
Wrap the project in defensive IP posture: switch to Apache 2.0, deposit prior art on Software Heritage and IP.com, draft an arXiv preprint, and join OIN.

## Acceptance criteria
- [ ] LICENSE updated to Apache 2.0 (verify all files have correct headers)
- [ ] README mentions license choice rationale (Apache 2.0 explicit patent grant)
- [ ] Repository submitted to Software Heritage (`save code now` form); SWHID committed to `docs/ip/swhid.txt`
- [ ] arXiv preprint draft (cs.MA category): 6-10 pages describing protocol, primitives, semantics, worked example, related work (KQML/FIPA/JADE/CAMEL/ChatDev/MCP/A2A). Saved to `docs/ip/preprint/` in LaTeX or markdown
- [ ] IP.com Prior Art Database submission planned (or filed if budget allows; ~$200)
- [ ] OIN membership application filed (free under $10M revenue) — task for human action, status tracked in `docs/ip/oin-application.md`
- [ ] Signed commits configured; CONTRIBUTING.md documents the requirement
- [ ] CONTRIBUTING.md includes Developer Certificate of Origin (DCO) sign-off requirement

## Inputs
- Patent-landscape finding (`~/.claude/plugins/workflow/memory/research/patent-landscape/agent-communication-protocols.md`)
- Spec extraction output (preprint cites the spec)

## Outputs
- LICENSE update
- `docs/ip/` directory with SWHID, preprint, OIN tracker
- README and CONTRIBUTING updates

## Suggested executor
`content-marketer` for preprint draft; `general-purpose` for license/repo housekeeping. Some steps require human action (OIN application, IP.com submission).

## State transitions
- 2026-04-29 initialized — workflow-architect
