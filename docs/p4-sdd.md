# P4 — Contradiction Finder (SDD)

**Status:** Specification — awaiting HITL approval before any implementation.
**Created:** 2026-04-30
**Preceded by:** P3 (link auditor) — complete, tag `v0.3.0`
**Target effort:** ~20h, part-time

---

## Goal

`wikilens contradict <vault>` surfaces pairs of chunks from the vault that contradict each other — scored, typed, and explained — so the user can reconcile or prune stale notes. Ships with a hand-labeled eval that measures **judge agreement with human gold labels** (P/R/F1 of the judge, not of the user).

This is the first phase that introduces:

- A **cognitive kernel** — an LLM judge for pairwise reasoning.
- A **network-allowed code path** — Anthropic API, gated behind `--judge`.
- An **eval shape** where ground truth is subjective and must be human-labeled.

## Pass/Fail criterion

`wikilens contradict fixtures/contradictions_vault` with `--judge claude`:

1. Retrieves the planted contradictions (recall of candidate-pair stage ≥ 0.90).
2. Judge verdicts match human gold labels: **Precision ≥ 0.80, Recall ≥ 0.70, F1 ≥ 0.75** on factual + temporal classes.
3. End-to-end wall clock on the contradictions vault: **< 2 minutes** with `--judge claude` on ~40 pairs; **< 3 seconds** with `--judge none` (dry-run, pair-gen only).
4. `--judge none` mode produces the full candidate-pair list without any API calls (validates the plumbing in isolation).
5. 100% of existing tests (115) still green; new tests green.

No "vibes" pass — numbers or it didn't ship.

## Scope

### In

- Retrieval-based candidate pair generation using P2's hybrid mode.
- Pair filters: same-note dedup, cosine > 0.95 dedup, canonical ordering.
- Pluggable judge interface with three backends: `none` (mock/dry-run), `claude` (Anthropic Sonnet 4.6), `ollama` (local, optional).
- Structured judge output: `{verdict, type, score, reasoning}` with JSON-mode parsing.
- `wikilens contradict <vault>` CLI subcommand — markdown default, `--json`, `--only {factual,temporal}`, `--sample N`, `--judge {none,claude,ollama}`, `--top-k K`, `--min-score FLOAT`.
- Exit code gate: 0 clean / 1 findings / 2 bad input (mirror P3).
- Hand-crafted `fixtures/contradictions_vault/` — 8-10 notes, 15 true contradictions + 20 near-misses + 5 unrelated pairs = ~40 pairs labeled.
- `fixtures/eval/p4_ground_truth.json` — human gold labels per pair.
- `scripts/eval_p4.py` — runs the judge against gold labels, reports P/R/F1 per type, appends to `BENCHMARK.md`.
- Unit tests for pair generation, filter, mock judge, CLI wiring.
- Documentation: `docs/p4-decisions.md`, README update, `BENCHMARK.md` section.
- Sanitize + commit gate enforced per phase.

### Out (deferred)

- Value contradictions ("I prefer X" vs "I prefer Y") — context-dependent, no clean pass/fail.
- Definitional contradictions ("a tomato is a fruit" vs "a tomato is a vegetable") — often correct in different frames.
- Multi-judge voting (ensemble of two or more judges).
- Judge self-consistency / chain-of-thought ensembling.
- Exhaustive O(n²) pair gen or topic-clustered pair gen.
- Auto-reconciliation / suggested rewrites.
- LLM-in-the-loop for pair generation.
- Persistent contradiction index in LanceDB (rebuild per run, like P3).
- Caching of judge verdicts across runs.
- Streaming / incremental judge calls.
- Rate limiting / retry logic beyond the Anthropic SDK defaults.

## Design decisions

### D1. LLM judge — **Claude Sonnet 4.6** (approved)

| Option | Pros | Cons |
|---|---|---|
| **Claude Sonnet 4.6 (remote)** ✅ | Fast iteration on judge prompt; strong reasoning; cheap (~$0.001/pair) | First network dep; requires API key |
| Claude Opus 4.7 | Strongest reasoning | ~10× cost; overkill for pairwise judgments |
| Ollama local (qwen2.5:7b) | Offline, free | Slower eval, noisier verdicts, install friction |

**Pick:** Sonnet 4.6 default. Ollama adapter shipped but not required for the eval gate. `ANTHROPIC_API_KEY` read from env; documented in `.env.example`; never logged.

### D2. Pair generation — **retrieval-based, filtered** (approved)

Algorithm:

