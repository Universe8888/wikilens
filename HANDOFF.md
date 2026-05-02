# Handoff — resume wikilens in a fresh chat

**Purpose:** Let a fresh Claude Code (or similar agent) session pick up wikilens exactly
where the previous session left off, without re-litigating decisions already made.

**Last updated:** 2026-05-02 (P7 complete, tag `v0.7.0`, live on PyPI)

---

## How to resume

Start a new chat. Tell the agent:

> We're continuing the `wikilens` project at `C:\Projects2026\wikilens\`.
> P7 is complete (`v0.7.0` live on PyPI). Read `.local/AGENT_BRIEFING.md`,
> then `.local/HANDOFF.md`, then `HANDOFF.md`, then `ROADMAP.md`.
> Next step: **P8** — Temporal Drift Detector. Plan before writing code.

That's it.

---

## What wikilens is

Open-source agentic intelligence layer for Markdown/Obsidian vaults. RAG core + evaluated
metacognitive agents (link auditor, contradiction finder, gap generator). Built in public
under the MIT license.

- **Repo:** https://github.com/Universe8888/wikilens
- **Branch for main work:** `main`

## Status — where we are

### P1 — Bootstrap (COMPLETE, 2026-04-30)

- Repo live, public, MIT
- README manifesto
- ARCHITECTURE.md sketch
- pyproject.toml (Python 3.12, hatchling, ruff, pytest)
- CLI stub (`wikilens --help|--version` functional; subcommands stubbed)
- 4/4 smoke tests pass
- `.gitignore` with PII guards; `.env.example`

### P2 — RAG Core (COMPLETE, 2026-04-30, tag `v0.2.0`)

- `wikilens ingest <vault>` + `wikilens query "..."` working end-to-end.
- Four retrieval modes: `dense`, `bm25`, `hybrid` (RRF), `rerank` (cross-encoder).
- Hit@5 = 1.00 in every mode on the 20-query eval set (target was 0.60).
- p95 rerank latency = 1846ms (target was < 2s); dense alone is 37ms p95.
- 86 tests pass.
- Decisions log: `docs/p2-decisions.md`. Benchmark: `BENCHMARK.md`.
- Gotchas: G1 (torchcodec on Windows), G2 (LanceDB paginated response),
  G3 (regex catastrophic backtracking on YAML flow lists).

### P3 — Link Auditor (COMPLETE, 2026-04-30, tag `v0.3.0`)

- `wikilens audit <vault>` detects broken wikilinks, one-way links,
  orphan notes, and shadowed basenames.
- Markdown by default, `--json` flag, `--only` class filter.
  Exit 0 clean / 1 findings / 2 bad input — usable as a pre-commit or CI gate.
- On the hand-labeled `fixtures/audit_vault/` (16 notes, 19 planted
  defects), every class scores precision = recall = F1 = 1.00.
- 115 tests pass.
- Decisions log: `docs/p3-decisions.md`. Benchmark: `BENCHMARK.md`.
- Gotcha: G4 (reciprocity check on directed graph always-true by construction).

### P4 — Contradiction Finder (COMPLETE, 2026-04-30, tag `v0.4.0`)

- `wikilens contradict <vault> --judge claude` surfaces contradicting chunk pairs,
  scored and typed (factual / temporal), with reasoning.
- Retrieval-based pair generation (P2 hybrid, O(n·k)). Three filters: same-note
  drop, canonical ordering, cosine > 0.95 near-duplicate drop.
- `ClaudeJudge` via Anthropic SDK (`claude-sonnet-4-6`). `MockJudge` for
  `--judge none` dry-runs. `--sample`, `--min-score`, `--only`, `--json` flags.
- Exit 0 clean / 1 findings / 2 bad input. API key via `ANTHROPIC_API_KEY` env
  var (auto-loaded from `.env` via python-dotenv).
- On the hand-labeled `fixtures/contradictions_vault/` (12 notes, 24 labeled
  pairs): **overall F1 = 0.82** (target ≥ 0.75 ✓), retrieval recall = 0.90
  (target ≥ 0.90 ✓), wall clock 67.7s (target < 2 min ✓).
