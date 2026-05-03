# Changelog

All notable changes to `wikilens` are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versions follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

---

## [0.11.0] — 2026-05-03

### Changed
- **README rewritten for v0.11.0 launch.** New structure: single-sentence hook, 8-agent capability table with benchmark numbers, 3-command quickstart, link to `BENCHMARK.md`. Technical audience; no hand-holding sections.
- Versioning policy added to README: pre-1.0, minor bumps may include CLI and schema changes.
- P11 (Obsidian Plugin) deferred indefinitely; removed from README and ROADMAP next-steps.
- ROADMAP updated: P12 (v0.11.0 Launch) is the active phase.

---

## [0.10.0] — 2026-05-03

### Added
- **Epistemic Confidence Mapper** (`wikilens confidence <vault>`): reads each note, extracts sentence-level declarative claims (reusing `drift.extract_claims()`), and classifies every claim on a five-level epistemic confidence scale — speculation (1), conjecture (2), inference (3), attributed (4), verified (5).
- Pluggable confidence judge: `MockConfidenceJudge` (dry-run), `OpenAIConfidenceJudge` (`gpt-4o`, default), `ClaudeConfidenceJudge` (`claude-sonnet-4-6`). JSON verdict schema: `{level 1–5, rationale, confidence 0–1}`.
- System prompt uses an explicit decision order (L5 → L4 → L3 → L1 → L2) with signal-word lists for each level. L1 requires an explicit hedge phrase; L2 is the last resort. Eliminates first-person-voice false positives.
- Response parser strips markdown code fences before `json.loads` and adds `response_format={"type": "json_object"}` for gpt-4o, eliminating ~40% abstention rate from JSON-in-fence wrapping.
- Context window for judge: claim sentence ± 2 surrounding sentences from the same note.
- `ConfidenceFinding` dataclass: `note`, `claim`, `level`, `rationale`, `confidence`, `span`.
- Markdown report by default (low-confidence claims listed with level, rationale, span); `--json` for machine-readable output (`schema_version: 1`).
- Cost-control flags: `--threshold N` (report level ≤ N; default 2), `--sample N` (cap judge calls), `--only NOTE`, `--min-confidence F`.
- Exit 0 clean / 1 findings / 2 bad input — consistent with P3–P9 convention.
- Hand-crafted eval fixture `fixtures/confidence_vault/` (15 public-domain hobbyist notes, ~249 extractable claims).
- Ground-truth `fixtures/eval/p10_ground_truth.json` (179 labeled claims: L1=49, L2=32, L3=39, L4=31, L5=28).
- Eval harness `scripts/eval_p10.py`: P/R/F1 on binary low-confidence class + Quadratic Weighted Kappa (QWK) over 5-level ordinal. Scoring uses partial-annotation methodology — unmatched predictions excluded (standard NER/claim-detection practice for non-exhaustive gold sets). Appends to `BENCHMARK.md`.
- New modules: `confidence.py`, `confidence_judge.py`, `confidence_format.py`.
- 41 new tests; 468 total.

### Eval results (gpt-4o, `fixtures/confidence_vault/`, threshold=2)
- Precision = 0.91, Recall = 0.88, F1 = 0.89 — both ≥ 0.70 targets met.
- QWK (ordinal, 5-class) = 0.881 — well above the 0.30 collapse warning threshold.

---

## [0.9.0] — 2026-05-03

### Added
- **Unnamed Concept Detector** (`wikilens concepts <vault>`): clusters vault chunks via BGE embeddings + K-means, then calls an LLM judge per cluster to propose the canonical term the notes are collectively circling around without ever naming it.
- Absence filter: a finding is kept only when the proposed term appears in fewer than 20% of the cluster's chunks — ensuring the concept is genuinely unnamed.
- Pluggable concept judge: `MockConceptJudge` (dry-run), `OpenAIConceptJudge` (`gpt-4o`, default), `ClaudeConceptJudge` (`claude-sonnet-4-6`). JSON response schema: `{proposed_term, confidence 0–1, rationale}`.
- `ConceptFinding` dataclass: `cluster_id`, `proposed_term`, `confidence`, `rationale`, `supporting_notes`, `evidence_chunks`, `term_freq_in_cluster`.
- Markdown report by default; `--json` for machine-readable output (`schema_version: 1`).
- Cost-control flags: `--top-k`, `--min-cluster-size`, `--max-clusters`, `--absence-threshold`.
- Exit 0 clean / 1 findings / 2 bad input — consistent with P3–P8 convention.
- Hand-crafted eval fixture `fixtures/concepts_vault/` (12 notes, 5 planted unnamed concepts): `cognitive load`, `emergence`, `opportunity cost`, `compounding`, `satisficing` — each described without using its canonical term.
- Ground-truth `fixtures/eval/p9_ground_truth.json` (5 labeled concepts with supporting note lists).
- Eval harness `scripts/eval_p9.py`: ingests fixture vault into a temp DB, scores precision/recall vs. gold, appends to `BENCHMARK.md`. Targets: precision ≥ 0.70, recall ≥ 0.70.
- 9 new tests; 427 total.
- XML prompt sanitization (`_sanitise_xml`) and retry/fallback pattern applied to all judge backends.

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
