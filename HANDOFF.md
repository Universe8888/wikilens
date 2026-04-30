# Handoff — resume wikilens in a fresh chat

**Purpose:** Let a fresh Claude Code (or similar agent) session pick up wikilens exactly
where the previous session left off, without re-litigating decisions already made.

**Last updated:** 2026-04-30 (P2 complete, tagged `v0.2.0`)

---

## How to resume

Start a new chat. Tell the agent:

> We're continuing the `wikilens` project. Read `HANDOFF.md` for orientation, then
> `docs/p2-decisions.md` for what P2 shipped. P3 (Link Auditor agent) is next —
> plan it from scratch before writing code.

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

### P3 — Link Auditor (NEXT — not planned yet)

First real agent. Uses P2's ingested metadata to detect:

- broken wikilinks (target note does not exist),
- one-way links (A → B but no B → A),
- orphan notes (zero inbound links, at least one outbound).

No plan written yet. The next session should produce a P3 spec before
touching code, following the same SDD + HITL gate discipline used in P2.

### P4–P7

Roadmap in `README.md`. Do not touch until P3 ships.

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
- **Node.js:** installed; not needed for P2
- **Docker:** not required

## Files to read first

In this order:

1. `HANDOFF.md` (this file) — orientation
2. `docs/p2-decisions.md` — what P2 actually shipped
3. `BENCHMARK.md` — measured numbers
4. `README.md` — project manifesto
5. `ARCHITECTURE.md` — system sketch
6. `src/wikilens/cli.py` — current CLI surface
7. `gotchas.md` — failure register

## What to do when P3 completes

1. Update this `HANDOFF.md` — bump "Last updated", move P3 to COMPLETE,
   summarize the P4 plan.
2. Tag release `v0.3.0`.
3. Append benchmark numbers for the Link Auditor to `BENCHMARK.md`.
4. Suggest: "fresh chat for P4?"

## Glossary

- **SDD** — Specification-Driven Development (Phase 1 output of the Agentic Engineering Protocol)
- **PIV loop** — Plan → Implement → Validate (Phase 2 execution rhythm)
- **HITL gate** — Human-in-the-loop approval checkpoint
- **Gotcha log** — File tracking "what broke + how to avoid next time"

## Open questions for the next session (P3 kickoff)

- Should the Link Auditor emit its findings as JSON, markdown, or both?
- Orphan-detection heuristic: strict (zero inbound) or graded (low inbound)?
- Is the sample vault's existing broken-link content sufficient for an eval
  fixture, or should we seed deliberately-broken notes for the test corpus?
