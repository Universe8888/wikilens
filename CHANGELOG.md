# Changelog

All notable changes to `wikilens` are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versions follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

---

## [0.8.0] — 2026-05-02

### Added
- **Temporal Drift Detector** (`wikilens drift <vault>`): walks the vault's `git log` and surfaces notes where beliefs shifted over time — not typo fixes, genuine semantic claim changes.
- Claim extraction from note history: strips frontmatter, fenced code, headings, wikilinks; sentence-level or paragraph-level granularity (`--granularity`).
- BGE cosine aligner pairs claims across adjacent revisions in `[τ_align, τ_identical)` window; three deterministic pre-filters (whitespace-only, list-reorder, Levenshtein typo).
- Pluggable drift judge: `MockDriftJudge` (dry-run), `OpenAIDriftJudge` (`gpt-4o`, default), `ClaudeDriftJudge` (`claude-sonnet-4-6`). Output schema: `{drift, type, score 1-5, reasoning}`.
- Drift types: `reversal`, `refinement`, `scope_change` — all counted as belief changes. `refinement` ("proven" → "may help") included per pre-kickoff decision.
- Markdown report by default; `--json` for machine-readable output (`schema_version: 1`).
- Exit 0 clean / 1 findings / 2 bad input — consistent with P3–P6 convention.
- Cost-control flags: `--sample`, `--since`, `--min-score`, `--only`, hidden `--align-threshold` / `--identical-threshold`.
- Hand-crafted eval fixture `fixtures/drift_vault/` (8 notes, 9 commits, `dotgit/` for safe tracking): 5 planted semantic drifts + 5 planted surface revisions.
- Ground-truth `fixtures/eval/p8_ground_truth.json` (10 labeled events with full commit SHAs).
- Eval harness `scripts/eval_p8.py`: restores fixture git history in a temp dir, scores precision/recall vs. gold, appends to `BENCHMARK.md`. Targets: precision ≥ 0.80, recall ≥ 0.80.
- Fixture builder `scripts/build_drift_fixture.py` for reproducibility.
- 106 new tests (4 test files); 413 total.
- `docs/p8-decisions.md`: decisions log including known limitations.

### Known limitations
- `--since` flag is parsed but not yet wired into `git log` (G6 in `gotchas.md`; fix deferred to P8.5+).
- Heavy renames / file splits not tracked (`git log --follow` limitation; documented in README).

---

## [0.7.0] — 2026-05-02

### Added
- Published to PyPI: `pip install wikilens`.
- GitHub Actions release workflow with trusted publishing (OIDC — no long-lived secrets).
- CI matrix expanded to Ubuntu + Windows on Python 3.12.
- First-run model-download notice on `ingest` and `query` when local models are absent.
- `CHANGELOG.md` (this file), backfilled from v0.2.0.

### Changed
- Development status classifier: Pre-Alpha → Alpha.

---

## [0.6.1] — 2026-05-02

### Fixed
- `wikilens answer --write` now rejects stub titles that would escape the `--out` directory (path-traversal guard).
- `wikilens ingest` honours documented full-rebuild semantics: stale LanceDB rows are removed before re-indexing.

### Changed
- `.[dev]` extra is now sufficient for `test`, `lint`, and `typecheck` workflows (previously required manual extras).
- Added `Makefile` targets: `lint`, `typecheck`, `test`, `check`, `benchmark`.
- GitHub Actions CI added for Python 3.12.

---

## [0.6.0] — 2026-05-01

### Added
- **Answer Generator** (`wikilens answer`): closes the gap loop. Consumes `wikilens gap --json` output, retrieves supporting vault evidence, and drafts structured Obsidian-ready note stubs.
- Stubs carry proof-carrying citations: every factual sentence has a `[^N]` footnote resolving to a retrieved `chunk_id`.
- Five-section stub shape: YAML frontmatter + *What the vault says* + *Evidence gaps* + *Related notes* + *Citations*.
- `--write --out <dir>` materialises `.md` files (no-overwrite policy).
- Pluggable drafters: `MockDrafter`, `OpenAIDrafter` (default `gpt-4o`), `ClaudeDrafter`.
- Automated `check_attribution` parser — verifies every `[^N]` resolves to a retrieved chunk ID without calling an LLM.
- 4-axis LLM-judge eval rubric (faithfulness / coverage / attribution quality / stub structure).
- Eval harness `scripts/eval_p6.py`; gold fixture `fixtures/eval/p6_answer_sketches.json` (10 sketches).
- **Pass rate = 0.80** (8/10 gold gaps pass all 4 axes ≥ 4). **Attribution rate = 1.00** (automated).