1. For each chunk `C` in the vault, call `query(text=C.text, mode="hybrid", k=10)`.
2. Emit candidate pair `(C, neighbor)` for each neighbor that isn't `C` itself.
3. Dedup canonically (`chunk_id_a < chunk_id_b`).
4. Drop pairs from the same source note.
5. Drop pairs with cosine similarity > 0.95 (likely near-duplicates, not contradictions).
6. Result: a list of `CandidatePair` dataclasses with both chunk bodies + metadata.

Complexity: O(n · k) = O(n · 10) on chunk count `n`. On a 10k-chunk vault, ~100k candidates pre-filter, ~30-50k post-filter. Judge cost is the dominant constraint — `--sample N` caps judge calls for smoke runs.

**Rejected:**

- **Exhaustive O(n²):** blows up past ~500 chunks.
- **Topic-clustered:** adds clustering complexity + tuning knob with no eval signal behind it yet. Revisit if retrieval-based misses too many true contradictions.

### D3. Eval methodology — **human-gold labels, judge agreement metric** (approved)

- The **judge is the thing being evaluated**, not the arbiter.
- Human labels once (~30-50 pairs in `fixtures/contradictions_vault/`).
- Eval = "does the judge's verdict agree with the gold label?" → compute P/R/F1 per class.
- Single judge for v1. Multi-judge voting deferred until we know single-judge variance.
- No "RLAIF trap" — AI evaluating AI is brittle on real-world edge cases.

**Label schema** (`fixtures/eval/p4_ground_truth.json`):

```json
{
  "schema_version": 1,
  "pairs": [
    {
      "pair_id": "stable-hash",
      "chunk_a_id": "...",
      "chunk_b_id": "...",
      "label": "factual",         // factual | temporal | none
      "gold_verdict": true,       // is this actually a contradiction?
      "notes": "human rationale, one line"
    }
  ]
}
```

### D4. Contradiction scope — **factual + temporal only** (approved)

| Class | Definition | Example |
|---|---|---|
| `factual` | Two chunks assert incompatible facts about the same entity/attribute. | A: "Paris is the capital of France." B: "Berlin is the capital of France." |
| `temporal` | Two chunks assert X vs ¬X with different dates, and the later one supersedes. Frontmatter `date` field (or git mtime fallback) provides the signal. | A (2022): "We use Postgres." B (2024): "We migrated to MySQL." |
| `none` | Everything else — values, definitions, framing, unrelated. | — |

Judge prompt returns `type ∈ {factual, temporal, none}`. `none` means "not a contradiction we score." Output schema is forward-compatible with value/definitional if we add them in P4.5.

### D5. Eval fixture — **hand-crafted `fixtures/contradictions_vault/`** (approved)

Structure (~8-10 notes, ~30-40 chunks, ~40 labeled pairs):

```
fixtures/contradictions_vault/
├── capitals/
│   ├── paris.md        # "Paris is the capital of France"
│   └── berlin.md       # "Berlin is the capital of France" — planted factual
├── stack/
│   ├── 2022-db.md      # dated 2022-06 — "We use Postgres"
│   └── 2024-db.md      # dated 2024-03 — "We migrated to MySQL" — planted temporal
├── near-miss/
│   ├── tomato-fruit.md # "A tomato is a fruit (botanically)"
│   └── tomato-veg.md   # "A tomato is a vegetable (culinarily)" — NOT a contradiction
└── unrelated/
    ├── photosynthesis.md
    └── bread-recipe.md
```

Label density: ~15 true contradictions (factual + temporal), ~20 near-misses (same topic, non-contradictory — tests FP rate), ~5 unrelated pairs (tests pair filter).

`sample_vault/` remains a **smoke corpus** — run the pipeline on it end-to-end, eyeball the output, do not gate on organic finds.

## Deliverables checklist

- [ ] `src/wikilens/contradict.py` — pair generation, filter, `CandidatePair` dataclass.
- [ ] `src/wikilens/judge.py` — `Judge` protocol + `MockJudge`, `ClaudeJudge`, `OllamaJudge` impls.
- [ ] `src/wikilens/contradict_format.py` — markdown + JSON formatters (mirror `audit_format.py`).
- [ ] `src/wikilens/cli.py` — wire up `contradict` subcommand.
- [ ] `fixtures/contradictions_vault/` — 8-10 hand-crafted notes.
- [ ] `fixtures/eval/p4_ground_truth.json` — human gold labels.
- [ ] `scripts/eval_p4.py` — runs eval, reports P/R/F1 per class, appends to `BENCHMARK.md`.
- [ ] `tests/test_contradict.py` — pair gen, filter, mock judge end-to-end.
- [ ] `tests/test_judge.py` — judge interface contract, JSON parsing, error paths.
- [ ] `docs/p4-decisions.md` — log actual choices (may diverge from SDD — honest).
- [ ] `README.md` — contradict usage section, API key setup.
- [ ] `.env.example` — `ANTHROPIC_API_KEY=your-key-here` (commented).
- [ ] `pyproject.toml` — add `anthropic>=0.40` to optional `[judge]` extra.
- [ ] `BENCHMARK.md` — P4 section appended.
- [ ] `gotchas.md` — G5+ entries from anything that bites during P4.
- [ ] Tag release `v0.4.0` (after HITL push approval).

