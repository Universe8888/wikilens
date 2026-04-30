# P3 decisions log

**Status:** P3 complete, tagged `v0.3.0`.
**Written:** 2026-04-30 at end of phase.

A record of what was actually chosen during P3 and where reality diverged from
the SDD kicked off at the start of the phase. Mirrors the shape of
`docs/p2-decisions.md` — honest, not aspirational.

## Stack (as shipped)

| Decision | Chosen | Notes |
|---|---|---|
| Graph model | **In-memory, rebuilt per run** | Nodes = `source_rel` without `.md`, edges = resolved wikilink targets. Frozen dataclasses, O(n) build, sub-second on 10k-note corpora. |
| Link parsing | **Reused P2 `extract_links()`** | Zero duplication — same wikilink regex, same code-block stripping. Pipeline's `extract_links` was already public API, it just wasn't called anywhere yet. |
| Target resolution (C1) | **Case-insensitive basename OR vault-relative full path** | Matches how Obsidian resolves `[[X]]`. `.md` suffix stripped if the user wrote one. Both forms indexed into a single lookup dict so resolution is one `dict.get`. |
| Orphan heuristic (C5) | **Strict zero-inbound, ≥1 outbound** | Graded thresholds rejected as premature abstraction — no eval signal behind them. Broken outbound counts as outbound (a note whose only link is broken is *more* orphan, not less). |
| Shadowed basename (Q4) | **Resolve to all candidates, emit warning** | Rejected "broken" and "require full path" framings. Warning surfaces a real bug pattern (silent future-shift if one of the candidates gets renamed) without blocking normal workflows. |
| Self-link handling (C6) | **Drop at graph-build, before broken-check** | A pure self-link (`[[a]]` inside `a.md`) contributes nothing to outbound or inbound. Never treated as broken. |
| Embeds (C7) | **Count as links** | `![[X]]` contributes an edge identical to `[[X]]`. Obsidian treats them as references; embed-only backlinks should resolve reciprocity. |
| Output | **Markdown default + `--json` flag + `--only` filter** | Q1 locked at planning. JSON has a `schema_version: 1` field — bump on breaking changes. |
| Exit code | **0 clean, 1 findings, 2 bad input** | Makes `wikilens audit` usable as a pre-commit / CI gate without extra wiring. |
| Link graph persistence | **Not persisted** | Q5 locked at planning. Rebuild per run is cheap and avoids LanceDB schema churn. Revisit if agents start re-reading the graph across invocations. |

## The four detector classes

All four share one graph build (`build_link_graph`) and run as pure functions
over the `LinkGraph`. Determinism is guaranteed by sort keys on every
dataclass and sorted iteration order in each detector.

| Class | What it detects |
|---|---|
| `broken`   | Wikilinks whose target resolves to zero files in the vault. |
| `one_way`  | Resolved A→B with no B→A reciprocal. Shadowed links are checked per-candidate. |
| `orphans`  | Notes with ≥1 outbound wikilink and zero inbound. Strict. |
| `shadowed` | Wikilinks resolving to 2+ notes sharing the same basename across folders. |

## Measured outcomes (see `BENCHMARK.md` for the exact table)

- **Precision = Recall = F1 = 1.00** on all four classes against the
  `fixtures/audit_vault/` ground truth (16 notes, 19 findings planted).
- **Runtime:** sub-second on the fixture vault; no model loading, no LanceDB
  open. The eval harness completes in well under the time the shell takes
  to start Python.
- **Organic-broken-link smoke on `fixtures/sample_vault/`** (the P2 corpus):
  36 nodes, 4 unintentional broken links surfaced
  (`atp-cycle`, `chloroplasts`, `chlorophyll`, `calvin-cycle-deep-dive`).
  Not planted — these are real artifacts of the P2 author drafting notes.
  Encouraging signal that the detector catches the kinds of things a user
  actually leaves behind.

## Divergences from the P3 SDD

### One reciprocity bug caught by the test suite

The first version of `find_one_way_links()` asked "does the source appear in
the target's inbound set?" — which is **always true** by construction of the
graph (if A links to B, A is in B's inbound). The correct question is "does
the target appear in the *source's* inbound set?" — i.e., does the target
link back. The unit test `test_find_one_way_links` failed on the first run
and the fix was a one-line swap. Tests did their job: a subtle graph-symmetry
bug that would have quietly produced nonsense output was caught before
anyone ran the CLI.

### BENCHMARK.md header generalized mid-phase

Phase 3.5 moved the single-vault intro paragraph up top and reworded it to
cover both eval suites additively. Both `scripts/eval_p2.py` and
`scripts/eval_p3.py` were updated so future runs preserve the generalized
header instead of re-introducing the old prose. Cosmetic but prevents doc
drift when the next eval phase lands.

### No new modules beyond `audit` and `audit_format`

The SDD allowed for a CLI-adjacent helpers module if output formatting got
messy. It didn't — splitting into `audit.py` (graph + detectors) and
`audit_format.py` (markdown/JSON) was enough. The CLI glue in `cli.py`
stayed thin.

## Open calls deferred to P4+

- **Markdown inline-link validation.** `[text](./other.md)` links are still
  parsed by `extract_links` but not checked by the auditor. The reason is
  that markdown links encode *intent* (browser-resolvable URL, relative file
  path, anchor jump) that wikilinks don't — a principled resolver needs to
  distinguish those cases. Fair work, wrong phase.
- **Heading-anchor validation.** `[[Note#Section]]` currently resolves iff
  `Note` exists; the `#Section` fragment is ignored. Validating the anchor
  requires reading the target's body and slug-comparing each heading. Cheap,
  but out of scope for P3's graph-only detectors.
- **Incremental audit.** Today's `audit` walks the entire vault every run.
  At 16 notes it's instant; at 10k it's still sub-second. No one has asked
  for incremental yet.
- **Auto-fix / suggestion.** P3 only *reports*. No rewrites, no
  "did you mean…", no LLM-in-the-loop. Each of those is a distinct agent.
- **LanceDB persistence of the link graph.** Q5 locked this at planning.
  If a future agent (contradiction-finder?) needs the same graph, pull the
  build out of `audit.py` and persist it once — not before.
- **Graded orphan thresholds.** Q2 locked strict at planning. If a user
  says "but `notes/foo` has 1 inbound from a dead-end log entry, it's
  *basically* an orphan," a `--min-inbound N` flag is a one-line addition.

## Gotchas logged during P3

Full detail goes in `gotchas.md` at the repo root when updated:

- **G4:** `find_one_way_links` initial implementation inverted the reciprocity
  check (source always appears in target's inbound set, because source → target
  is how the inbound set is built). The correct check is "does target appear
  in source's inbound?" — i.e., does the target reciprocate. Tests caught it;
  the fix is a single-line swap. Moral: when writing a symmetric/reciprocal
  check over a directed graph, write the test *before* the implementation
  and trace an example by hand before trusting the expression.

## Reproducing the P3 benchmark

From a fresh clone:

```bash
pip install -e '.[dev]'
python scripts/eval_p3.py
```

Second command appends a timestamped section to `BENCHMARK.md`. No LanceDB
ingest required — the auditor operates directly on the filesystem.

## What's next

P4 — **Contradiction Finder**. First agent that actually needs retrieval
(find candidate pairs of chunks that might contradict) + an LLM judge
(score whether they actually do). Eval will be harder than P3's set-based
P/R/F1 — contradiction is judgment-heavy. Gold-standard dataset will be
the bottleneck, not the code.
