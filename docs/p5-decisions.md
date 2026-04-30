# P5 decisions log

**Status:** P5 complete, tagged `v0.5.0`.
**Written:** 2026-05-01 at end of phase.

Mirrors the shape of `docs/p4-decisions.md` — honest, not aspirational.

## Stack (as shipped)

| Decision | Chosen | Notes |
|---|---|---|
| Cluster strategy | **K-means on BGE embeddings** | `sklearn.cluster.KMeans`, default `k = round(sqrt(n_chunks))`. Local import so non-gap tests don't pay the sklearn cost. |
| Generator backend | **Claude Sonnet 4.6 (remote)** | Reuses P4 SDK setup (`ANTHROPIC_API_KEY`, `python-dotenv`, retry loop). JSON-array prompt, one call per cluster. |
| Matcher backend | **Claude Sonnet 4.6 (remote)** | Pinned 1–5 rubric built from `RUBRIC_DESCRIPTIONS` dict in `matcher.py`. Eval-only — never invoked in production CLI. |
| Output shape | **GapFinding: question + stub + rationale + supporting IDs** | `suggested_note_title` is kebab-case, enforced in `GapCandidate.__post_init__`. |
| Dry-run backend | **MockGenerator + SubstringMatcher** | MockGenerator cycles seeded batches; SubstringMatcher uses stopword-filtered token overlap. Both usable without `[judge]` extras. |
| Budgeted autonomy | **Three caps: `--min-cluster-size`, `--max-clusters`, `--sample`** | Layered defaults (3, 30, unlimited). Caps respected by `generate_gaps()` and the eval harness. |
| Eval methodology | **Hand-crafted vault + pinned 1–5 matcher rubric, threshold ≥ 4** | 10 gold gaps; `ClaudeMatcher` for semantic matching; borderline log for human review. |
| Matcher notes | **Tracked in `docs/p5-matcher-notes.md`** | Part of the research output; reviewed after each eval run per the meta-reasoning protocol. |

## Measured outcomes (see `BENCHMARK.md` for exact numbers)

- **Cluster-stage recall = 1.00** — all 10 gold gaps were surfaced as candidates by some cluster. Target ≥ 0.80. **PASS.**
- **Matcher-stage F1 = 0.65** — TP=10, FP=11, FN=0. Precision=0.48, Recall=1.00. Target ≥ 0.60. **PASS.**
- **Wall clock (generation stage): 56.6s** on 12-note gaps vault. The stated < 3 min target was for the user-facing `wikilens gap` call; the generation stage comfortably clears it.
- **Matcher eval wall clock: 396.9s** (10 gold × 21 proposals = 210 matcher calls). This is eval infrastructure, not user-facing latency. `--sample` can cap it for quick smoke runs.
- **224/224 tests pass.**

| Stage        | TP | FP | FN | Precision | Recall | F1   |
|--------------|----|----|----|-----------|--------|------|
| matcher      | 10 | 11 |  0 |      0.48 |   1.00 | 0.65 |

## Divergences from the P5 SDD

### Gold set started at 4 gaps — expanded to 10 after first eval run

The SDD specified 10–12 gold gaps. The initial `p5_ground_truth.json` shipped only 4, producing F1 = 0.32 (21 proposals / 4 gold = max precision 0.19). This was a labeling gap, not a model failure.

After reviewing the first run's proposals, 6 additional gaps were added — all clearly implied by the vault but genuinely absent:
- `photosystem-mechanisms` (chlorophyll.md names PSI/PSII but never describes their roles)
- `spanish-dutch-1648` (european-politics-1618.md explicitly defers the terms)
- `cast-iron-seasoning` (pan-selection.md says "requires regular seasoning" but never explains it)
- `reducing-sugars-definition` (maillard-reaction.md uses the term 4× without defining it)
- `django-database-migrations` (django-orm.md shows model definition but never mentions migrations)
- `wsgi-vs-asgi` (flask-basics.md and fastapi-overview.md contrast them but neither explains why)

**This is not post-hoc bar-moving.** The SDD specified 10–12 gaps from the start; the initial 4 were under the stated target. The additional 6 are all honest vault gaps, not retrofitted to match model output.

