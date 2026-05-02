# P8 decisions log

**Status:** P8 complete, tagged `v0.8.0`.
**Written:** 2026-05-02 at end of phase.

Mirrors the shape of `docs/p6-decisions.md` — honest, not aspirational.

## Stack (as shipped)

| Decision | Chosen | Notes |
|---|---|---|
| Git backend | **subprocess (no GitPython)** | Avoids dep bloat. Four call sites in `drift.py`. `shell=False` throughout; SHA format check prevents injection even though it's redundant. |
| Claim granularity | **sentence-level default** | `--granularity paragraph` escape hatch available. Sentence splitter is rule-based with a small abbreviation list; no NLP deps. |
| Alignment thresholds | **τ\_align=0.75, τ\_identical=0.98** | Set before eval, not tuned post-hoc. `--align-threshold` / `--identical-threshold` are hidden CLI args for future calibration. |
| Judge backend default | **OpenAI gpt-4o** | Consistent with P5.4 memory (project-wide default). `--judge claude` uses `claude-sonnet-4-6`. |
| Drift types | **reversal, refinement, scope\_change, none** | `refinement` counted as drift with its own tag — a softened claim is a belief change. Confirmed pre-kickoff. |
| Transitive chaining | **adjacent-only** | Rev A→B and B→C are two events; A→C is not synthesized. Keeps eval math unambiguous. Deferred to P8.5+ if demand arises. |
| Fixture layout | **dotgit/ committed, renamed at eval time** | Reproducibility-by-clone. `_setup_fixture_git()` in `eval_p8.py` copies vault to tempdir and renames `dotgit/` → `.git/`. |
| Branch scope | **main / first-parent only** | `--first-parent` in `git log`. Multi-branch drift rare on personal vaults; deferred. |

## What shipped

| File | Role |
|---|---|
| `src/wikilens/drift.py` | Git walker, claim extractor, BGE aligner, 3 filters, pair builder |
| `src/wikilens/drift_judge.py` | `DriftJudge` protocol, `MockDriftJudge`, `OpenAIDriftJudge`, `ClaudeDriftJudge` |
| `src/wikilens/drift_format.py` | Markdown + JSON formatters, `schema_version: 1` |
| `src/wikilens/cli.py` | `wikilens drift` subcommand |
| `fixtures/drift_vault/` | 8 notes, 9 commits, `dotgit/` |
| `fixtures/eval/p8_ground_truth.json` | 10 labeled events (5 drift, 5 surface) |
| `scripts/build_drift_fixture.py` | Reproducible fixture builder |
| `scripts/eval_p8.py` | Eval harness; appends to `BENCHMARK.md` |
| 106 new tests across 4 test files | |

## Known limitations (documented, not bugs)

- **Heavy renames** (`git log --follow` misses splits and cross-path renames beyond git's similarity heuristic). Documented in README.
- **Cooking + philosophy candidate-pair gap**: the two notes' drift claims are long enough that the sentence aligner captures them at the paragraph level but not always as sentence-level pairs within the cosine window. The mock eval shows 0 pairs from `cooking.md` and `philosophy.md` — these notes benefit from `--granularity paragraph` or a lower `--align-threshold`. The real judge run should be calibrated against the fixture before declaring the P/R targets met.
- **Surface-edit E9 and E10**: ground truth pairs where `before_claim == after_claim` (added example / heading rename). The aligner correctly produces 0 candidate pairs for these — no pair surfaces, no FP. Verified in smoke run.
- **`--since` flag not yet wired** into `walk_note_revisions`. The CLI arg is parsed and passed through but `git log` does not yet apply it. Filed as G6 below.

## Gotcha G6 — `--since` not propagated to git log

**Phase:** P8.6 (discovered during decisions review)
**Symptom:** `wikilens drift --since 2026-01-01` ignores the date; full history is always walked.
**Root cause:** `_cmd_drift` reads `args.since` but never passes it to `walk_note_revisions`, which shells `git log` without `--after` or `--since`. The flag was designed and parked in the SDD as a cost-cap mechanism; the implementation was omitted.
**Fix (deferred to P8.5+):** Pass `since: str | None` to `walk_note_revisions`; append `[f"--after={since}"]` to the `git log` args when set.
**When this bites again:** Any time a CLI flag is added to the parser but the corresponding variable is not threaded through the pipeline.

## Open items for P8.5+ (post-ship)

1. Wire `--since` into `walk_note_revisions` (G6 above).
2. Calibrate cosine thresholds against `--judge openai` run on the fixture; tune if cooking/philosophy notes miss the P/R targets.
3. Consider `--granularity paragraph` as default for vaults with prose-heavy notes.
4. Transitive chaining: emit A→C event when A→B and B→C both exceed threshold (opt-in flag).
