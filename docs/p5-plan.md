# P5 — Gap Generator (SDD)

**Status:** Specification — awaiting HITL approval before any implementation.
**Created:** 2026-04-30
**Preceded by:** P4 (contradiction finder) — complete, tag `v0.4.0`
**Target effort:** ~20h, part-time

---

## Goal

`wikilens gap <vault>` surfaces **unanswered questions implied by the vault's own content** — topics the notes bring up but never resolve. Each finding includes a rationale, supporting chunks, and a suggested note stub (kebab-case title) the user can create in one step. Ships with a hand-labeled eval that measures agreement between proposed gaps and human-planted gold gaps via a pinned LLM-as-matcher rubric.

This is the first phase that introduces:

- **Cluster-driven reasoning** — k-means on P2 embeddings groups chunks before the LLM sees them.
- **Generative output** — the agent produces new text (gap statements + stubs), not just judgments over existing text.
- **LLM-as-matcher eval** — because two differently-worded gap strings can describe the same missing concept, gold/proposal matching itself requires an LLM. Rubric is pinned to keep the metric traceable.

## Pass/Fail criterion

`wikilens gap fixtures/gaps_vault --judge claude`:

1. **Overall F1 ≥ 0.60** on 10–12 planted gaps in `fixtures/gaps_vault/` against `ClaudeMatcher` (Sonnet 4.6) with rubric threshold ≥ 4/5.
2. **Cluster-stage recall ≥ 0.80** — ≥ 80% of gold gaps are produced as candidates by *some* cluster before matching. Separates clustering quality from matcher quality.
3. **End-to-end wall clock < 3 minutes** on the gaps vault with `--judge claude` (expected ~10–20 clusters × ~3s generation + matcher eval). `--judge none` (dry-run, clustering + empty LLM) < 5s.
4. **Budgeted autonomy enforced:** `--max-clusters`, `--min-cluster-size`, `--sample` respected; verified via unit test.
5. **100% of existing tests (153) still green; new tests green.**

No "vibes" pass — numbers or it didn't ship. Pass bar of 0.60 is deliberately lower than P3/P4 because generative gap-finding is a harder, noisier task than judgment; documented in `docs/p5-decisions.md`.

## Scope

### In

- K-means clustering of P2 chunk embeddings (`k = round(√n_chunks)` default, configurable).
- Per-cluster gap generation via `ClaudeGenerator` (Sonnet 4.6) with structured JSON output.
- Pluggable generator interface: `none` (mock, returns fixed stubs for plumbing validation), `claude` (default).
- Pluggable matcher interface: `none` (substring fallback for dry-runs), `claude` (pinned 1–5 rubric, threshold ≥ 4).
- `wikilens gap <vault>` CLI subcommand — markdown default, `--json`, `--max-clusters N`, `--min-cluster-size N`, `--sample N`, `--judge {none,claude}`, `--seed N` for deterministic k-means, `--top-gaps-per-cluster K`.
- Exit code gate: 0 clean (no gaps found) / 1 findings / 2 bad input (mirror P3/P4).
- Hand-crafted `fixtures/gaps_vault/` — 10–15 notes, 10–12 deliberately planted gaps.
- `fixtures/eval/p5_ground_truth.json` — human gold gaps + supporting cluster hints.
- `scripts/eval_p5.py` — runs eval, reports cluster-stage recall + matcher-stage P/R/F1, appends to `BENCHMARK.md`.
- Matcher debug log: borderline decisions (rubric score 3 or 4) dumped to `docs/p5-matcher-notes.md` for human review each eval run.
- Unit tests for clustering, generator, matcher, CLI wiring.
- Documentation: `docs/p5-decisions.md`, README update, `BENCHMARK.md` section.
- Sanitize + commit gate enforced per phase.

### Out (deferred)

- **Subtopic-coverage gaps** (reference-model-based: "vault has light reactions but no dark reactions"). Requires an external domain taxonomy; revisit in P5.5 after questions-first lands.
- Multi-generator ensembling / self-consistency decoding.
- Graph-community clustering (P3 wikilink communities) as an alternative cluster source.
- Auto-creation of the suggested note stubs (report-only, like P3/P4).
- Caching of generator outputs across runs.
- Incremental gap-finding (rebuild per run).
- Evaluating the matcher itself against human rubric applications (meta-eval).
- LLM-based auto-update of the matcher rubric (explicit non-goal — rubric is human-updated).
- OllamaGenerator / OllamaMatcher (interface compatible, implementation deferred).

