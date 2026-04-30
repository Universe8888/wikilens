# P2 — RAG Core

**Status:** Planned, not started
**Created:** 2026-04-30
**Target effort:** 1–2 weeks part-time (~20h)
**Preceded by:** P1 (bootstrap) — complete, commit `14f0d29`

---

## Goal

A working `wikilens ingest <vault>` + `wikilens query "..."` pair: point it at a folder of Markdown files, and it returns semantically relevant chunks ranked by similarity, in under 2 seconds for a medium vault (~500 notes).

This is the foundation every later agent builds on. Get the primitive right, and P3/P4/P6 are additive. Get it wrong, and every agent inherits the rot.

## Pass/Fail criterion (from SDD)

> `wikilens query "…"` returns top-5 relevant chunks from sample vault in <2s; manual recall ≥60% on 20 hand-written queries.

Concretely:
- Sample vault: 30–50 synthetic notes in `fixtures/sample_vault/`
- Eval set: 20 hand-written `(question, expected_note_titles)` pairs in `fixtures/eval/p2_queries.jsonl`
- Metric: **recall@5** — fraction of queries where ≥1 expected note appears in top 5 results
- Target: ≥0.60 (this is the floor — good RAG should hit 0.8+ even in P2, but we're being honest about scaffolding)
- Latency: p95 < 2s on a ThinkPad-class machine after index is warm

## Scope

### In
- Vault discovery (walk `*.md`, configurable glob filters)
- Frontmatter parser (YAML)
- Wikilink/tag/embed extractor (regex-based, not a full parser)
- Chunking (heading-aware, paragraph-boundaries, with overlap)
- Embedding (single pluggable backend for P2)
- Vector store (single backend for P2)
- `wikilens ingest <path>` — build/refresh index
- `wikilens query "..."` — semantic retrieval, top-k, with source citations
- 20-query eval harness + recall@5 reporting

### Out (defer to later phases)
- Reranking (P5 polish)
- Hybrid search (BM25 + vector) — stretch, only if recall@5 < target
- Incremental re-indexing (P2 does full rebuilds; incremental is P3)
- Any LLM generation (querying returns chunks, not answers — generation is P4)
- Multi-vault / multi-index support
- Config file (CLI flags only for P2)

## Design decisions — the five blockers

These are the open questions from `ARCHITECTURE.md`. Each has a recommended default + reasoning so we can unblock fast.

### D1. Vector store — **LanceDB** (recommended)

| Option | Pros | Cons |
|---|---|---|
| **LanceDB** ✅ | Embedded, zero server, modern columnar format, actively developed, Arrow-native, good Python DX | Younger ecosystem |
| Chroma | Simple, popular, decent docs | Heavier dependency, weird migrations between versions, slower on large sets |
| sqlite-vss | One-file, tiny | Extension loading on Windows is finicky; slower on HNSW |

**Pick:** LanceDB. Local-first fits, no server to manage, and using it early gives you real experience with a tool that's gaining traction — resume-relevant. Fallback to Chroma only if LanceDB on Windows bites us.

### D2. Embedding model — **BAAI/bge-small-en-v1.5** (local) for P2

| Option | Pros | Cons |
|---|---|---|
| **BGE-small local (via sentence-transformers)** ✅ | No API key, no cost, offline, fast, 384-dim | English-only, downloads ~130MB first run |
| OpenAI text-embedding-3-small | Excellent quality, cheap | Requires key, cost per run, leaks content to vendor |
| Voyage / Cohere | High quality | Vendor lock, cost, key |

**Pick:** BGE-small local. P2's job is the pipeline, not top-tier retrieval quality. Local means the `make benchmark` everyone can run has no API dependency. Upgrading to remote models becomes a swap in P5 (swappability = design principle #3).

### D3. Chunking — **heading-aware paragraph chunks with overlap**

Strategy:
1. Split on H2/H3 headings first (semantic section boundaries)
2. Within each section, group paragraphs until token budget (~400 tokens)
3. 15% overlap between adjacent chunks to avoid boundary misses
4. Preserve metadata: source file, section heading path, chunk index

**Rejected:** fixed-size char splitting (breaks mid-sentence, mid-list), semantic splitting (adds LLM dependency at ingest time — kills local-only guarantee).

### D4. Agent orchestration — **N/A for P2**

P2 has no agents. `query` is a pure retrieval call. Orchestration question defers to P3 when the first agent (Link Auditor) lands. P3 agent is a pure function; P4 is where planner-executor may matter.

### D5. LLM backend — **N/A for P2**

P2 doesn't call an LLM. Generation is P4+. When it arrives, default will be native Anthropic SDK with LiteLLM as a swap-in for multi-provider — but that's a decision for P4.

## Deliverables checklist

- [ ] `src/wikilens/ingest.py` — vault walker, frontmatter parser, link extractor, chunker
- [ ] `src/wikilens/embed.py` — pluggable embedding interface + BGE-small backend
- [ ] `src/wikilens/store.py` — pluggable vector store interface + LanceDB backend
- [ ] `src/wikilens/query.py` — semantic search + result formatting
- [ ] `src/wikilens/cli.py` — wire up `ingest` and `query` subcommands
- [ ] `fixtures/sample_vault/` — 30–50 synthetic notes with deliberate wikilinks/tags
- [ ] `fixtures/eval/p2_queries.jsonl` — 20 hand-written (query, expected_titles) pairs
- [ ] `scripts/eval_p2.py` — runs eval set, reports recall@5, writes to `BENCHMARK.md`
- [ ] `tests/test_ingest.py`, `tests/test_chunker.py`, `tests/test_query.py`
- [ ] `docs/p2-decisions.md` — log actual choices made (may diverge from plan — honest)
- [ ] `README.md` updated with install + usage
- [ ] `BENCHMARK.md` first version with P2 numbers
- [ ] Tag release `v0.2.0`

## Breakdown into atomic actions (15-min rule)

Ordered for the PIV loop. Each step has a single dominant risk and a validation check.

1. **Install deps** — `lancedb`, `sentence-transformers`, `pyyaml`, `tiktoken` (for token counting). Pin versions. Validate: `pip install -e '.[dev]'` succeeds.
2. **Vault walker** — glob-based file discovery, returns list of paths. Validate: unit test on `fixtures/sample_vault/` returns known file count.
3. **Frontmatter parser** — YAML extraction, graceful failure. Validate: unit test on a note with/without frontmatter.
4. **Wikilink extractor** — regex for `[[link]]`, `[[link|alias]]`, `![[embed]]`. Validate: unit test on a dozen variants.
5. **Chunker v1** — heading-split → paragraph-group → token budget. Validate: total token count preserved modulo overlap; no chunk > budget.
6. **Embedding backend interface** — `Embedder` protocol + `BGEEmbedder` impl. Validate: embed a string, dim = 384.
7. **Vector store interface** — `VectorStore` protocol + `LanceDBStore` impl (create, upsert, search). Validate: round-trip a known vector, get it back with score 1.0.
8. **Pipeline wiring** — `ingest` glues walker → chunker → embedder → store. Validate: ingest sample_vault, count rows in LanceDB matches expected chunks.
9. **Query path** — embed query → vector search → format results with citations. Validate: query "photosynthesis" on a note about photosynthesis returns that note in top-1.
10. **CLI wiring** — `wikilens ingest <path>`, `wikilens query "..."`. Validate: run from shell end-to-end on sample_vault.
11. **Sample vault content** — 30–50 synthetic notes (public-domain topics: science, philosophy, cooking, fake meeting notes). Validate: manually spot-check for content diversity.
12. **Eval set** — 20 `(query, expected_titles)` pairs covering easy / medium / hard retrieval. Validate: human review that expected_titles are actually the best answers.
13. **Eval harness** — runs queries, computes recall@5, prints to stdout + appends to `BENCHMARK.md`. Validate: reported number matches manual spot-check.
14. **Performance pass** — measure p95 latency; if > 2s, investigate (embedding cache? index type?). Validate: p95 < 2s reported.
15. **Docs + release** — update README install + usage, tag `v0.2.0`, write `docs/p2-decisions.md`. Validate: fresh clone + install + `wikilens query` works in < 5 min.

## Risks & mitigation

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| BGE model download flakes on first run | Med | Low | Pre-download in install instructions; cache path configurable |
| LanceDB Windows install issues | Low | High | Fallback plan: swap to Chroma (interface is pluggable by design) |
| Recall@5 falls below 0.6 | Med | High | Hybrid search (BM25 + vector) as rescue lever; accept honest low score + writeup |
| Chunking splits bad | Med | Med | Heading-aware + overlap mitigates; test fixtures include edge cases |
| Sample vault accidentally includes private content | Low | Very high | Pre-commit hook + manual review before each commit |

## Gotcha log (P2 working notes)

None yet. Will be populated during execution. Any failures → `gotchas.md` in repo root.

## Handoff from P1

- Repo live: https://github.com/Universe8888/wikilens
- Local: `C:\Projects2026\wikilens\`
- Branch: `main`, commit `14f0d29`
- Smoke tests pass (`pytest tests/ -q` → 4 passed)
- CLI stubs know all P2+ commands exist but return "not available yet"
- No remote LLM calls anywhere yet — P2 keeps it that way

## What we learn in P2

- RAG pipeline construction end-to-end (cert demo)
- LanceDB as a vector store (resume-relevant)
- Eval-first discipline (the habit that separates hobbyists from engineers)
- Honest benchmarking on a public fixture (the research-output seed)
