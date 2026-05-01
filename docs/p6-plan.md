# P6 — Answer Generator (SDD)

**Status:** Specification — awaiting HITL approval before any implementation.
**Created:** 2026-05-01
**Preceded by:** P5 (gap generator) — complete, tag `v0.5.0`
**Target effort:** ~15–20h, part-time

---

## Goal

`wikilens answer <vault> --gaps gaps.json` closes the gap loop: for each gap that `wikilens gap` surfaced, retrieve supporting chunks from the existing index and draft a **note stub** that:

1. synthesizes what the vault already says on the topic, with inline citations,
2. explicitly calls out what the vault does *not* cover (the residual evidence gaps),
3. lists `[[wikilinks]]` to the parent notes of the supporting chunks, and
4. carries provenance frontmatter (`source_gap_id`, `source_cluster_id`, `generator`, etc.) so a future pass can regenerate, audit, or remove the stub deterministically.

By default the stub is **printed to stdout**. With `--write --out <dir>` the CLI materializes one `.md` file per gap. Writing is always explicit — a `--write` flag is the irreversibility gate.

This is the first phase that introduces:

- **Consumption of another agent's output** (`gap --json`) as its canonical input.
- **Generation of content that could land in the user's vault** — higher blast radius than P3–P5 (analysis/proposal only).
- **Multi-axis LLM-judge eval** — faithfulness, coverage, attribution quality, stub structure. Four dimensions instead of P5's single rubric.
- **Automated attribution check** — every factual sentence in a draft must cite a `chunk_id` that was in the retrieved-context set.

## Pass/Fail criterion

`wikilens answer fixtures/gaps_vault --gaps <p5-output.json> --judge openai`:

1. **Faithfulness ≥ 0.80** — per-sentence LLM judge: at least 80% of cited sentences are actually supported by the chunk they cite. This is the hallucination guard.
2. **Coverage ≥ 0.60** — per-gap LLM judge: drafts cover at least 60% of the hand-written gold sketch's key claims. Measures "did it actually answer the question."
3. **Attribution ≥ 0.90** — automated parser: ≥ 90% of declarative sentences in the "What the vault says" section carry a `[^N]` footnote that resolves to a retrieved `chunk_id`. No LLM in this metric.
4. **Skip-correctness** — when `--min-supporting N` skips a gap (or emits an "external-research" stub), the skip reason is logged and the gap is not silently dropped.
5. **End-to-end wall clock < 3 min** on the 10-gap eval with `--judge openai` (≈ 10 draft calls + 10 retrieval calls + faithfulness/coverage judging). `--judge none` (mock, skipping LLM) < 5s.
6. **Budgeted autonomy enforced:** `--sample`, `--min-supporting` respected; verified via unit test.
7. **100% of existing tests (224) still green; new tests green.**

No "vibes" pass — numbers or it didn't ship. Bars chosen before eval runs to avoid post-hoc bar-moving. Faithfulness is the hardest bar because one unfaithful sentence is worse than a missing paragraph — hallucinated content in a user's vault is the nightmare failure mode for this agent.

## Scope

### In

