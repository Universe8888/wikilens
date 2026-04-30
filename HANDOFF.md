# Handoff — resume wikilens in a fresh chat

**Purpose:** Let a fresh Claude Code (or similar agent) session pick up wikilens exactly
where the previous session left off, without re-litigating decisions already made.

**Last updated:** 2026-04-30 (end of P1, start of P2)

---

## How to resume

Start a new chat. Tell the agent:

> We're continuing the `wikilens` project. Read `HANDOFF.md` for orientation, then
> `docs/p2-plan.md` for the current phase. Start P2 at step 1 (install deps).

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

### P2 — RAG Core (NEXT — planned, not started)

Full plan lives at `docs/p2-plan.md`. Summary:

**Goal:** `wikilens ingest <vault>` + `wikilens query "..."` returning ranked chunks in <2s.

**Pass criterion:** Recall@5 ≥ 0.60 on 20-query eval set; p95 latency < 2s.

**Five design decisions (pre-made, override only with strong reason):**

1. **Vector store:** LanceDB (fallback: Chroma)
2. **Embedding:** BGE-small-en-v1.5 local via sentence-transformers
3. **Chunking:** heading-aware paragraph grouping, ~400 tokens, 15% overlap
4. **Agent orchestration:** N/A for P2
5. **LLM backend:** N/A for P2 (no generation yet)

**15 atomic steps** enumerated in `docs/p2-plan.md`, each with a validation check.

### P3–P7

Roadmap in `README.md`. Do not touch until P2 passes.

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
2. `docs/p2-plan.md` — current phase plan
3. `README.md` — project manifesto
4. `ARCHITECTURE.md` — system sketch
5. `src/wikilens/cli.py` — current CLI surface
6. `tests/test_smoke.py` — existing tests

## What to do when P2 completes

1. Update this `HANDOFF.md` — bump "Last updated", move P2 to COMPLETE, summarize P3 plan
2. Tag release `v0.2.0`
3. Update changelog / phase status
4. Suggest: "fresh chat for P3?"

## Glossary

- **SDD** — Specification-Driven Development (Phase 1 output of the Agentic Engineering Protocol)
- **PIV loop** — Plan → Implement → Validate (Phase 2 execution rhythm)
- **HITL gate** — Human-in-the-loop approval checkpoint
- **Gotcha log** — File tracking "what broke + how to avoid next time"

## Open questions for the next session

- Use `uv` for package management, or stick with `pip`?
- Install `sentence-transformers` now (downloads ~130 MB model weights on first run)?
- Any preference on LanceDB version pin?
