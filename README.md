# wikilens

> An agentic intelligence layer for Markdown / Obsidian vaults.
> RAG + evaluated metacognitive agents, built in public.

**Status:** Pre-alpha · P2 shipped. `wikilens ingest` + `wikilens query` work end-to-end on local Markdown vaults. [See benchmark →](./BENCHMARK.md)

---

## What it is

`wikilens` turns a folder of Markdown notes (an Obsidian vault, a Zettelkasten, any personal knowledge base) into a queryable, auditable, self-aware knowledge system.

It is:

- **Local-first.** Runs on your machine. Your notes never leave unless you explicitly call a remote LLM.
- **Agent-based.** Individual capabilities (link auditing, contradiction detection, gap finding) are isolated agents with measured performance.
- **Evaluated, not vibes.** Every agent ships with a labeled test fixture and a reported score. No "it seems to work."
- **Markdown-native.** Understands Obsidian-flavored syntax: `[[wikilinks]]`, YAML frontmatter, callouts, embeds.

It is not:

- A hosted SaaS (v1 is local only)
- A note editor (bring your own — Obsidian, VS Code, plain text)
- A chatbot wrapper ("chat with your notes" is table stakes; this is the layer above that)

## Why it exists

Second-brain tools have exploded, but most are storage-shaped, not thinking-shaped. They help you *save* notes, not *reason across them*.

The interesting question isn't "can an LLM answer a question about my vault" — that's solved. The interesting questions are:

- Where does my vault **contradict itself**?
- What **should be there but isn't** (gaps)?
- Which links are **missing** or **wrong**?
- What am I **circling without naming** (emergent concepts)?

Each of those is an agent. Each has a measurable success criterion. That's the project.

## Who it's for

Knowledge workers who keep a serious Markdown vault (≥ 200 notes) and want more than search. Researchers, writers, developers, second-brain practitioners.

## Roadmap

| Phase | Goal | Status |
|---|---|---|
| P1 — Bootstrap | Repo, scaffold, manifesto | ✅ shipped |
| P2 — RAG core | Markdown ingestion + local vector store + `query` CLI | ✅ shipped (`v0.2.0`) |
| P3 — Link Auditor agent | Detect broken wikilinks, orphan notes, one-way links | Next |
| P4 — Contradiction Finder agent | Multi-hop retrieval + LLM-judge for semantic conflicts | — |
| P5 — Eval harness | Public benchmark dataset + per-agent scores | — |
| P6 — Gap Generator agent | Propose missing sub-topics given a cluster | — |
| P7 — Polish + launch | Docs site, install guide, launch thread | — |

## Design principles

1. **No silent steps.** Every agent explains what it did and why.
2. **Reproducible evaluation.** `make benchmark` produces the numbers in `BENCHMARK.md`.
3. **No vendor lock.** Swappable embeddings, swappable LLMs, swappable vector stores.
4. **Fail loud.** Broken inputs are surfaced, never guessed.

## Install

Not yet published to PyPI. From a clone:

```bash
git clone https://github.com/Universe8888/wikilens.git
cd wikilens
pip install -e '.[dev]'
```

Python 3.12 is required. First run downloads two local models (~270 MB
total, cached for reuse): `BAAI/bge-small-en-v1.5` for embeddings and
`BAAI/bge-reranker-base` for reranking.

## Usage

```bash
# Build the index (full rebuild each run in P2; incremental lands in P3).
wikilens ingest ./my-vault

# Query — four retrieval modes are supported.
wikilens query "how do plants turn light into sugar"            # default: rerank
wikilens query "..." --mode dense                               # cosine only
wikilens query "..." --mode bm25                                # FTS / BM25 only
wikilens query "..." --mode hybrid                              # RRF fusion
wikilens query "..." --mode rerank -k 10                        # top-k after rerank
```

Index defaults to `.wikilens/db` inside the current directory; override with
`--db <path>`.

## Benchmark

On the in-repo synthetic vault (36 notes, 152 chunks, 20 hand-written queries),
every mode clears the P2 target of hit@5 ≥ 0.60 — most reach 1.00. See
[`BENCHMARK.md`](./BENCHMARK.md) for the full ablation table including
latency per mode. Reproduce from a fresh clone:

```bash
wikilens ingest fixtures/sample_vault --db .wikilens_test/db
python scripts/eval_p2.py --db .wikilens_test/db
```

## Writing / research

Design decisions and methodology writeups are published as they happen. Index will live at [`/docs`](./docs/) once P2 is done.

## License

MIT — see [LICENSE](./LICENSE).

## Author

Built by [Boris Manzov](https://github.com/Universe8888). Feedback and ideas welcome in [Issues](https://github.com/Universe8888/wikilens/issues).
