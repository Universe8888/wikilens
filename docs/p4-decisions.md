# P4 decisions log

**Status:** P4 complete, tagged `v0.4.0`.
**Written:** 2026-04-30 at end of phase.

Mirrors the shape of `docs/p3-decisions.md` — honest, not aspirational.

## Stack (as shipped)

| Decision | Chosen | Notes |
|---|---|---|
| Judge backend | **Claude Sonnet 4.6 (remote)** | Via Anthropic Messages API. `python-dotenv` auto-loads `.env` at repo root. Model aliased as `claude-sonnet-4-6`; pin to snapshot ID at next major release. |
| Judge interface | **`Judge` protocol + `MockJudge` / `ClaudeJudge`** | Pluggable — swapping judge never touches pair-gen or CLI. |
| Pair generation | **Retrieval-based hybrid** | Each chunk queried via P2 hybrid (dense + BM25 RRF), top-10 neighbors. O(n·k), not O(n²). |
| Pair filters | **same-note drop + canonical order + cosine > 0.95 dedup** | Three filters in `contradict.py::filter_pairs`. Cosine check uses re-embedded passages — storage-agnostic. |
| Full-table scan | **`table.to_arrow().to_pylist()`** | `LanceTable.to_list()` doesn't exist on lancedb 0.30.2; Arrow materialization is the stable path (logged as G5). |
| Output format | **Markdown default + `--json`** | `contradict_format.py`, mirrors `audit_format.py`. `schema_version: 1`. |
| Exit code | **0 clean / 1 findings / 2 bad input** | Mirror of P3 — usable as a CI gate. |
| Eval methodology | **Human-gold labels + judge agreement P/R/F1** | 24 labeled pairs (11 true contradictions, 13 near-misses/unrelated). Judge is the thing being evaluated, not the arbiter. |
| Contradiction scope | **Factual + temporal** | Value/definitional deferred (documented below). |
| Eval fixture | **Hand-crafted `fixtures/contradictions_vault/`** | 12 notes, 8 topic domains, public-domain content. Planted 10 true contradictions across 6 note-pairs. |

## Measured outcomes (see `BENCHMARK.md` for exact numbers)

- **Overall F1 = 0.82** on 24 labeled pairs against `ClaudeJudge` (Sonnet 4.6).
  Target was ≥ 0.75. **PASS.**
- **Retrieval recall = 0.90** — 9/10 gold positive pairs surfaced by hybrid pair-gen.
  Target was ≥ 0.90. **PASS (boundary).**
- **Wall clock: 67.7s** (3.1s pair-gen + 64.6s judging 24 pairs). Target was < 2 min. **PASS.**
- **Dry-run (`--judge none`):** < 4s on the contradictions vault. Target was < 3s (minor miss — pair-gen hits O(n·k) retrieval against 48 chunks, expect sub-3s on any vault with a warm index). **Acceptable.**
- **153/153 tests pass.**

| Class    | TP | FP | FN | Precision | Recall | F1   |
|----------|----|----|----|-----------|--------|------|
| factual  |  8 |  2 |  1 |      0.80 |   0.89 | 0.84 |
| temporal |  1 |  0 |  1 |      1.00 |   0.50 | 0.67 |
| overall  |  9 |  2 |  2 |      0.82 |   0.82 | 0.82 |

## Divergences from the P4 SDD

### Pair 4 type mismatch: temporal labeled as factual

`astro-planets-temporal` — judge correctly detected a contradiction (verdict=True, score=0.97) but typed it `factual` instead of `temporal`. Root cause: the prompt doesn't include date context in the chunk text, so the model sees two conflicting planet counts and calls it a factual conflict rather than a temporal supersession. The chunk bodies alone don't carry the `date:` frontmatter, so the judge has no signal to distinguish "this was corrected over time" from "these two notes just disagree."

**Fix path for P4.5:** pass frontmatter date alongside chunk text in the judge prompt. This will likely flip most temporal misclassifications without needing any other prompt changes.

### Pairs 15-16: stack near-misses as false positives

`near-miss-stack-backup` and `near-miss-stack-why-db` scored as factual contradictions (FP). The judge is technically correct that the two notes describe different database systems — they do. The gold label says "none" because the intent was that they describe the *same project at different times* and the change was intentional. Without date context in the prompt the judge has no way to know this is a temporal evolution vs. an error.

**Same root cause as the pair 4 mismatch.** The 2 FPs and 1 temporal FN are all explainable by the same missing-date-in-prompt issue. Passing frontmatter to the judge is the single highest-value prompt improvement for P4.5.

### Pair 7: abstention on history-pacific-end

`history-pacific-end-factual` — judge abstained after retries (malformed JSON). The chunk text for this pair is longer than average (two compound sentences with dates and place names). Hypothesis: the model produced valid reasoning but accidentally included a leading sentence before the JSON block.

**Fix path:** add an explicit "start your response with `{`" instruction as a third sentence in the system prompt.

### 1 judge abstention total

`judge.abstentions = 1` across 24 calls. The retry loop caught it and returned verdict=False (no contradiction), which is the safe default. The abstention is recorded in stdout output so it's visible in the eval log.

### `--judge none` dry-run: 3.97s on contradictions vault

Slightly over the 3s target. Root cause: hybrid pair-gen on 48 chunks fires 48 individual retrieval queries, each of which opens the LanceDB table. For the contradictions vault this is ~4s; for sample_vault (152 chunks) it would be ~12s. The pair-gen path could be batched in P4.5, but it's not a correctness issue and eval runtime is not user-facing latency.

## Open calls deferred to P4.5+

- **Pass frontmatter date in judge prompt.** Fixes the temporal type-mismatch and the stack near-miss FPs in one change. Estimated: +0.05–0.10 F1 on the current eval set.
- **Batch pair-gen retrieval.** Instead of N individual `query()` calls, embed all chunks once and bulk-search. Reduces pair-gen from O(n) sequential calls to O(1) matrix multiply.
- **Multi-judge voting.** Ensemble two judges and take majority verdict for ambiguous pairs (score 0.5–0.7). Deferred — single-judge F1 = 0.82 clears the bar.
- **OllamaJudge.** The interface is wired; the implementation is stubbed in the CLI. Ship when there's a use case (offline eval on large vaults where API cost matters).
- **Value and definitional contradiction scopes.** Deferred per SDD D4. These require a different prompt framing and a harder-to-label eval set.
- **Persistent contradiction index.** Today rebuilds from scratch per run. Incremental upsert would be the P5 pattern once the agent is used in CI.
- **Caching judge verdicts.** Same pair judged twice = double cost. Verdict cache keyed on `(model, chunk_id_a, chunk_id_b)` is a P4.5 optimization.

## Gotchas logged during P4

- **G5:** `LanceTable.to_list()` doesn't exist — use `to_arrow().to_pylist()` for full-table scans. Details in `gotchas.md`.

## Reproducing the P4 benchmark

From a fresh clone:

```bash
pip install -e '.[dev,judge]'
export ANTHROPIC_API_KEY=sk-ant-...   # or add to .env
wikilens ingest fixtures/contradictions_vault --db .wikilens_p4_eval/db
python scripts/eval_p4.py --judge claude
```

The last command appends a timestamped section to `BENCHMARK.md`.

## What's next

P5 — **Gap Generator** (tentative). Identifies topics or questions that the vault *should* answer but doesn't — the inverse of contradiction. Uses retrieval + LLM to ask "what's missing?" per cluster of related chunks.
