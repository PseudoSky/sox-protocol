---
phase_id: 03-polish
title: Visual polish + a11y review
agent: ui-designer
profile: review
estimated_effort: 2-3 days
prereqs: [02-build]
unblocks: []
parallelizable_with: []
writes: ["packages/ui/**", "docs/media/**", "README.md"]
reads:  ["packages/ui/**", "docs/media/**"]
context_size: medium
---

# 03 — Polish

## Objective

Visual + interaction + a11y review. Capture the demo recording for the project landing page.

## Inputs

- `packages/ui/` (the built app)
- `.workflow/plans/chat-webapp/implementation-plan.json`
- `docs/media/demo.gif` (TUI demo, for visual continuity reference)

## Prompt (verbatim)

```text
Polish the SOX Protocol web app for public showcase.

READ:
- packages/ui/ (the app)
- .workflow/plans/chat-webapp/implementation-plan.json
- docs/media/demo.gif (TUI demo for visual style reference)

REVIEW + REMEDIATE:

1. Visual hierarchy. Channel sidebar should not dominate; message thread is the focus. Typography scale consistent. Spacing rhythm.
2. Interaction polish. Hover states, focus rings, loading states (live recv shouldn't flash; use animation easing), empty states.
3. Accessibility. Run axe-core via Playwright. Every interactive element keyboard-navigable. ARIA labels on icon-only buttons. Color contrast WCAG AA.
4. Visual continuity with the TUI. Same vocabulary (channels/groups/threads/presence), same demo choreography if reasonable.
5. Capture demo recording. Use Playwright + ffmpeg to script a 60-90s recording showing: open app, see channels, click thread, see message reply, see ACK indicator, see presence dot. Output to docs/media/webapp-demo.mp4 + .gif.

DELIVER:
- Visual + interaction fixes (commit any changes to packages/ui/src)
- a11y review report at .workflow/plans/chat-webapp/reviews/02-build.md
- docs/media/webapp-demo.mp4 and .gif
- Update README.md to embed the new asset (if it's stronger than TUI demo for landing page)

ACCEPTANCE:
- npx playwright test (a11y suite passes)
- All Lighthouse scores from 02-build maintained or improved
- docs/media/webapp-demo.{mp4,gif} exist
- Review report has Verdict + Findings + Sign-off

REPORT: ≤ 200 words. Top 3 changes made, recording duration, a11y violations fixed.
```

## Exit criteria

Universal (`review`):
- [ ] `test -f .workflow/plans/chat-webapp/reviews/02-build.md`
- [ ] `grep -E '^## Verdict' .workflow/plans/chat-webapp/reviews/02-build.md`

Engagement-specific:
- [ ] `test -f docs/media/webapp-demo.mp4 || test -f docs/media/webapp-demo.gif`
- [ ] `cd packages/ui && npx playwright test --reporter=line` (a11y suite green)
- [ ] `cd packages/ui && pnpm vitest run` (regression — 02 tests still pass)
- [ ] `cd packages/ui && pnpm tsc --noEmit --strict` (regression)

## Outputs

- Polished `packages/ui/`
- `docs/media/webapp-demo.{mp4,gif}`
- `.workflow/plans/chat-webapp/reviews/02-build.md`
- Optional README update

## Next state

Leaf. Engagement complete on DONE.