## Design decisions

### D1. Gap definition — **unanswered questions only, v0** (approved)

| Option | Pros | Cons |
|---|---|---|
| **Unanswered questions** ✅ | Concrete target; LLM-natural; groundable without external taxonomy | Misses "whole missing subtopic" gaps |
| Subtopic gaps | Richer ("you have X but no Y") | Needs reference model of domain; eval harder |
| Both | Richest output | Conflates two eval metrics; slippery pass/fail |

**Pick:** questions-only for v0. Subtopic gaps deferred to P5.5 once the eval harness is proven.

### D2. Cluster strategy — **k-means on BGE embeddings** (approved)

Algorithm:

1. Load all chunk embeddings from the existing LanceDB store (reuse P2's full-scan pattern — G5 applies: `table.to_arrow().to_pylist()`).
2. Run `sklearn.cluster.KMeans(n_clusters=k, random_state=seed, n_init=10)`. Default `k = round(√n_chunks)`; configurable via `--k`.
3. Drop clusters with fewer than `--min-cluster-size` chunks (default 3) as noise.
4. Sort clusters by size descending; cap at `--max-clusters` (default 30).
5. Per surviving cluster, concatenate chunk texts with `[chunk_id] ...` prefixes as generator input.

**Rejected:**

- **Query-driven retrieval:** needs a seed question, but gap generation *has no seed* — we're asking the vault what to ask.
- **Graph communities:** viable only on densely-linked vaults; fails on new vaults with sparse wikilinks.

**New dep:** `scikit-learn>=1.4` in the `[judge]` extra (same extra gates all LLM-adjacent code). ~25MB install cost; standard everywhere. If this becomes an objection, mini-batch k-means is ~40 lines of numpy and we can drop the dep.

### D3. LLM — **Claude Sonnet 4.6**, same as P4 (approved)

Reuses the P4 SDK setup (`ANTHROPIC_API_KEY`, `python-dotenv`, retry loop). Two call sites:

- **`ClaudeGenerator`:** given a cluster's chunks, return up to `--top-gaps-per-cluster` (default 3) gap records. Structured JSON output, same parse/retry path as `ClaudeJudge`.
- **`ClaudeMatcher`:** given a gold gap string and a proposed gap string, return a 1–5 rubric score + one-line rationale. Used **only** in `scripts/eval_p5.py`, never in the production CLI.

Keeps the cognitive layer homogeneous — same model, same cost tier, same SDK path.

### D4. Output shape — **finding + note stub, per gap** (approved)

Per finding record:

```json
{
  "cluster_id": 7,
  "gap_question": "What is the Calvin cycle and how does it relate to the light reactions?",
  "suggested_note_title": "calvin-cycle",
  "rationale": "Three cluster notes describe the light reactions and chlorophyll absorption, but none explain what the resulting NADPH and ATP are used for.",
  "supporting_chunks": ["abc123", "def456", "ghi789"],
  "cluster_size": 5
}
```

`suggested_note_title` is kebab-case, no extension, matches Obsidian's default file-naming. No score field at the finding level — the eval layer scores, the CLI reports.

**Rejected:** score-per-gap at generation time. Would require either (a) a self-rated score from the generator (noisy, self-serving) or (b) a second judge call per gap (doubles cost). The matcher rubric in the eval harness gives us the score we actually care about.

### D5. Eval methodology — **hand-crafted vault + pinned 1–5 matcher rubric** (approved w/ refinements)

- **Hand-label once** (~10–12 gaps in `fixtures/gaps_vault/`). Each gold gap includes the chunk IDs that *imply* it exists.
- **Matcher rubric — pinned** (non-negotiable for reproducibility):

  | Score | Meaning |
  |---|---|
  | 5 | Proposed and gold describe the **same missing concept** with equivalent semantics. |
  | 4 | Same missing concept, different wording / framing. |
  | 3 | Related concept, different scope (broader or narrower). |
  | 2 | Same general topic area, but a different specific question. |
  | 1 | Unrelated. |

  **Match threshold: ≥ 4.** Tightens the eval against rephrasing tolerance without requiring exact-string overlap. Threshold chosen once here; changing it is a breaking eval change (bump `schema_version`).

- **Borderline-decision logging:** every matcher call with score 3 or 4 writes `{gold, proposal, score, rationale}` to `docs/p5-matcher-notes.md`. This is the **meta-reasoning surface** — after an eval run, the user reviews borderline decisions and decides (a) rubric stays, (b) rubric needs a refinement, or (c) a gold label was wrong. No auto-rewriting of the rubric.

- **Metrics reported:**
  - **Cluster-stage recall:** did the pipeline produce at least one proposal (pre-match) that a human would accept for this gold gap? Measured with the same matcher, but pools all proposals across all clusters.
  - **Matcher-stage P/R/F1:** standard retrieval metrics on the matched set.
  - Both reported — separating clustering failures from generation failures is how we know where to push next.

**Label schema** (`fixtures/eval/p5_ground_truth.json`):

```json
{
  "schema_version": 1,
  "matcher_threshold": 4,
  "gaps": [
    {
      "gap_id": "calvin-cycle",
      "gold_question": "What is the Calvin cycle and how does it use ATP/NADPH from the light reactions?",
      "supporting_chunks": ["abc123", "def456"],
      "notes": "planted by omitting dark-reactions note from photosynthesis cluster"
    }
  ]
}
```

### D6. Budgeted autonomy — **hard caps on cluster and call volume** (new, approved)

Three caps layer defensively:

- `--min-cluster-size` (default 3) drops micro-clusters before any LLM call.
- `--max-clusters` (default 30) caps total generator calls regardless of vault size.
- `--sample N` (mirror P4) caps total LLM calls in matcher eval.

On a 5k-chunk vault, default caps yield ≤ 30 generator calls + ≤ N matcher calls ≈ < $0.20 / eval run at Sonnet pricing. Documented in the CLI help and README.

## Deliverables checklist

- [ ] `src/wikilens/gap.py` — cluster + `GapFinding` dataclass + `generate_gaps(vault, generator, opts)` pipeline.
- [ ] `src/wikilens/generator.py` — `Generator` protocol + `MockGenerator`, `ClaudeGenerator` impls.
- [ ] `src/wikilens/matcher.py` — `Matcher` protocol + `SubstringMatcher` (dry-run), `ClaudeMatcher` (pinned 1–5 rubric).
- [ ] `src/wikilens/gap_format.py` — markdown + JSON formatters (mirror `audit_format.py` / `contradict_format.py`).
- [ ] `src/wikilens/cli.py` — wire up `gap` subcommand.
- [ ] `fixtures/gaps_vault/` — 10–15 hand-crafted notes with deliberate omissions.
- [ ] `fixtures/eval/p5_ground_truth.json` — 10–12 gold gaps with supporting-chunk hints.
- [ ] `scripts/eval_p5.py` — runs eval, reports cluster-stage recall + matcher P/R/F1, appends to `BENCHMARK.md`, writes borderline-decision log.
- [ ] `docs/p5-matcher-notes.md` — borderline-decision log (gitignored? decide at Phase 5.4).
- [ ] `tests/test_gap.py` — clustering, pipeline, mock generator end-to-end.
- [ ] `tests/test_generator.py` — generator contract, JSON parse, error paths.
- [ ] `tests/test_matcher.py` — matcher contract, rubric thresholding, substring fallback.
- [ ] `docs/p5-decisions.md` — log actual choices (may diverge from SDD — honest).
- [ ] `README.md` — gap usage section.
- [ ] `pyproject.toml` — add `scikit-learn>=1.4` to `[judge]` extra.
- [ ] `BENCHMARK.md` — P5 section appended.
- [ ] `gotchas.md` — G6+ entries from anything that bites.
- [ ] Tag release `v0.5.0` (after HITL push approval).

## CLI surface

```
wikilens gap <vault>
    [--db PATH]                          # LanceDB path (default: .wikilens/db)
    [--judge {none,claude}]              # default: claude
    [--model NAME]                       # default: claude-sonnet-4-6
    [--k N]                              # k-means cluster count (default: round(sqrt(n_chunks)))
    [--min-cluster-size N]               # drop clusters with fewer than N chunks (default: 3)
    [--max-clusters N]                   # cap clusters processed (default: 30)
    [--top-gaps-per-cluster K]           # max gaps generated per cluster (default: 3)
    [--sample N]                         # cap generator calls (smoke mode)
    [--seed N]                           # k-means random_state (default: 42)
    [--json]                             # JSON output, schema_version: 1
    [-v | --verbose]                     # progress bars, per-cluster output
```

**Exit codes** (mirror P3/P4):
- `0` — no gaps found (or dry-run completed).
- `1` — gaps found.
- `2` — bad input (missing vault, missing API key with `--judge claude`, malformed generator response).

**Default output** (markdown):

```markdown
# Gap report — fixtures/gaps_vault

Clustered 47 chunks into 8 clusters (dropped 3 below min-size). Generated 18 gap candidates.

## Cluster 3 — photosynthesis (5 chunks)

### What is the Calvin cycle?

- **Rationale:** Three notes describe the light reactions and chlorophyll absorption, but none explain what the resulting NADPH and ATP are used for.
- **Supporting chunks:** `photosynthesis.md#L8`, `chlorophyll.md#L3`, `leaf-anatomy.md#L15`
- **Suggested note:** `calvin-cycle`

...
```

## Breakdown into atomic actions (15-min rule)

Ordered for the PIV loop. Each step has a single dominant risk and a validation check. Phase 5.1 is intentionally model-free so plumbing is validated without tokens.

### Phase 5.1 — Skeleton & Plumbing (no real LLM)

1. **Add `scikit-learn>=1.4` to `[judge]` extra; update `.env.example` if needed.** Validate: `pip install -e '.[judge]'` succeeds; `sklearn.cluster.KMeans` importable.
2. **Define `Generator` protocol + `GapCandidate` / `GapFinding` dataclasses in `src/wikilens/generator.py`.** Validate: module imports; unit test instantiates and round-trips a finding.
3. **Implement `MockGenerator` returning a hardcoded gap sequence.** Validate: test calls it on 3 clusters, gets deterministic outputs.
4. **Define `Matcher` protocol + `SubstringMatcher` in `src/wikilens/matcher.py`.** Validate: unit test on exact / partial / non-match pairs.
5. **Implement `cluster_chunks(embeddings, k, seed, min_size)` in `src/wikilens/gap.py`.** Validate: unit test on 20 synthetic 2D vectors (3 Gaussian blobs) produces 3 clusters with correct members.
6. **Implement `generate_gaps(vault, generator, opts)` pipeline — full-table scan → cluster → per-cluster generate → collect.** Validate: unit test with `MockGenerator` on 4-chunk mini vault returns expected findings.
7. **Wire `wikilens gap` CLI subcommand** using `MockGenerator` when `--judge none`. Validate: `wikilens gap fixtures/gaps_vault --judge none` prints full pipeline output; exit code correct.
8. **Implement `gap_format.py`** markdown + JSON. Validate: snapshot test against a fixed input.

### Phase 5.2 — The Cognitive Kernel

9. **Implement `ClaudeGenerator`** — Anthropic SDK, JSON mode, retries via SDK defaults. Validate: mock the SDK client; unit test verifies prompt structure, JSON parse, error paths (missing key, malformed JSON).
10. **Hand-tune generator prompt** on 2 synthetic clusters. Validate: on a photosynthesis cluster with Calvin cycle missing, returns a gap question naming the Calvin cycle (or a synonym) in top-3.
11. **Implement `ClaudeMatcher`** — pinned 1–5 rubric prompt, threshold-agnostic output (returns raw score + rationale, caller applies threshold). Validate: unit test with mocked SDK on 4 synthetic (gold, proposal) pairs hitting each rubric level.

### Phase 5.3 — Eval Fixture (human-gold gaps)

12. **Hand-craft `fixtures/gaps_vault/`** — 10–15 notes, deliberate omissions per clusters. Validate: `wikilens ingest` succeeds, 30+ chunks produced across ≥ 3 topic clusters.
13. **Hand-label `fixtures/eval/p5_ground_truth.json`** — 10–12 gold gaps, each tied to supporting chunk IDs from the ingest output. Validate: every `supporting_chunks` entry resolves to a real chunk.

### Phase 5.4 — Eval Harness + Benchmark

14. **`scripts/eval_p5.py`** — load gold labels, run pipeline + matcher, compute cluster-stage recall + matcher P/R/F1, append to `BENCHMARK.md`, write borderline-decision log to `docs/p5-matcher-notes.md`. Validate: running with `--judge none` (mock) reports reproducible numbers; `--judge claude` hits the ≥ 0.60 F1 target.
15. **Performance pass** — wall clock < 3 min on gaps vault with `--judge claude`; < 5s with `--judge none`. Validate: measured numbers in `BENCHMARK.md`.
16. **Meta-reasoning review** — manually read `docs/p5-matcher-notes.md` borderline decisions; decide whether rubric needs a refinement or any gold label is wrong. Validate: reviewed list pasted into `docs/p5-decisions.md` with outcomes.

### Phase 5.5 — Ship

17. **Docs + release** — `docs/p5-decisions.md`, README update, `BENCHMARK.md`, `gotchas.md` updates (if any), version bump, tag `v0.5.0`. Validate: fresh-clone smoke (`pip install -e '.[dev,judge]'` + CLI + eval) works end-to-end.

Every step ends with `pytest -q` green and `python scripts/check_sanitization.py` on staged diff before commit.

## Risks & mitigation

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Matcher rubric is too lenient → F1 inflates | Med | High | Borderline-decision log; manually review every eval run; tighten rubric if score-4 rate > 30% of matches |
| Matcher rubric is too strict → F1 tanks on valid paraphrases | Med | High | Same mitigation — review log; if gold/proposal pair obviously matches and scores 3, the rubric is the bug |
| K-means clusters are incoherent (mixed topics) | High | Med | Expected — LLM is robust to noisy clusters; monitor cluster-stage recall; if < 0.8, try `k = 2 * sqrt(n)` before escalating |
| Generator hallucinates gaps that the vault *does* answer (FP) | Med | Med | Include supporting-chunk quotes in prompt; matcher catches FPs structurally |
| Cost blowup on large vaults | Low | Med | `--max-clusters`, `--min-cluster-size`, `--sample` all cap; default 30 clusters ≈ $0.10/run |
| F1 < 0.60 on first eval run | Med | High | Iterate prompt; try `k = 2*sqrt(n)`; accept honest low score + writeup as P3's "organic-link smoke" fallback |
| Generator returns malformed JSON | Med | Low | SDK JSON mode + schema validation; retry once with stricter instructions; count as abstention |
| scikit-learn install flakes on Windows | Low | Low | Widely available; wheels on all platforms. Fallback: drop dep, implement mini-batch k-means inline (~40 LOC numpy) |
| Sanitization breach in gaps vault | Low | Very high | All fixture content synthetic / public-domain; sanitization gate runs pre-commit |
| API key leaks | Low | Very high | Existing gate (`.env` gitignored, `sk-ant-` in sanitization scan) |

## Gotcha log (P5 working notes)

Empty at SDD time. Will populate during execution. Anything that bites → `gotchas.md` at repo root (G6+).

## Handoff from P4

- Repo: tip of `main` at `25e7d16`, tag `v0.4.0` pushed to origin.
- 153 tests green.
- P2 retrieval + ingest untouched; reused via full-table scan (G5 pattern: `table.to_arrow().to_pylist()`).
- P4 `ClaudeJudge` SDK setup, retry loop, and `.env` loading pattern are the templates for `ClaudeGenerator` / `ClaudeMatcher`.
- `ANTHROPIC_API_KEY` already provisioned from P4.
- Models cached: `BAAI/bge-small-en-v1.5`, `BAAI/bge-reranker-base` — no new model downloads needed.

## What we learn in P5

- Building a **cluster-driven generative agent** — first phase where the vault's own geometry (embedding space) drives what the LLM reasons about.
- Eval design under fuzzy matching — pinning a rubric is the honest way to make an LLM-judged metric reproducible; borderline-decision logging is the honest way to make it falsifiable.
- **FinOps discipline** — layered caps (`--min-cluster-size`, `--max-clusters`, `--sample`) as first-class design primitives, not afterthoughts.
- The shape of generative agent output — findings + rationale + supporting chunks + suggested atomic action is a reusable pattern for P6+.
- Honest acknowledgment that F1 ≥ 0.60 is the P5 bar — generative tasks have a lower reproducibility ceiling than P3/P4 judgment tasks, and pretending otherwise is the first step toward eval theater.

## Open questions the user must resolve before Phase 5.2

- **`scikit-learn` as a new dep.** Confirm or veto. If vetoed, Phase 5.1 implements mini-batch k-means in numpy (~40 LOC); everything else unchanged.
- **Borderline-decision log location.** Tracked in `docs/p5-matcher-notes.md` (visible in git history, part of the research output), or gitignored working notes? Default: tracked — it's part of honest eval methodology.
- **Pass bar.** Proposed F1 ≥ 0.60; confirm or tighten. Set before eval runs to avoid post-hoc bar-moving.
- **`fixtures/gaps_vault/` topics.** Propose: photosynthesis cluster (Calvin cycle omitted), Python web frameworks cluster (async comparison omitted), history cluster (specific treaty omitted), cooking cluster (specific technique omitted). Public-domain, domain-distant from the user's day job. Confirm topics before hand-crafting.
