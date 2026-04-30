# Architecture — wikilens

High-level sketch. This document will be updated as each phase lands.

## Shape of the system

```
                 ┌──────────────────────────────────┐
                 │           User's Vault           │
                 │  (folder of .md files + assets)  │
                 └─────────────────┬────────────────┘
                                   │
                                   ▼
           ┌───────────────────────────────────────────┐
           │              Ingestion Layer              │
           │  parse frontmatter · extract wikilinks ·  │
           │        chunk · embed · persist            │
           └─────────────────┬─────────────────────────┘
                             │
            ┌────────────────▼─────────────────┐
            │        Local Index Store         │
            │    (vector DB + graph index)     │
            └────────────────┬─────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
  │   Agent:    │     │   Agent:    │     │   Agent:    │
  │ Link Audit  │     │ Contradict. │     │    Gap      │
  │             │     │   Finder    │     │  Generator  │
  └──────┬──────┘     └──────┬──────┘     └──────┬──────┘
         │                   │                   │
         └───────────────────┼───────────────────┘
                             ▼
                  ┌──────────────────────┐
                  │   CLI / Report Out   │
                  └──────────────────────┘
```

## Layers

### 1. Ingestion
- Walks a vault directory, filters by configurable include/exclude globs.
- Parses YAML frontmatter (typed where possible).
- Extracts `[[wikilinks]]`, `#tags`, embeds (`![[...]]`), callouts.
- Chunks content (strategy TBD in P2 — paragraph-aware, respecting headings).
- Builds two parallel representations:
  - **Vector index** for semantic retrieval
  - **Graph index** for link-topology queries (no LLM needed for link audits)

### 2. Index store
- Vector backend: pluggable, default likely LanceDB or Chroma (local, no server).
- Graph backend: in-memory dict keyed by page slug → in/out links.
- Both rebuildable from source on demand; state is a cache, not truth.

### 3. Agents
Each agent is a pure function of `(index, config) → findings`. Contract:
- Takes the index + its own config block
- Returns a list of typed findings (each with severity, location, evidence)
- Has a corresponding fixture + eval script
- Reports performance in `BENCHMARK.md`

**Planned agents:**

| Agent | Dominant technique | Eval metric |
|---|---|---|
| Link Auditor | Graph traversal, no LLM | Precision/recall on labeled breaks |
| Contradiction Finder | Multi-hop retrieval + LLM judge | Precision on annotated pairs |
| Gap Generator | Cluster + LLM proposal + heuristic filter | Blind usefulness rating |

### 4. CLI
`wikilens <command>` subcommands:
- `ingest <path>` — build/refresh index
- `query "..."` — RAG-style answer
- `audit links` — run Link Auditor
- `find contradictions` — run Contradiction Finder
- `find gaps` — run Gap Generator
- `benchmark` — run full eval harness

## Open design questions

These live in `docs/decisions/` once P2 starts. Current list:
- Vector store: LanceDB vs Chroma vs sqlite-vss?
- Embedding model: local (BGE, E5) vs remote (OpenAI, Voyage)?
- Chunking: paragraph vs heading-section vs semantic-split?
- Agent orchestration: single-pass vs planner-executor?
- LLM backend: provider-agnostic (LiteLLM) vs native Anthropic?

## What this is not

- Not a web app. CLI + library only in v1.
- Not a replacement for Obsidian's core search. Complementary.
- Not a chatbot. Query results are findings, not conversation.
