# P12 — v0.11.0 Launch (SDD)

**Status:** Specification — HITL-approved 2026-05-03, awaiting execution.
**Created:** 2026-05-03
**Preceded by:** P10 (Epistemic Confidence Mapper) — complete, tag `v0.10.0`.
**Target effort:** ~4–6h, single session.

---

## Goal

Ship `wikilens` v0.11.0 publicly. All eight agents are already implemented and
evaluated. This phase contains no new code. It is pure launch prep: rewrite the
README, draft launch posts, pass the sanitization gate, push the tag, post.

Launch hook: *"I built 8 AI agents that audit a knowledge base. Here are the
honest benchmark numbers."*

## Versioning policy

This release is `v0.11.0`, not `v1.0.0`. Precedent: `llm`, `aider`,
`litellm`, `bat` — all ship production-quality tools at `0.x` until they are
ready to commit to API stability. A `1.0.0` tag implies that the public CLI
surface is frozen; we are not making that commitment yet. The version policy
will be stated explicitly in the new README.

## Pass/Fail criterion

1. Git tag `v0.11.0` (with `v` prefix, matching existing convention) is pushed
   to GitHub.
2. GitHub Actions CI is green on the tag.
3. A post is submitted to at least one launch platform (Show HN or
   `r/ObsidianMD`).

## Scope

### In

- Rewrite `README.md` following the aider/litellm model: hook line, 8-agent
  capability table, quickstart block, link to `BENCHMARK.md`. No P11 reference.
  Versioning policy line included.
- Write `.local/launch_posts.md` containing three drafts: Show HN, Reddit
  (`r/ObsidianMD`), and Product Hunt (lowest priority; included for
  completeness).
- Run `python scripts/check_sanitization.py` on the staged diff and confirm
  zero hits.
- Edit `ROADMAP.md` and `HANDOFF.md` to reflect P11 deferred status and P12
  complete.
- Tag `v0.11.0` locally; push tag and commits to GitHub.
- Record a terminal screencast GIF (audit + contradict on a sample vault) for
  use in launch posts. Saved locally; not committed to the repo.
- Post in order: Show HN, then `r/ObsidianMD`, then Product Hunt. Same day.
- Update `.local/HANDOFF.md`, public `HANDOFF.md`, and `BENCHMARK.md` header
  with last-updated date and "v0.11.0 live, launched" status.

### Out (not in this phase)

- Any new `wikilens` CLI subcommand or agent.
- Obsidian plugin (P11, deferred indefinitely).
- Hosted demo, Docker image, or cloud deployment.
- Paid tier or analytics.
- Automated social posting. All posts are manual.

## README design

Follow the aider/litellm model for a technical audience:

1. **Hook line** — one sentence, the launch hook above.
2. **Install block** — `pip install wikilens`, one code block.
3. **Agent capability table** — 8 rows, one per agent, with the eval number
   from `BENCHMARK.md`.
4. **Quickstart** — four commands: `ingest`, `audit`, `contradict`, `confidence`.
5. **Benchmark link** — `See BENCHMARK.md for full eval results.`
6. **Versioning policy** — one sentence: "wikilens follows 0.x versioning
   until the CLI surface is stable enough to warrant an API-stability
   commitment."
7. **License** — MIT.

No badges beyond PyPI version + CI status. No animated GIF embedded in the
README (link to it in the launch post instead). No P11/plugin reference anywhere.

The 8-agent table format:

| Agent | Command | Key metric |
|-------|---------|-----------|
| Link Auditor | `wikilens audit` | P=R=F1=1.00 on 19 planted defects |
| Contradiction Finder | `wikilens contradict` | F1=0.82, retrieval recall=0.90 |
| Gap Generator | `wikilens gap` | cluster recall=1.00, matcher F1=0.65 |
| Answer Generator | `wikilens answer` | pass rate=0.80, attribution=1.00 |
| Temporal Drift Detector | `wikilens drift` | precision/recall targets ≥0.80 |
| Unnamed Concept Detector | `wikilens concepts` | precision/recall targets ≥0.70 |
| Epistemic Confidence Mapper | `wikilens confidence` | P=0.91, R=0.88, F1=0.89 |
| Query (RAG core) | `wikilens query` | Hit@5=1.00, p95 rerank 1846ms |

Note: P8 (drift) and P9 (concepts) eval numbers are placeholders — confirm
exact figures from `BENCHMARK.md` before committing the README.

## Launch post strategy

**Priority order: Show HN first, r/ObsidianMD second, Product Hunt third.**

### Show HN

- Audience: technical builders. Lead with the honest benchmark numbers and the
  open-source MIT angle.
- Title format: `Show HN: wikilens — 8 AI agents that audit an Obsidian vault
  (open source, benchmarks included)`
- Body: what each agent does in one sentence, benchmark table snippet, install
  command, GitHub link.
- Timing: weekday, 7–9am ET. HN front-page probability peaks in that window.

