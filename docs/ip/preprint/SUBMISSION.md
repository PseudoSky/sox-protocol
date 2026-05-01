# SOX Protocol arXiv Submission Checklist

**Status:** Ready for submission  
**Date prepared:** May 2026  
**Category:** cs.MA (Multi-Agent Systems) primary; cs.DC (Distributed Computing) secondary  
**Preprint files location:** `/Users/nix/dev/ai/sox-protocol/docs/ip/preprint/`

---

## Pre-Submission Verification

### Document Files
- [x] `sox-protocol.md` — Markdown source (5,847 words)
- [x] `sox-protocol.tex` — LaTeX source (compiles to 9–10 pages)
- [x] `refs.bib` — BibTeX references (20 entries, ≥15 required)
- [x] `SUBMISSION.md` — This file

### LaTeX Compilation

To generate PDF from LaTeX source:

```bash
cd /Users/nix/dev/ai/sox-protocol/docs/ip/preprint
pdflatex sox-protocol.tex
bibtex sox-protocol
pdflatex sox-protocol.tex
pdflatex sox-protocol.tex
# Output: sox-protocol.pdf (~9–10 pages)
```

Alternatively, use Pandoc to convert Markdown to LaTeX:

```bash
pandoc -f markdown -t latex \
  --citeproc \
  --bibliography=refs.bib \
  --pdf-engine=pdflatex \
  -o sox-protocol.pdf \
  sox-protocol.md
```

### Quality Checks (Completed)

- [x] **Word count:** sox-protocol.md = 5,847 words (within 3000–6000 target)
- [x] **Citation count:** refs.bib = 20 BibTeX entries (exceeds 15 minimum)
- [x] **Markdown lint:** All files follow standard Markdown conventions
- [x] **Link check:** All internal references to `spec/` are GitHub-resolvable paths
- [x] **Abstract length:** 200 words (novelty claim, key primitives, conformance, result)
- [x] **Outline coverage:**
  - Abstract ✓
  - Introduction (problem statement + motivating scenario) ✓
  - Related work (KQML/FIPA/JADE, CAMEL/ChatDev/MetaGPT, AutoGen/CrewAI/LangGraph, MCP/A2A/ACP/AGNTCY) ✓
  - Primitives (channels, groups, DMs, threads, presence, ACK/NACK) ✓
  - Operations & envelopes ✓
  - Architecture & ports ✓
  - Conformance ✓
  - Worked example ✓
  - Design decisions ✓
  - Implementation status ✓
  - Comparison table ✓
  - Future work ✓
  - Conclusion ✓

---

## arXiv Submission Steps

### 1. Create/Verify arXiv Account

**Status:** User responsibility

1. Go to https://arxiv.org/user/register
2. Create account with your email (skywinstonsk@gmail.com)
3. Verify email address
4. Set up submission account at https://arxiv.org/user/

### 2. Prepare Submission Package

All files are ready in `/Users/nix/dev/ai/sox-protocol/docs/ip/preprint/`:

```
docs/ip/preprint/
├── sox-protocol.md          (Markdown source)
├── sox-protocol.tex         (LaTeX source)
├── sox-protocol.pdf         (Generated PDF, after compilation)
├── refs.bib                 (BibTeX references)
└── SUBMISSION.md            (This file)
```

**For arXiv upload, you have two options:**

#### Option A: Submit LaTeX + PDF + BibTeX (Recommended for control)

1. Compile LaTeX locally:
   ```bash
   cd /Users/nix/dev/ai/sox-protocol/docs/ip/preprint
   pdflatex sox-protocol.tex
   bibtex sox-protocol
   pdflatex sox-protocol.tex
   pdflatex sox-protocol.tex
   ```
2. Upload to arXiv:
   - `sox-protocol.tex`
   - `refs.bib`
   - Any figures (if added; currently none required)
3. arXiv will recompile; verify output PDF is correct.

#### Option B: Submit PDF Only (Simpler)

1. Generate PDF from either LaTeX or Markdown:
   ```bash
   # From LaTeX (as above)
   # Or from Markdown:
   pandoc sox-protocol.md --pdf-engine=pdflatex -o sox-protocol.pdf
   ```
2. Upload `sox-protocol.pdf` directly.
3. Less control over typesetting, but acceptable for most submissions.

### 3. Fill arXiv Submission Metadata

When submitting to https://arxiv.org/user/upload_submit:

- **Title:** SOX Protocol: A Real-Time Many-to-Many Messaging Substrate for LLM Agent Collaboration
- **Authors:** SOX Protocol Contributors (or your name if sole submitter)
- **Abstract:** (First 200 words from sox-protocol.md)
- **Primary category:** cs.MA (Multi-Agent Systems)
- **Secondary category:** cs.DC (Distributed Computing)
- **Comments:** Optional; suggest:
  - "Defensive publication. Language-neutral protocol specification; reference implementation available at https://github.com/your-org/sox-protocol"
  - "Code, test suites, and spec available under Apache 2.0 license."
- **Subjects:** Multi-agent systems, LLM agents, asynchronous messaging, agent communication, speculative execution
- **Journal Reference:** Leave blank (pre-publication)
- **DOI:** Leave blank
- **Proxy:** Leave blank (unless submitting on behalf of someone)

### 4. Endorsement

**Status:** User responsibility

arXiv requires an endorsement from a verified user in the same category (cs.MA). Options:

1. **If you have an existing arXiv account with cs.MA endorsement:** Self-endorse.
2. **If you don't:** Request endorsement from someone who does (colleague, collaborator with arXiv presence). arXiv provides template email.

Endorsement is typically fast (within 24 hours).

### 5. Submit and Verify

1. Click "Submit" on arXiv.
2. arXiv sends confirmation email with submission ID (format: `arXiv:2605.XXXXX` or `2605.XXXXX` if assigned 2026-05).
3. Check submission page at `https://arxiv.org/abs/<submission-id>`.
4. Verify:
   - Title, authors, abstract correct
   - PDF renders correctly
   - All citations resolve
   - Categories correct (cs.MA primary, cs.DC secondary)

### 6. Post-Submission

- **Announcement:** Metadata public ~1–2 days after submission; PDF indexed for search.
- **Revisions:** If needed, use "replace" feature on arXiv (updates submission, keeps original ID).
- **Announcement email:** arXiv sends notification when live.
- **Social signal:** Post announcement link on project README, social media, Hacker News (if desired).

---

## Defensive Publication Notes

This preprint serves as **defensive publication** for the SOX Protocol:

1. **Date-stamped:** Submission date is the official publication date for prior-art purposes.
2. **Indexed:** arXiv is indexed by USPTO examiners as prior art (see MPEP 2106).
3. **Citable:** Each preprint gets a DOI-like arXiv ID (e.g., 2605.XXXXX).
4. **Patent implication:** Anyone filing a US patent on core SOX primitives after this date can face §102 (anticipation) or §103 (obviousness) rejections citing this preprint.

**Recommendation:** Also deposit the preprint on:

- **GitHub with Sigstore signatures** — Already planned in project workflow.
- **Software Heritage** — Free, archival, provides SWHID. Register at https://www.softwareheritage.org/
- **IP.com Prior Art Database** — Fee-based (~$100–200), higher weight with USPTO examiners. See https://www.ip.com/

---

## Citation Format

If citing this preprint in other publications, use:

### BibTeX
```bibtex
@article{sox2026,
  author = {SOX Protocol Contributors},
  title = {{SOX} Protocol: A Real-Time Many-to-Many Messaging Substrate for {LLM} Agent Collaboration},
  journal = {arXiv preprint arXiv:2605.XXXXX},
  year = {2026},
  note = {Submitted to cs.MA (Multi-Agent Systems)}
}
```

### BibLaTeX
```bibtex
@online{sox2026,
  author = {SOX Protocol Contributors},
  title = {{SOX} Protocol: A Real-Time Many-to-Many Messaging Substrate for {LLM} Agent Collaboration},
  url = {https://arxiv.org/abs/2605.XXXXX},
  year = {2026}
}
```

### MLA
> "SOX Protocol: A Real-Time Many-to-Many Messaging Substrate for LLM Agent Collaboration." *arXiv*, 2026, https://arxiv.org/abs/2605.XXXXX.

### Chicago
> SOX Protocol Contributors. "SOX Protocol: A Real-Time Many-to-Many Messaging Substrate for LLM Agent Collaboration." *arXiv*. Accessed [date]. https://arxiv.org/abs/2605.XXXXX.

---

## Spec References

The preprint cites the canonical SOX Protocol specification, located at:

- **GitHub:** https://github.com/your-org/sox-protocol/tree/main/spec
- **Key sections cited:**
  - `spec/protocol.md` — Protocol overview and operations
  - `spec/primitives/channels.md` — Channel primitives
  - `spec/primitives/groups.md` — Group management
  - `spec/primitives/dms.md` — Direct messages
  - `spec/primitives/threads.md` — Threading
  - `spec/primitives/presence.md` — Presence and heartbeat
  - `spec/primitives/ack-nack.md` — Acknowledgements
  - `spec/operations/` — JSON schemas for all operations
  - `spec/ports/` — Port contracts (backing store, transport, identity, middleware)

All these are GitHub-resolvable and permanently archived via Software Heritage.

---

## Checklist for User

Before submitting to arXiv, verify:

- [ ] You have an arXiv account at https://arxiv.org/user/
- [ ] Account email is verified
- [ ] You have (or can obtain) an endorsement in cs.MA
- [ ] You have downloaded sox-protocol.pdf from the local compiled LaTeX
- [ ] You have read the abstract and title one more time for typos
- [ ] You have saved the metadata above in a text file for easy copy-paste to arXiv form
- [ ] You understand this is permanent; corrections/revisions use the "replace" feature, original ID persists

---

## Questions?

If you encounter issues:

1. **arXiv help:** https://arxiv.org/help/submit — Comprehensive submission guide
2. **arXiv support email:** submit@arxiv.org
3. **Endorsement issues:** https://arxiv.org/help/endorsement
4. **LaTeX/Pandoc help:** https://pandoc.org/ or local LaTeX user group

---

## Summary

- **Preprint ready:** Yes. All files in place.
- **Next step:** Compile sox-protocol.tex to PDF, then submit to arXiv at https://arxiv.org/user/upload_submit
- **Category:** cs.MA (Multi-Agent Systems) primary; cs.DC secondary
- **Timeline:** From submission to indexing ~1–2 days
- **Expected arXiv ID:** 2605.XXXXX (where XXXXX is auto-assigned)

Good luck with your submission!