- 153 tests pass.
- Decisions log: `docs/p4-decisions.md`. Benchmark: `BENCHMARK.md`.
- Gotcha: G5 (`LanceTable.to_list()` doesn't exist — use `to_arrow().to_pylist()`).
- Known improvement for P4.5: pass frontmatter date in judge prompt to fix
  temporal type misclassification and stack near-miss FPs (all trace to same root cause).

### P5 — Gap Generator (COMPLETE, 2026-05-01, tag `v0.5.0`)

- `wikilens gap <vault> --judge claude` clusters vault chunks via k-means on
  BGE embeddings, then calls ClaudeGenerator per cluster to surface unanswered
  questions implied by the vault's own content.
- `MockGenerator` + `SubstringMatcher` for `--judge none` dry-runs (no API).
- Budgeted autonomy caps: `--min-cluster-size`, `--max-clusters`, `--sample`.
- `ClaudeMatcher` with pinned 1–5 rubric for eval; borderline decisions logged
  to `docs/p5-matcher-notes.md` for human review.
- **Cluster-stage recall = 1.00** (10/10 gold gaps surfaced). **F1 = 0.65**
  (target ≥ 0.60). Generation stage: 56.6s on 12-note vault.
- **224/224 tests pass.** +71 new tests since P4.
- Decisions log: `docs/p5-decisions.md`. Benchmark: `BENCHMARK.md`.

### P6 — Answer Generator (COMPLETE, 2026-05-01, tag `v0.6.1`)

- `wikilens answer <vault> --gaps <gap-json>` consumes `gap --json` output,
  retrieves supporting chunks per gap, drafts structured note stubs.
- Stubs: YAML frontmatter + "What the vault says" (cited) + "Evidence gaps" +
  "Related notes" (`[[wikilinks]]`) + "Citations". Print-only by default;
  `--write --out <dir>` materialises `.md` files (no-overwrite policy).
- `MockDrafter` / `OpenAIDrafter` / `ClaudeDrafter` — default `openai/gpt-4o`.
- `check_attribution` — automated parser verifying every `[^N]` resolves to a
  retrieved chunk ID. No LLM.
- **Pass rate = 0.80** (8/10 gold gaps, all 4 axes ≥ 4). Attribution rate = 1.00.
  Wall clock 90s for 10 gaps. **313/313 tests pass.**
- Decisions log: `docs/p6-decisions.md`. Benchmark: `BENCHMARK.md`.
- Gold eval fixture: `fixtures/eval/p6_answer_sketches.json` (10 sketches).
  Eval harness: `scripts/eval_p6.py`.

### P7 — PyPI + Installer Polish (COMPLETE, 2026-05-02, tag `v0.7.0`, live on PyPI)

- `pip install wikilens` works from PyPI. OIDC trusted publishing via GitHub Actions.
- CI matrix expanded to Ubuntu + Windows on Python 3.12.
- First-run model-download notice on `ingest` and `query`.
- CHANGELOG.md added; Development Status bumped to Alpha.
- 317/317 tests pass.

### P8 – P12

Full phase list with launch hooks and eval targets: [`ROADMAP.md`](./ROADMAP.md).

- **P8** — Temporal Drift Detector. Walks vault `git log` for belief changes over time.
- **P9** — Unnamed Concept Detector. Finds clusters paraphrasing the same unnamed idea.
- **P10** — Epistemic Confidence Mapper. Classifies claims on hypothesis → verified fact.
- **P11** — Obsidian Plugin. Thin wrapper over the CLI; marketplace discovery.
- **P12** — v1.0 launch. Product Hunt + Show HN + `r/ObsidianMD`.

## Hard constraints (do not violate)

1. **No private content in the public repo.** Sanitization gate before every commit.
   Never ingest private notes into public fixtures.
2. **Every agent ships with an eval.** No "vibes-based" merges.
3. **One public artifact per phase:** repo push + writeup + changelog entry.
4. **Follow the Agentic Engineering Protocol:** SDD → HITL approval → PIV loop per step.

## Operating style

- Terse is good. Skip preamble.
- Confirm before destructive or public actions. Ask before pushing to a branch, before
  installing new deps, before widening repo visibility.
- If offering options, rank them with a recommended default; don't force a pick from
  equal-weighted options.
- Test actions end-to-end (install + CLI works on a fresh shell) before declaring done.

## Tooling environment

- **OS:** Windows 11, bash shell
- **Python:** 3.12
- **Node.js:** installed; not needed for P2–P4
- **Docker:** not required

## Files to read first

In this order:

1. `HANDOFF.md` (this file) — orientation
2. `docs/p4-decisions.md` — what P4 shipped (contradiction finder)
3. `docs/p3-decisions.md` — what P3 shipped (link auditor)
4. `docs/p2-decisions.md` — what P2 shipped (retrieval foundation)
5. `BENCHMARK.md` — measured numbers for all eval suites
6. `README.md` — project manifesto
7. `ARCHITECTURE.md` — system sketch
8. `src/wikilens/cli.py` — current CLI surface
9. `gotchas.md` — failure register (G1–G5)

## What to do when P7 starts

P7 — **PyPI + installer polish** (per `ROADMAP.md`). This is the public-launch gate:
`pip install wikilens` from PyPI, clean first-run UX, CI/CD pipeline.

1. Read `ROADMAP.md` for P7 scope.
2. Start a fresh chat with updated HANDOFF prompt.
3. Tag `v0.7.0` locally when P7 ships.

## Release Readiness Fixes

- Secured `wikilens answer --write` so generated stub titles cannot escape `--out`.
- Made `wikilens ingest` honor documented full rebuild semantics by clearing stale LanceDB rows.
- Made `.[dev]` sufficient for test, lint, and typecheck workflows.
- Added `Makefile` targets for local checks and benchmark reproduction.
- Added GitHub Actions CI for Python 3.12.
- Synced README and ROADMAP around P6 shipped / P7 next.

Validation:
- `python -m ruff check .`
- `python -m mypy src`
- `python -m pytest`
- `make check`

## Glossary

- **SDD** — Specification-Driven Development (Phase 1 output of the Agentic Engineering Protocol)
- **PIV loop** — Plan → Implement → Validate (Phase 2 execution rhythm)
- **HITL gate** — Human-in-the-loop approval checkpoint
- **Gotcha log** — File tracking "what broke + how to avoid next time"