## CLI surface

```
wikilens contradict <vault>
    [--db PATH]                          # LanceDB path (default: .wikilens/db)
    [--judge {none,claude,ollama}]       # default: claude
    [--model NAME]                       # default: claude-sonnet-4-6
    [--top-k K]                          # retrieval neighbors per chunk, default 10
    [--min-score FLOAT]                  # filter judge scores below, default 0.5
    [--only {factual,temporal}]          # class filter
    [--sample N]                         # cap judge calls to first N pairs
    [--json]                             # JSON output, schema_version: 1
    [-v | --verbose]                     # progress bars, per-pair verdicts
```

**Exit codes** (mirror P3):
- `0` — no contradictions found (or dry-run completed).
- `1` — contradictions found above `--min-score`.
- `2` — bad input (missing vault, missing API key with `--judge claude`, malformed JSON response).

**Default output** (markdown):

```markdown
# Contradiction report — fixtures/contradictions_vault

Scanned 32 chunks, 85 candidate pairs, 40 judged, 3 contradictions found.

## factual (2)

### Paris vs Berlin (score 0.97)

- **A:** `capitals/paris.md#L3` — "Paris is the capital of France."
- **B:** `capitals/berlin.md#L3` — "Berlin is the capital of France."
- **Judge:** These statements directly contradict — France has one capital.