---

## [0.5.0] — 2026-05-01

### Added
- **Gap Generator** (`wikilens gap`): clusters vault chunks via k-means on BGE embeddings, then calls an LLM per cluster to surface unanswered questions implied by the vault's own content.
- Budgeted autonomy flags: `--min-cluster-size`, `--max-clusters`, `--sample`.
- `MockGenerator` + `SubstringMatcher` for `--judge none` dry-runs.
- `ClaudeMatcher` with pinned 1–5 rubric for eval; borderline decisions logged to `docs/p5-matcher-notes.md`.
- OpenAI backend (`--judge openai`, `gpt-4o` default) for generator and matcher.
- Eval harness `scripts/eval_p5.py`; gold fixture `fixtures/eval/p5_ground_truth.json` (10 gold gaps).
- **Cluster-stage recall = 1.00** (10/10 gold gaps surfaced). **Matcher F1 = 0.65**.

---

## [0.4.0] — 2026-04-30

### Added
- **Contradiction Finder** (`wikilens contradict`): retrieval-based pair generation (O(n·k)), three dedup filters, pluggable LLM judge.
- `ClaudeJudge` via Anthropic SDK (`claude-sonnet-4-6`); `MockJudge` for `--judge none` dry-runs.
- Factual + temporal contradiction types, scored and explained.
- Flags: `--sample`, `--min-score`, `--only`, `--json`.
- Exit 0 clean / 1 findings / 2 bad input — usable as a CI gate.
- Eval harness `scripts/eval_p4.py`; ground-truth fixture `fixtures/eval/p4_ground_truth.json` (24 labeled pairs).
- **Overall F1 = 0.82**, retrieval recall = 0.90 on the 24-pair fixture. Wall clock 67.7s.

---

## [0.3.0] — 2026-04-30

### Added
- **Link Auditor** (`wikilens audit`): detects broken wikilinks, one-way links, orphan notes, and shadowed basenames.
- Markdown report by default; `--json` for machine-readable output; `--only` class filter.
- Exit 0 clean / 1 findings / 2 bad input — usable as a pre-commit or CI gate.
- Eval harness `scripts/eval_p3.py`; ground-truth fixture `fixtures/eval/p3_ground_truth.json` (19 planted defects).
- **Precision = Recall = F1 = 1.00** on all four detector classes.
- Security policy (`SECURITY.md`) and git-hook installer (`scripts/install_hooks.sh`).

---

## [0.2.0] — 2026-04-30

### Added
- **RAG core**: `wikilens ingest <vault>` + `wikilens query "..."` working end-to-end.
- Four retrieval modes: `dense`, `bm25`, `hybrid` (RRF, Cormack et al. 2009), `rerank` (BGE cross-encoder).
- Heading-aware chunker with enriched metadata, deterministic SHA-256 chunk IDs.
- BGE embedder (`BAAI/bge-small-en-v1.5`, ~130 MB); BGE reranker (`BAAI/bge-reranker-base`, ~140 MB). Both cached after first run.
- Hybrid search via LanceDB native FTS + reciprocal-rank fusion.
- **Hit@5 = 1.00** in all four modes on a 20-query eval set. p95 rerank latency 1846ms.
- 36-note synthetic sample vault under `fixtures/sample_vault/`.
- Eval harness `scripts/eval_p2.py`; query fixture `fixtures/eval/p2_queries.jsonl`.

[Unreleased]: https://github.com/Universe8888/wikilens/compare/v0.8.0...HEAD
[0.8.0]: https://github.com/Universe8888/wikilens/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/Universe8888/wikilens/compare/v0.6.1...v0.7.0
[0.6.1]: https://github.com/Universe8888/wikilens/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/Universe8888/wikilens/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/Universe8888/wikilens/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Universe8888/wikilens/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Universe8888/wikilens/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Universe8888/wikilens/releases/tag/v0.2.0