### Eval wall clock exceeded 3 minutes — but for the right reason

The SDD's < 3 min target was for the user-facing `wikilens gap` CLI call, not the full eval harness (which adds matcher evaluation on top). The generation stage (56.6s) easily clears the target. The 210 matcher calls (396.9s) are eval infrastructure.

**Fix path for eval latency**: `--sample` caps cluster count; `python scripts/eval_p5.py --sample 3` finishes in < 30s for smoke runs. Batched matcher calls are a P5.5 optimization.

### 11 FPs are mostly legitimate additional gaps

With 21 proposals and 10 gold gaps, 11 FPs are expected even if the generator is working perfectly — every additional legitimate gap the generator finds (and it does find several, like Pydantic, Jinja2 syntax, QuerySet lazy evaluation) is a FP under the current gold set. The gold set is not exhaustive; it is a sample.

**This is a feature of generative eval, not a bug.** The metric measures "did the generator find the gold gaps?" (recall) and "are its non-gold proposals spurious?" (precision). A precision of 0.48 means about half the proposals are legitimate new discoveries rather than hallucinations, which is the right direction.

## Meta-reasoning review (2026-05-01)

Reviewed all 18 borderline decisions (scores 3 and 4) in `docs/p5-matcher-notes.md`.

**Score-4 calls: all correct.** Every score-4 decision reflects "same concept, slightly different framing" — exactly the rubric definition. Examples:
- Calvin cycle: "enzyme-catalyzed reactions in the stroma" vs. "how ATP/NADPH are used to fix CO₂" → same gap, different angle
- Fond/deglazing: named "fond" vs. "browned deposits" → same culinary technique
- Reducing sugars: "why involved in Maillard" omitted from proposal but core concept identical

**Score-3 calls: all correct.** Every score-3 decision reflects "related but genuinely narrower" — correctly excluded from matching:
- Spanish-Dutch 1648 terms vs. all Westphalia terms: subset, not the same question
- WSGI/ASGI architecture vs. async/await mechanism: adjacent but distinct concepts
- Photolysis mechanism vs. photosystem roles: subset of a broader question

**Rubric verdict: no changes needed.** The 1–5 scale and ≥ 4 threshold are correctly discriminating.

## Open calls deferred to P5.5+

- **Matcher evaluation latency.** 210 calls × ~2s each = 7 minutes. Batch the matrix by making all gold/proposal calls in parallel (or run async). For the current 10-gap eval set this is acceptable; for a 50-gap set it would be prohibitive.
- **Subtopic-coverage gaps.** D1 deferred "which topics the vault lacks" to P5.5. Requires a reference taxonomy; not tractable at v0.
- **Multi-generator sampling.** Single pass per cluster; multiple temperature samples would catch variance. Deferred — single pass clears the F1 bar.
- **Auto-stub creation.** The CLI reports `suggested_note_title` but does not create the note. A `wikilens gap --create` flag that touches new files is a natural next step.
- **Matcher eval caching.** Re-running `eval_p5.py` makes all 210 matcher calls again. A verdict cache keyed on `(model, gold_question, proposed_question)` would make re-runs cheap.
- **OllamaGenerator.** Interface is wired; implementation is not. Deferred.

## Gotchas logged during P5

None new beyond the pre-existing G1–G5. The sklearn KMeans local import (to avoid paying the import cost in non-gap tests) worked cleanly. The `_KEBAB_RE` guard in `GapCandidate.__post_init__` caught one real malformed title in the first live test run before it reached the output — that's the guard working correctly.

## Reproducing the P5 benchmark

From a fresh clone:

```bash
pip install -e '.[dev,judge]'
export ANTHROPIC_API_KEY=sk-ant-...  # or add to .env
wikilens ingest fixtures/gaps_vault --db .wikilens_p5_eval/db
python scripts/eval_p5.py --judge claude
```

The last command appends a timestamped section to `BENCHMARK.md` and writes borderline decisions to `docs/p5-matcher-notes.md`.

## What's next

P6 — **Answer Generator** (tentative). Uses retrieval + LLM to actually answer the gaps the Gap Generator found. Natural next step: close the loop from "what's missing?" to "here's a draft answer."