...
```

**JSON output** (`--json`):

```json
{
  "schema_version": 1,
  "vault": "fixtures/contradictions_vault",
  "stats": {"chunks": 32, "candidates": 85, "judged": 40, "findings": 3},
  "findings": [
    {
      "type": "factual",
      "score": 0.97,
      "chunk_a": {"id": "...", "path": "capitals/paris.md", "line": 3, "text": "..."},
      "chunk_b": {"id": "...", "path": "capitals/berlin.md", "line": 3, "text": "..."},
      "reasoning": "..."
    }
  ]
}
```

## Breakdown into atomic actions (15-min rule)

Ordered for the PIV loop. Each step has a single dominant risk and a validation check. Phase 4.1 is intentionally model-free so we can validate plumbing without burning tokens.

### Phase 4.1 — Skeleton & Plumbing (no real LLM)

1. **Add `anthropic` to `[judge]` extra in `pyproject.toml`; update `.env.example`.** Validate: `pip install -e '.[judge]'` succeeds; `anthropic` importable.
2. **Define `Judge` protocol + `JudgeVerdict` dataclass in `src/wikilens/judge.py`.** Validate: module imports; unit test instantiates and round-trips a verdict.
3. **Implement `MockJudge` returning a hardcoded verdict sequence.** Validate: test calls it 5×, gets deterministic outputs.
4. **Define `CandidatePair` dataclass and `generate_candidate_pairs(vault, k)` in `src/wikilens/contradict.py`** — reuses P2 hybrid. Validate: unit test on 4-chunk mini vault returns the right set.
5. **Implement filters: same-note dedup, canonical ordering, cosine > 0.95 drop.** Validate: unit test hits all three filter paths.
6. **Wire `wikilens contradict` CLI subcommand** using `MockJudge` as default when `--judge none` is passed. Validate: `wikilens contradict fixtures/contradictions_vault --judge none` prints the full pipeline output; exit code correct.
7. **Implement `contradict_format.py`** markdown + JSON. Validate: snapshot test against a fixed input.

### Phase 4.2 — The Cognitive Kernel

8. **Implement `ClaudeJudge`** — Anthropic SDK, JSON mode, retries via SDK defaults, reads `ANTHROPIC_API_KEY` from env. Validate: mock the SDK client; unit test verifies prompt structure + JSON parse + error paths (missing key, malformed JSON).
9. **Hand-tune judge prompt** on ~5 synthetic pairs. Validate: on a factual pair ("Paris is capital" / "Berlin is capital"), returns `{verdict: true, type: "factual", score: >0.9}`.
10. **Implement `OllamaJudge`** (optional, behind `--judge ollama`). Validate: if Ollama running locally, pair judgment returns valid JSON; otherwise skip test.

### Phase 4.3 — Eval Fixture (human-gold labels)

11. **Hand-craft `fixtures/contradictions_vault/`** — 8-10 notes, deliberate structure per D5. Validate: `wikilens ingest` succeeds, 30+ chunks produced.
12. **Hand-label `fixtures/eval/p4_ground_truth.json`** — ~40 pairs. Validate: every labeled `pair_id` resolves to real chunk IDs from the ingest output.

### Phase 4.4 — Eval Harness + Benchmark

13. **`scripts/eval_p4.py`** — load gold labels, run pair gen + judge, compute P/R/F1 per class, append to `BENCHMARK.md`. Validate: running with `--judge none` (mock) reports reproducible numbers; `--judge claude` hits the ≥0.75 F1 target.
14. **Performance pass** — p95 wall-clock with `--judge claude` < 2 min on contradictions vault; `--judge none` < 3 s. Validate: measured numbers in `BENCHMARK.md`.

### Phase 4.5 — Ship

15. **Docs + release** — `docs/p4-decisions.md`, README update, `BENCHMARK.md`, `gotchas.md` updates, version bump, tag `v0.4.0`. Validate: fresh-clone smoke (`pip install -e '.[dev,judge]'` + CLI + eval) works end-to-end.

Every step ends with `pytest -q` green and `python scripts/check_sanitization.py` on staged diff before commit.

## Risks & mitigation

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Judge disagrees with gold labels too often (F1 < 0.75) | Med | High | Iterate prompt; try few-shot; fall back to Opus for judge as escape hatch |
| Retrieval-based pair gen misses planted contradictions | Med | High | Inspect recall of candidate stage separately; add topic-clustered fallback if < 0.90 |
| Anthropic API rate limit / outage during eval | Low | Med | SDK default retries; `--sample` to bound blast radius; document the `OllamaJudge` fallback |
| Judge returns malformed JSON | Med | Low | SDK JSON mode + schema validation; one retry with stricter instructions; then count as abstention |
| Cost blowup on large vaults | Low | Med | Retrieval-based keeps it O(n·k); `--sample` cap; `--min-score` thresholding |
| API key leaks into committed files | Low | Very high | `.env` in `.gitignore`; sanitization gate greps for `sk-ant-` prefix; never log the key |
| Hand-labeled gold set is too small / biased | Med | Med | Document sample size honestly; plan P4.5 expansion if single-judge F1 unstable |
| Ollama fallback not actually tested end-to-end | High | Low | Mark Ollama support as "experimental" in docs; exclude from the release gate |
| Sanitization breach in contradictions vault (real personal data leaks in) | Low | Very high | All fixture content is synthetic, public-domain (capitals, science, cooking); sanitization gate runs pre-commit |

## Gotcha log (P4 working notes)

Empty at SDD time. Will populate during execution. Anything that bites → `gotchas.md` at repo root (G5+).

## Handoff from P3

- Repo: tip of `main` at `a5cb3a3`, tag `v0.3.0` pushed to origin.
- 115 tests green.
- P2 retrieval (`src/wikilens/query.py`) + P2 ingest (`src/wikilens/ingest.py`) are the foundation P4 builds on — no changes required to either.
- `src/wikilens/pipeline.py` `extract_links` stays untouched; P4 doesn't need the link graph.
- Models cached: `BAAI/bge-small-en-v1.5`, `BAAI/bge-reranker-base`.
- `ANTHROPIC_API_KEY` — not yet provisioned. User will set it before Phase 4.2.

## What we learn in P4

- Building an **LLM-as-judge** pipeline with gold-label validation (the research-grade eval pattern).
- Pairwise reasoning tasks and prompt engineering for structured JSON output.
- Cost-aware agentic development: dry-run + sample caps + mock judges as first-class design primitives.
- When "retrieval for agents" (using P2 to find candidates to reason over) is the right pattern vs. brute-force enumeration.
- Honest measurement of judge agreement — precondition for every future LLM-backed agent in P5+.

## Open questions the user must resolve before Phase 4.2

- **Anthropic API key provisioning.** User will export `ANTHROPIC_API_KEY` in their shell before running `--judge claude`. Not needed for Phase 4.1.
- **Judge model pinning.** Default `claude-sonnet-4-6`; confirm at Phase 4.2 kickoff whether to pin the exact alias or leave it model-router-friendly.
- **Label count.** Proposed ~40 pairs; user may want 60-80 if the single-judge F1 is noisy. Revisit after first eval run.