- New CLI subcommand `wikilens answer <vault>`:
  - `--gaps PATH` (required) — path to a `gap --json` file (schema_version: 1).
  - `--db PATH` — LanceDB path (default: `.wikilens/db`).
  - `--judge {none,openai,claude}` — drafter backend (default: `openai`, per project standard).
  - `--model NAME` — drafter model (default: `gpt-4o`).
  - `--top-k N` — retrieval neighbors per gap question (default: 8).
  - `--retrieval-mode {dense,bm25,hybrid,rerank}` — default `rerank` (best quality; P2's `rerank` Hit@5 = 1.00).
  - `--min-supporting N` — skip gap if retrieved chunks (post-filter) < N; default 2.
  - `--sample N` — cap total drafts produced (smoke mode).
  - `--write` — actually write stubs to disk (without this, print to stdout only).
  - `--out DIR` — output directory for `--write`. Required if `--write` set.
  - `--json` — emit structured JSON report instead of rendered stubs.
- Pluggable drafter interface: `MockDrafter` (deterministic, for plumbing), `OpenAIDrafter` (default), `ClaudeDrafter` (alt).
- Per-gap retrieval using P2's `query()` in `rerank` mode (or configurable).
- Stub output shape (see §D4 below): frontmatter + `What the vault says` + `Evidence gaps` + `Related notes` + `Citations`.
- "External research" stub mode when retrieval yields < `--min-supporting` chunks (see §D4, §Q4-resolution).
- Attribution check in `src/wikilens/answer.py::check_attribution()` — parses footnotes, verifies every `[^N]` resolves to a retrieved `chunk_id`.
- `fixtures/eval/p6_answer_sketches.json` — hand-written gold answer sketches for the 10 existing `fixtures/gaps_vault/` gold gaps (key claims list + required-chunks hint per gap).
- `scripts/eval_p6.py` — runs end-to-end eval: P5 gaps in → P6 drafts out → judges faithfulness/coverage → reports attribution/skip metrics → appends to `BENCHMARK.md`.
- Borderline-decision log: drafts that score 3 on any judge dimension written to `docs/p6-judge-notes.md` for human review (same meta-reasoning pattern as P5).
- Unit tests for drafter, attribution parser, answer pipeline, CLI wiring, mock end-to-end.
- Documentation: `docs/p6-decisions.md`, README update, `BENCHMARK.md` section.
- Sanitize + commit gate enforced per phase.

### Out (deferred)

- **Iterative refinement** (`--iterate`: user feedback → regenerate). Per Q5, single-shot for v0.6.0. Revisit in P6.5.
- **Actually committing stubs to the user's vault** — `--write --out <dir>` goes to a user-chosen directory. Integration with Obsidian's file system, collision handling beyond "refuse to overwrite," and wikilink backfilling (updating the target notes' inbound links) all deferred.
- **Multi-draft sampling / self-consistency** — one draft per gap. Temperature=0, seed fixed. Multi-sample is a P6.5 experiment if faithfulness needs boosting.
- **Cross-gap deduplication** — if two gaps produce semantically similar drafts, both are emitted. Dedup via embedding similarity is a P6.5 feature.
- **OllamaDrafter** — interface compatible, implementation deferred (same status as OllamaGenerator / OllamaJudge).
- **Fine-grained cost control beyond `--sample`** — per-draft token caps, streaming, etc.
- **Auto-fixing attribution** — if the model drops a citation, we flag it; we do not auto-patch.
- **Feedback into the gap generator** — P6 does not inform P5. The loop is one-way for v0.6.0.
- **Meta-eval of the judge itself** (does the faithfulness judge agree with humans?).
- **Subtopic-coverage answers** — P5 explicitly deferred subtopic gaps; P6 inherits that deferral.

## Design decisions

### D1. Input source — **consume `gap --json` file** (approved)

`wikilens answer <vault> --gaps gaps.json` — the CLI reads the exact JSON `wikilens gap --json` produced. Separation of concerns: P5 analyzes, P6 produces. Reproducible (same gaps → same drafts with fixed seed). Avoids re-paying clustering + generator cost on every answer run.

Validation: schema version must match. Unknown `schema_version` → exit 2 with a clear error. `gaps.json` without `findings[]` → exit 2.

**Rejected:**
- **Re-running the gap pipeline internally.** Doubles the cost and entangles the two phases' eval runs.
- **Both.** Two input modes doubles surface area and tests for marginal benefit.

### D2. Write policy — **print-only by default; `--write --out <dir>`** (approved)

Default: render the stubs (markdown) to stdout. Users pipe / tee / eyeball.

`--write` requires `--out DIR`:
- If `DIR` doesn't exist, create it (idempotent).
- One `.md` file per draft, filename = `suggested_note_title.md`.
- **Refuse to overwrite** an existing file; exit 1 with the list of collisions. No `--force` flag in v0.6.0 — explicit human action required to resolve.
- `--json` output goes to stdout even when `--write` is set (so the write log is machine-readable).

Writing to the user's vault is the first irreversible action the project takes. Gating behind an explicit flag + `--out` + no-overwrite policy matches the "human-accountable gate" pattern.

### D3. Answer source — **hybrid: retrieval-first, explicit "external research" when vault is silent** (approved)

For each gap:

1. Use the gap's `gap_question` as the retrieval query.
2. Call P2's `query(mode=rerank, k=top_k)` against the LanceDB store.
3. **Augment with the gap's `supporting_chunk_ids`** — these were already identified by the gap generator as relevant. Merge the two sets, dedup by chunk_id, keep top-`top_k` by rerank score (or union order if dense).
4. If the resulting chunk count ≥ `--min-supporting`: draft the stub with these chunks as evidence. The drafter prompt is strict: **cite only chunks that appear in the evidence set; every factual sentence must carry a `[^N]` footnote**.
5. If < `--min-supporting`: emit an **"external research" stub** (see §D4) — the "What the vault says" section is replaced with a brief "the vault has no relevant coverage" statement, and the "Evidence gaps" section becomes the primary content (list the question, suggest external sources *without fabricating URLs*).

This avoids the worst failure mode (confident hallucination in the user's vault) while still producing useful output when the vault is genuinely silent.

**Rejected:**
- **Retrieval-only, skip if too sparse.** Loses the signal that P5 found a gap — the stub itself is valuable even when retrieval is weak (it documents what's missing).
- **LLM-only (no retrieval).** Defeats the point. The vault is the ground truth.

### D4. Output shape — **structured stub with 5 sections** (approved)

One stub per gap. Markdown with YAML frontmatter:

```markdown
---
title: calvin-cycle
generated_by: wikilens-answer
generated_at: 2026-05-01T14:30:00Z
source_gap_id: calvin-cycle
source_cluster_id: 3
generator: openai/gpt-4o
retrieval_mode: rerank
top_k: 8
min_supporting: 2
supporting_chunks:
  - photosynthesis.md#L8
  - chlorophyll.md#L3
  - leaf-anatomy.md#L15
evidence_strength: strong   # strong | thin | external-research
---

# Calvin cycle

> **Gap:** What is the Calvin cycle and how does it use ATP/NADPH from the light reactions?

## What the vault says

The vault's photosynthesis notes describe light reactions producing ATP and NADPH in the thylakoid membranes[^1]. Chlorophyll a in PSII absorbs photons at 680nm, driving water splitting[^2]. The notes reference "downstream carbon fixation" but do not describe it[^1].

## Evidence gaps

The vault does not cover:

- The specific enzyme (RuBisCO) that fixes CO₂ in the Calvin cycle.
- The three-phase structure (carboxylation, reduction, regeneration) of the cycle.
- How ATP/NADPH from the light reactions are consumed per CO₂ fixed.

A stub note at `calvin-cycle.md` would close the loop between `photosynthesis.md` and `leaf-anatomy.md`.

## Related notes

- [[photosynthesis]]
- [[chlorophyll]]
- [[leaf-anatomy]]

## Citations

[^1]: `photosynthesis.md#L8` — "Light reactions produce ATP and NADPH in the thylakoid membranes, which are then used in downstream carbon fixation..."
[^2]: `chlorophyll.md#L3` — "Chlorophyll a in photosystem II absorbs photons at approximately 680nm..."
```

**External-research variant** (when retrieval < `--min-supporting`):

```markdown
---
title: spanish-dutch-1648
generated_by: wikilens-answer
generated_at: 2026-05-01T14:30:00Z
source_gap_id: spanish-dutch-1648
evidence_strength: external-research
supporting_chunks: []
---

# Spanish-Dutch treaty of 1648

> **Gap:** What were the specific terms of the Spanish-Dutch settlement (Treaty of Münster, 1648)?

## What the vault says

The vault references the Treaty of Westphalia but does not cover the separate Spanish-Dutch agreement signed the same year. No supporting chunks were retrieved above the `--min-supporting=2` threshold.

## Evidence gaps

This gap cannot be answered from the vault's current content. External sources required.

Suggested next steps:

- Consult primary source: Treaty of Münster text (1648).
- Cross-reference with `european-politics-1618.md` once the Thirty Years' War terms are added.

## Related notes

- [[european-politics-1618]]

## Citations

_No citations — external research required._
```

**Key properties:**

- **Frontmatter is provenance.** A future `wikilens audit --generated` pass could find, regenerate, or remove all `generated_by: wikilens-answer` stubs deterministically.
- **Every factual sentence in "What the vault says" carries `[^N]`.** Enforced by the prompt; verified by the attribution checker. Footnotes include the chunk_id and a snippet.
- **Citations section doubles as proof-carrying actions** — a human reviewer can verify every claim without opening the source note.
- **`evidence_strength`** (strong / thin / external-research) is set by the pipeline based on retrieved-chunk count and judge faithfulness score. `thin` = retrieval met min-supporting but judge flags weak support.

### D5. Eval methodology — **LLM-judge rubric (4 axes) + automated attribution check** (approved)

Two kinds of eval signals, complementary:

**(i) LLM-judge rubric** — `scripts/eval_p6.py` calls a judge (same backend as drafter) per draft across four dimensions, each 1–5, threshold ≥ 4:

| Axis | Meaning |
|---|---|
| **Faithfulness** | Every cited sentence is actually supported by the chunk it cites. Score 5 = no unfaithful sentences; 1 = majority unfaithful. Measured **per sentence**, aggregated to rate per draft. |
| **Coverage** | Draft addresses the gold sketch's key claims. Score 5 = all key claims covered; 1 = none. |
| **Attribution quality** | Citations land on the right evidence (vs. being present but pointing at a loosely-related chunk). Score 5 = every citation is the strongest available evidence; 1 = citations are noise. |
| **Stub structure** | Output conforms to the shape spec (§D4): frontmatter complete, sections in order, wikilinks resolve, no prose outside the expected sections. Score 5 = clean; 1 = ill-formed. |

Threshold ≥ 4 on all four axes = pass for that draft. Headline metric: **pass rate** = (drafts passing all 4) / (drafts attempted).

Borderline log: any score-3 decision on any axis is written to `docs/p6-judge-notes.md` for human review — same meta-reasoning pattern as P5's matcher notes.

**(ii) Automated attribution check** — `src/wikilens/answer.py::check_attribution(draft, retrieved_chunk_ids)`:

1. Parse the "What the vault says" section.
2. Count declarative sentences.
3. Count sentences carrying at least one `[^N]` footnote.
4. Verify every `[^N]` resolves to a footnote in "Citations".
5. Verify every resolved footnote's `chunk_id` is in `retrieved_chunk_ids`.
6. Return `AttributionReport(total_sentences, cited_sentences, orphan_footnotes, invalid_chunk_refs)`.

Headline metric: **attribution rate** = cited_sentences / total_sentences. No LLM, fully reproducible, cheap.

**Why both:** the LLM judge catches semantic faithfulness (does the sentence actually match what the chunk says?); the attribution check catches structural faithfulness (is there even a citation at all?). A draft can pass (ii) and fail (i): well-formed footnotes pointing at real chunks that don't support the sentence.

**Label schema** (`fixtures/eval/p6_answer_sketches.json`):

```json
{
  "schema_version": 1,
  "faithfulness_threshold": 4,
  "coverage_threshold": 4,
  "attribution_threshold": 4,
  "structure_threshold": 4,
  "attribution_rate_threshold": 0.90,
  "sketches": [
    {
      "gap_id": "calvin-cycle",
      "gold_question": "What is the Calvin cycle...",
      "key_claims": [
        "Calvin cycle is the dark-reaction phase of photosynthesis.",
        "RuBisCO fixes CO₂.",
        "Three phases: carboxylation, reduction, regeneration.",
        "Consumes ATP and NADPH produced by the light reactions."
      ],
      "required_chunks": ["photosynthesis.md#L8", "chlorophyll.md#L3"],
      "notes": "Key claims are what any competent stub should cover."
    }
  ]
}
```

**Rejected:**
- **Cosine similarity vs. gold answers.** Penalizes paraphrasing, rewards over-fitting to gold wording. LLM judge handles paraphrase natively.
- **Attribution-only (skip LLM judge).** Cheap but blind to semantic hallucination.
- **Single-axis rubric.** Four dimensions are the minimum to separate "ill-formed" from "unfaithful" from "incomplete."

### D6. Fixture — **reuse `fixtures/gaps_vault/`** (approved)

No new fixture vault. Eval fixture = existing `fixtures/gaps_vault/` + new `fixtures/eval/p6_answer_sketches.json` with key claims for each of the 10 gold gaps from P5.

Pipeline: `scripts/eval_p6.py` ingests gaps_vault (if not already), runs `wikilens gap --json` (or loads a cached JSON from a prior P5 run), feeds it to `wikilens answer`, judges the drafts against the sketches, appends to `BENCHMARK.md`.

**Longitudinal property:** the gap → answer loop can be tested on the same vault, so improvements to either agent are visible end-to-end.

### D7. Backend — **OpenAI / `gpt-4o`** (approved)

Consistent with P4/P5 defaults per the memory entry. `ClaudeDrafter` is wired via `--judge claude` and `--model claude-sonnet-4-6`. Same SDK patterns as `OpenAIGenerator` / `ClaudeGenerator` — `_env.py`, retry loop, structured-output prompt, abstention counter.

**Same model serves as drafter and judge** in `scripts/eval_p6.py`, matching P5's pattern (ClaudeMatcher using the same Sonnet as ClaudeGenerator). Meta-eval of judge-vs-human agreement is deferred.

### D8. Budgeted autonomy — **`--sample` + `--min-supporting`** (approved)

Layered caps:

- `--sample N` (mirrors P4/P5) — cap total drafts attempted. Default: unlimited.
- `--min-supporting N` — skip a gap if retrieved chunks < N. Default: 2.

Both propagate through the pipeline and eval harness. Default `--min-supporting=2` means most "external research" stubs are emitted rather than drafted — which is the safe default per Q3.

Estimated cost on the 10-gap eval at `gpt-4o` pricing: ≤ 10 draft calls × ~1.5k output tokens + ≤ 40 judge calls × ~200 output tokens ≈ < $0.10 per full eval run.

### D9. Exit codes — **0 clean / 1 partial / 2 bad input** (approved)

- `0` — all gaps produced drafts at or above `--min-supporting` evidence threshold. No skips.
- `1` — at least one gap skipped or emitted as external-research. Still a successful run; the exit code surfaces "partial coverage" as a CI-visible signal.
- `2` — bad input (missing `--gaps` file, malformed gaps JSON, schema mismatch, missing API key with `--judge openai/claude`, missing index, `--write` without `--out`, collision with existing file when `--write` set).

### D10. Wikilink integration — **resolve supporting chunks to parent notes, emit `[[basename]]`** (approved)

For each draft:

1. Collect all unique `source_rel` values from the retrieved chunks that were actually cited (appeared in at least one footnote).
2. Strip `.md` extension → wikilink basename.
3. De-dup and sort alphabetically.
4. Emit under "## Related notes" as a bullet list of `[[basename]]`.

Obsidian will resolve these to the existing notes automatically, so the generated stub joins the vault's graph on ingest. If the user runs `wikilens audit` on the vault + stubs together, the new stubs will show as one-way-linked until the parent notes add an outbound link — a useful audit signal, not a bug.

## Deliverables checklist

- [ ] `src/wikilens/drafter.py` — `Drafter` protocol + `MockDrafter`, `OpenAIDrafter`, `ClaudeDrafter` impls.
- [ ] `src/wikilens/answer.py` — pipeline: load gaps, per-gap retrieval, call drafter, attribution check, assemble `AnswerDraft` records.
- [ ] `src/wikilens/answer_format.py` — markdown stub renderer + JSON output + file-writer (one `.md` per draft, no-overwrite policy).
- [ ] `src/wikilens/cli.py` — wire up `answer` subcommand.
- [ ] `fixtures/eval/p6_answer_sketches.json` — 10 gold sketches, one per P5 gold gap.
- [ ] `scripts/eval_p6.py` — runs eval, reports pass-rate + per-axis means + attribution rate + skip rate, appends to `BENCHMARK.md`, writes borderline log to `docs/p6-judge-notes.md`.
- [ ] `tests/test_drafter.py` — drafter contract, JSON parse, prompt shape, retry path.
- [ ] `tests/test_answer.py` — pipeline, retrieval integration, attribution parser, skip logic, external-research stub.
- [ ] `tests/test_answer_format.py` — markdown stub snapshot, JSON schema, file-write no-overwrite policy.
- [ ] `tests/test_cli_answer.py` — CLI end-to-end with MockDrafter, exit codes, `--write` / `--out` validation.
- [ ] `docs/p6-decisions.md` — log actual choices (may diverge from SDD — honest, per P4/P5 precedent).
- [ ] `docs/p6-judge-notes.md` — borderline-decision log (tracked, same as P5's matcher notes).
- [ ] `README.md` — answer usage section.
- [ ] `BENCHMARK.md` — P6 section appended.
- [ ] `HANDOFF.md` + `.local/HANDOFF.md` — bumped on completion.
- [ ] `gotchas.md` — G6+ entries if anything bites.
- [ ] Tag release `v0.6.0` (after HITL push approval).

## CLI surface

```
wikilens answer <vault>
    --gaps PATH                          # required: gap --json output
    [--db PATH]                          # LanceDB path (default: .wikilens/db)
    [--judge {none,openai,claude}]       # drafter backend (default: openai)
    [--model NAME]                       # drafter model (default: gpt-4o)
    [--top-k N]                          # retrieval neighbors per gap (default: 8)
    [--retrieval-mode {dense,bm25,hybrid,rerank}]  # default: rerank
    [--min-supporting N]                 # skip if retrieved < N (default: 2)
    [--sample N]                         # cap total drafts (smoke mode)
    [--write]                            # write stubs to disk (default: stdout only)
    [--out DIR]                          # output directory (required if --write)
    [--json]                             # structured JSON report
    [-v | --verbose]                     # per-gap progress
```

**Exit codes:**

- `0` — every gap drafted with ≥ `--min-supporting` evidence.
- `1` — at least one gap skipped or emitted as external-research.
- `2` — bad input (see §D9).

**Default output** (markdown, stdout):

One stub section per gap, separated by `\n---\n`. See §D4 for shape.

## Breakdown into atomic actions (15-min rule)

Ordered for the PIV loop. Each step has a single dominant risk and a validation check. Phase 6.1 is model-free so plumbing is validated without tokens.

### Phase 6.1 — Skeleton & Plumbing (no real LLM)

1. **Define data classes in `src/wikilens/answer.py`:** `AnswerDraft`, `AttributionReport`, `AnswerReport`. Validate: module imports; unit test round-trips a draft through dataclass.
2. **Define `Drafter` protocol + `MockDrafter` in `src/wikilens/drafter.py`.** Validate: protocol check; unit test calls MockDrafter with seeded output.
3. **Implement `load_gaps(path)` — parse `gap --json`, validate schema_version.** Validate: unit test on fixture JSON; malformed JSON → `ValueError`; wrong version → explicit error.
4. **Implement `retrieve_support(store, question, top_k, mode)` wrapper around P2's `query()`.** Validate: unit test on ingested mini-vault returns top-k with deterministic order.
5. **Implement `draft_answers(gaps, store, drafter, opts)` pipeline** — per gap: retrieve → merge with supporting_chunk_ids → filter by min_supporting → drafter.draft() → attribution check. Returns list of `AnswerDraft`. Validate: unit test with MockDrafter on 3-gap fixture produces expected structure; skip case covered.
6. **Implement `answer_format.py`** — markdown stub renderer (5 sections + frontmatter + external-research variant) + JSON serializer. Validate: snapshot tests for strong / thin / external-research cases.
7. **Implement `check_attribution(draft_markdown, retrieved_chunk_ids)`** — parse footnotes, compute `AttributionReport`. Validate: unit tests for all-cited, partial, orphan-footnote, invalid-chunk-ref cases.
8. **Wire `wikilens answer` CLI subcommand** using `MockDrafter` when `--judge none`. Validate: `wikilens answer fixtures/gaps_vault --gaps <p5-json> --judge none` prints expected stubs; exit code 0/1 correct.
9. **Implement `--write --out <dir>` path** — create dir, write one `.md` per draft, refuse-overwrite. Validate: unit test creates + rewrites (collision), collision reported as exit 2.

### Phase 6.2 — The Cognitive Kernel

10. **Implement `OpenAIDrafter`** — Chat Completions API, structured prompt enforcing citation discipline, retry on malformed output. Validate: mock the SDK client; unit test verifies prompt structure, footnote format, retry path, missing-key error.
11. **Implement `ClaudeDrafter`** — Anthropic Messages API, same prompt shape, same retry path. Validate: parallel unit test to OpenAI counterpart.
12. **Hand-tune drafter prompt** on 2 seed gaps from gaps_vault. Validate: on calvin-cycle gap with retrieval returning photosynthesis + chlorophyll chunks, produces a draft with ≥ 2 cited sentences in "What the vault says" and a non-empty "Evidence gaps" section.

### Phase 6.3 — Eval Fixture (gold answer sketches)

13. **Hand-write `fixtures/eval/p6_answer_sketches.json`** — for each of the 10 P5 gold gaps, list 3–5 key claims a competent stub should cover + required_chunks hint. Validate: every `required_chunks` entry resolves to a real ingested chunk; schema validation unit test.
14. **Implement eval-harness judge prompt** — four-axis 1–5 rubric matching §D5. Validate: unit test with mocked judge on synthetic draft/sketch pairs at each rubric level.

### Phase 6.4 — Eval Harness + Benchmark

15. **`scripts/eval_p6.py`** — pipeline: load gaps (from cached P5 JSON) → run `draft_answers` → judge each draft on 4 axes → write borderline log → compute pass-rate + per-axis means + attribution-rate + skip-rate → append to `BENCHMARK.md`. Validate: `--judge none` run (mock drafter + mock judge) produces deterministic numbers; `--judge openai` run hits target bars.
16. **Performance pass** — wall clock < 3 min on 10-gap eval with `--judge openai`; < 5s with `--judge none`. Validate: measured numbers in `BENCHMARK.md`.
17. **Meta-reasoning review** — manually read `docs/p6-judge-notes.md` borderline decisions; decide whether any rubric axis needs refinement or any gold sketch was wrong. Validate: review outcomes pasted into `docs/p6-decisions.md`.

### Phase 6.5 — Ship

18. **Docs + release** — `docs/p6-decisions.md`, README section, `HANDOFF.md` + `.local/HANDOFF.md` updates, version bump to `0.6.0`, tag `v0.6.0` **locally**. `gotchas.md` updates if anything bit. Validate: fresh-clone smoke (`pip install -e '.[dev,judge]'` + ingest + gap + answer + eval) works end-to-end. **Do not push without explicit user approval.**

Every step ends with `pytest -q` green and `python scripts/check_sanitization.py` on staged diff before commit.

## Risks & mitigation

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Drafter hallucinates content not in retrieved chunks | High | **Very high** (content lands in user's vault) | Strict prompt ("cite every sentence"); attribution check flags missing citations; faithfulness judge flags unfaithful cited sentences; pass bar is 0.80 faithfulness |
| Drafter cites correct chunk_id for wrong sentence (citation theater) | Med | High | Faithfulness judge specifically tests "is this sentence supported by this chunk?"; attribution-quality axis separately measures "is this the strongest available evidence?" |
| Retrieval pulls low-relevance chunks → drafter forced to synthesize thin evidence | Med | Med | `--min-supporting` skips; rerank mode (P2 Hit@5 = 1.00) is the default; supporting_chunk_ids from gap output pre-seed the evidence set |
| Coverage bar too strict → drafts penalized for paraphrasing gold claims | Med | High | LLM judge (not cosine); key_claims are semantic, not literal; threshold = 4 allows "same claim, different wording" |
| Structure judge is noise (formatting pedantry) | Low | Med | Narrow structure rubric: sections present + in order + frontmatter complete. Not "is the prose stylish." |
| `--write` overwrites user files | Low | **Very high** | No-overwrite policy hard-coded; `--force` not in v0.6.0; collision = exit 2 |
| Gap JSON schema drift between P5 and P6 | Low | Med | `schema_version: 1` check; explicit error on mismatch |
| OpenAI API key leak in logs | Low | Very high | Drafter doesn't log prompts; sanitization scanner on staged diff |
| Judge bias (same model grades its own output) | High | Med | Documented in `docs/p6-decisions.md`; borderline log as honesty check; deferred meta-eval |
| Attribution parser false negatives on edge-case markdown | Low | Low | Conservative regex; unit tests on adversarial inputs (footnotes inside code blocks, etc.) |
| Cost blowup on large gap lists | Low | Med | `--sample` caps; default eval is 10 gaps; per-draft cost ~$0.01 |
| Fixture sanitization breach | Low | Very high | Reuses existing public-domain `gaps_vault/`; no new vault content in P6 |

## Gotcha log (P6 working notes)

Empty at SDD time. Will populate during execution. Anything that bites → `gotchas.md` at repo root (G6+).

## Handoff from P5

- Repo: tip of `main` at `e88067c`, tag `v0.5.0` pushed to origin.
- 224 tests green.
- P2 retrieval reused via `query(mode=rerank, k=top_k)` — no changes needed.
- P5 `OpenAIGenerator` / `ClaudeGenerator` SDK setup, retry loop, and `.env` loading pattern are the templates for `OpenAIDrafter` / `ClaudeDrafter`.
- `OPENAI_API_KEY` + `ANTHROPIC_API_KEY` already provisioned.
- `fixtures/gaps_vault/` already ingested in P5's eval DB — can reuse for P6 eval runs.
- `fixtures/eval/p5_ground_truth.json` provides the 10 gold gap IDs that the P6 sketches key off.

## What we learn in P6

- Building a **consumer agent** — first phase that takes another agent's output as its canonical input. Tests the "Agentic Web" protocol story in practice.
- **Generation under a strict attribution contract** — every sentence must cite evidence, verified both automatically (parser) and semantically (LLM judge). This is the most production-relevant pattern in the project so far.
- **Multi-axis eval design** — when a single number hides the failure mode, splitting it into faithfulness / coverage / attribution / structure surfaces which axis to push next.
- **Irreversibility gating** — `--write --out <dir>` + no-overwrite is the minimum viable "human in the loop" for a content-producing agent.
- Honest acknowledgment that faithfulness ≥ 0.80 is the defining bar — a content-producing agent that hallucinates once in ten is not shippable into the user's vault without a human review step, regardless of coverage.

## Open questions the user must resolve before Phase 6.2

- **Gap JSON provenance.** Should `scripts/eval_p6.py` cache a known-good `gaps.json` from a fixed P5 run (committed to repo) so the eval is fully reproducible, or call `wikilens gap` live on every run (slower, but tests the integration)? Default proposal: **cache one `fixtures/eval/p6_input_gaps.json` committed to repo, with a script comment noting how to regenerate**. This isolates P6 eval from P5 stochasticity.
- **Judge backend for eval.** Same model as drafter (`gpt-4o`) to match P5's pattern, or different model to reduce self-grading bias? Default proposal: **same model, document the bias, defer cross-model meta-eval to P6.5**.
- **Stub file naming on collision.** If the user has an existing `calvin-cycle.md`, current policy is "refuse, exit 2." Alternative: suffix (`calvin-cycle-1.md`) with a warning. Default proposal: **refuse, no silent suffixing**. Silent suffix is a foot-gun; explicit human decision is the safer path.
- **Whether to commit `fixtures/eval/p6_input_gaps.json`** or gitignore it (regenerated per run). Same tension as P5's matcher-notes question. Default proposal: **commit it** — it's part of the reproducibility story, and the gaps JSON contains no private content.
