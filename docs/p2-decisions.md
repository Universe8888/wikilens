# P2 decisions log

**Status:** P2 complete, tagged `v0.2.0`.
**Written:** 2026-04-30 at end of phase.

A record of what was actually chosen during P2 and where reality diverged from
the plan in `p2-plan.md`. Honest, not aspirational.

## Stack (as shipped)

| Decision | Chosen | Planned | Notes |
|---|---|---|---|
| Vector store | **LanceDB 0.30.2** | LanceDB | Held. No Windows install issues. |
| Embedder | **`BAAI/bge-small-en-v1.5`** (384 dim, L2-normalized) | BGE-small | Held. Query-instruction prefix applied on queries only, not passages — the BGE convention. |
| Chunker | Heading-aware (H1/H2/H3), ~400 tokens, 15% overlap, sentence-split fallback for oversize paragraphs | As planned | Enriched chunk metadata beyond plan: deterministic `chunk_id`, content hash, char offsets, frontmatter, full heading path. |
| FTS / BM25 | **LanceDB native FTS index** | Not in initial plan; added via optimization pass | Kept separate FTS index over `text` alongside the dense index. |
| Fusion | **Reciprocal-rank fusion** (Cormack et al. 2009, `k=60`) | Not in initial plan; added via optimization pass | Score-agnostic — combines ranks, not raw scores. |
| Reranker | **`BAAI/bge-reranker-base`** cross-encoder | Not in initial plan; added via optimization pass | Runs on CPU; ~300ms per call for 20 candidates. |
| Tokenizer for budgets | **`tiktoken cl100k_base`** | Not in plan | Close approximation to BGE WordPiece count; ~10% drift is acceptable for budget math. |
| CLI | **`argparse`** | — | `wikilens ingest <path>` + `wikilens query <q> --mode {dense,bm25,hybrid,rerank} -k N`. |
| Python | **3.12** | 3.12 | Pinned in `pyproject.toml`. |

## The four retrieval modes

All four are exposed via `wikilens query --mode`. They share one indexed store —
no re-ingestion required to switch modes.

| Mode | What it does |
|---|---|
| `dense` | Pure cosine similarity against the BGE-small index. |
| `bm25` | Pure LanceDB FTS / BM25 search. |
| `hybrid` | RRF fusion of dense top-50 ∪ BM25 top-50. |
| `rerank` | `hybrid` top-20, cross-encoder rerank to top-k. Default. |

## Measured outcomes (see `BENCHMARK.md` for exact numbers)

- **Hit@5 = 1.00** in every mode on the 20-query eval set. Target was 0.60.
- **Partial recall@5 = 1.00** for `dense`, 0.97 for the other three — one
  multi-title query loses its second expected title after rerank but keeps
  its primary hit in top-1. That's the cost of rerank sharpening separation.
- **p95 latency:** dense 37ms, bm25 7ms, hybrid 65ms, rerank 1846ms. Rerank
  sits under the 2s target but with little headroom on CPU; the other modes
  have 30-280× the margin.
- **Corpus:** 152 chunks from 36 synthetic markdown files across 7 clusters
  (biology, chemistry, physics, philosophy, cooking, history, meetings).

## Divergences from the plan

### +1: Hybrid search shipped in P2, not P3+

`p2-plan.md` listed hybrid as a stretch goal "only if recall@5 < target." We
shipped it anyway because:

1. LanceDB's FTS index is native — adding BM25 costs one extra index build
   at ingest time and a few lines of query code.
2. RRF is simple, score-agnostic, and has been canonical since Cormack 2009.
3. Having the four-way ablation table is more interesting research output
   than a single number.

### +2: Reranker shipped in P2, not P5

Same reasoning. The `BAAI/bge-reranker-base` cross-encoder is 140MB, loads
lazily on first query, and the separation it produces on the sample corpus
is dramatic (top-1 = 0.92 vs. rank-2 = 0.14 on the photosynthesis query).
Pulling it forward gives every later phase a working reranker to build on.

### +3: Small CLI hardening

`sys.stdout.reconfigure(encoding="utf-8")` in the entrypoint. Without it,
Windows `cp1252` crashes on chunk snippets containing common typography
(arrows, em-dashes, degree signs). One defensive line, no downside.

## Open calls deferred to P3+

- **Incremental re-indexing** (detect changed files → upsert affected chunks
  only). Today's `ingest` does a full rebuild. Acceptable at 36 files; not at
  5,000.
- **Query-time caching** of the embedder and reranker models across CLI
  invocations. Every `wikilens query` pays ~2-3s cold-start to load both
  models. Fine for P2 smoke testing; mandatory for P3's eval-heavy agents.
- **Config file.** CLI flags only for P2. A `.wikilens.toml` with defaults
  per-vault will land when the first agent needs configuration (P3).
- **Multi-vault support.** P2 assumes one `--db` per invocation.

## Gotchas logged during P2

Full detail in `gotchas.md` at the repo root:

- **G1:** `sentence-transformers>=5.0` pulls `torchcodec` → import fails on
  Windows. Pinned `<5.0`.
- **G2:** `LanceDB.list_tables()` returns a paginated wrapper, not a list;
  membership checks silently fail. Unwrap with `getattr(raw, "tables", raw)`.
- **G3:** The frontmatter regex had catastrophic backtracking on YAML flow
  lists (`tags: [chemistry]`). Replaced with an O(n) line scanner.

## Reproducing the benchmark

From a fresh clone:

```bash
pip install -e '.[dev]'
wikilens ingest fixtures/sample_vault --db .wikilens_test/db
python scripts/eval_p2.py --db .wikilens_test/db
```

The second command appends a timestamped section to `BENCHMARK.md`. Prior
sections are preserved — every run is additive, not destructive.

## What's next

P3 — **Link Auditor** agent. Uses the P2 ingest to build a wikilink graph,
then flags: broken links (target note doesn't exist), one-way links (A → B
with no backlink), and orphan notes (no inbound links, ≥ 1 outbound). Each
diagnostic is a pure function over the ingested metadata, so the "agent" is
thin — the real test is whether the heuristics produce useful output, not
whether any clever orchestration runs.