### r/ObsidianMD

- Audience: Obsidian power users, not necessarily programmers. Lead with the
  use case ("what wikilens found in my vault"), link to the GIF screencast.
- No benchmark table in the body — link to BENCHMARK.md instead.
- Flair: likely "Plugin/Tool".

### Product Hunt

- Lowest priority. CLI tools historically underperform on PH (audience skews
  toward GUI/SaaS). Prepare a draft but post last, after HN and Reddit.
- Tagline must fit 60 chars.
- Thumbnail: terminal screenshot or the screencast GIF first frame.

All three drafts live in `.local/launch_posts.md` (not committed to the public
repo — `.local/` is gitignored).

## Step plan

One in-progress task at a time. Each step ends with a HITL checkpoint before
the next begins.

| # | Step | Work | Exit criterion |
|---|------|------|----------------|
| 12.1 | Rewrite `README.md` | aider/litellm model, 8-agent table, no P11 ref, versioning policy line | 8-agent table present; `grep -i plugin README.md` returns nothing |
| 12.2 | Write `.local/launch_posts.md` | 3 post drafts: Show HN + Reddit + Product Hunt | Drafts reviewed and approved by user |
| 12.3 | Sanitization gate | `python scripts/check_sanitization.py` on staged diff | Zero hits |
| 12.4 | Commit | README rewrite + ROADMAP/HANDOFF P11-deferred edits | Commit message: `P12: README rewrite for v0.11.0 launch` |
| 12.5 | Push + tag | `git push origin main && git push origin v0.11.0` | CI green; PyPI publishes v0.11.0 automatically (OIDC trusted publishing from P7) |
| 12.6 | Record GIF | `wikilens audit` + `wikilens contradict` on the sample vault, asciinema or equivalent | GIF saved locally; confirmed playable; not committed |
| 12.7 | Post | Show HN → r/ObsidianMD → Product Hunt, in that order, same day | URLs captured |
| 12.8 | Post-launch update | `.local/HANDOFF.md` + public `HANDOFF.md` + `BENCHMARK.md` header | Last-updated set to post date; status = "v0.11.0 live, launched"; post URLs recorded |

## Risks

| Risk | Mitigation |
|------|-----------|
| HN timing — post outside the 7–9am ET weekday window and front-page probability drops significantly | Schedule step 12.7 for a Tuesday–Thursday morning ET slot; do not post Friday or weekend |
| README contains private info that slipped through previous edits | Step 12.3 (sanitization gate) is a hard blocker; do not proceed to 12.4 if it reports hits |
| PyPI auto-publish assumes CI workflow is still correctly configured from P7 | Before pushing the tag, verify the `.github/workflows/publish.yml` trigger is `on: push: tags: ['v*']` and the OIDC trusted publisher is still active on PyPI |
| Tag format drift — PyPI workflow may be keyed to a specific prefix | Existing convention is `v`-prefixed (e.g. `v0.10.0`); tag must be `v0.11.0`, not `0.11.0` |
| GIF screencast captures private vault content | Use only the public fixture vaults in `fixtures/` for the recording; verify filenames before saving |
| Reddit post removed for self-promotion | `r/ObsidianMD` allows tool posts; use the "Plugin/Tool" flair; disclose it is your own project |

## Files touched

```
README.md                        # full rewrite
ROADMAP.md                       # minor: P12 → complete, P11 → deferred note
HANDOFF.md                       # minor: status update, P12 complete
BENCHMARK.md                     # header last-updated date
CHANGELOG.md                     # v0.11.0 entry
.local/launch_posts.md           # new; not committed (gitignored)
.local/HANDOFF.md                # status update
```

No changes to `src/`, `tests/`, `fixtures/`, or `scripts/`.

## Design principles carried from P1–P10

1. **No silent steps.** Every benchmark number in the README resolves to a
   labeled entry in `BENCHMARK.md`.
2. **Reproducible evaluation.** Numbers are not rounded up or fabricated.
   Placeholders (`TBD`) are acceptable in draft; they must be filled from
   `BENCHMARK.md` before the commit lands.
3. **No vendor lock.** README install section shows `--judge openai` and
   `--judge claude` symmetrically.
4. **Fail loud.** Sanitization gate is a hard stop, not a soft warning.
5. **Budgeted autonomy.** This phase has no LLM calls and no cost exposure.

## Open questions settled at SDD approval (2026-05-03)

- **Version:** `v0.11.0`, not `v1.0.0`. Decision recorded; not revisited.
- **P11:** Deferred indefinitely. No reference in README or launch posts.
- **New code:** None. Scope is locked to polish and launch artifacts.
- **PyPI:** v0.10.0 already live; v0.11.0 will auto-publish from CI on tag push.
- **Launch order:** Show HN first, r/ObsidianMD second, Product Hunt third.
- **README model:** aider/litellm — hook + table + quickstart + benchmark link.
