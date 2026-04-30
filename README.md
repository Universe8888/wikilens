# wikilens

> An agentic intelligence layer for Markdown / Obsidian vaults.
> RAG + evaluated metacognitive agents, built in public.

**Status:** Pre-alpha · P5 shipped (`v0.5.0`). `ingest`, `query`, `audit`, `contradict`, and `gap` all work end-to-end on local Markdown vaults. [See benchmark →](./BENCHMARK.md)

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
| P3 — Link Auditor agent | Detect broken wikilinks, orphan notes, one-way links | ✅ shipped (`v0.3.0`) |
| P4 — Contradiction Finder agent | Multi-hop retrieval + LLM-judge for semantic conflicts | ✅ shipped (`v0.4.0`) |
| P5 — Gap Generator agent | K-means clustering + LLM to surface unanswered questions | ✅ shipped (`v0.5.0`) |
| P6 — Answer Generator | Close gaps by drafting note stubs from retrieved evidence | — |
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
# Build the index (full rebuild each run; incremental is deferred).
wikilens ingest ./my-vault

# Query — four retrieval modes are supported.
wikilens query "how do plants turn light into sugar"            # default: rerank
wikilens query "..." --mode dense                               # cosine only
wikilens query "..." --mode bm25                                # FTS / BM25 only
wikilens query "..." --mode hybrid                              # RRF fusion
wikilens query "..." --mode rerank -k 10                        # top-k after rerank

# Audit — find broken, one-way, orphan, and shadowed wikilinks.
wikilens audit ./my-vault                                       # markdown report
wikilens audit ./my-vault --json                                # machine-readable
wikilens audit ./my-vault --only broken,orphan                  # filter classes
```

`audit` exits 0 when clean, 1 when any finding is reported — so it doubles as
a pre-commit / CI gate. Index defaults to `.wikilens/db` inside the current
directory; override with `--db <path>`.

```bash
# Contradict — find conflicting chunk pairs (requires ANTHROPIC_API_KEY).
pip install -e '.[judge]'
wikilens contradict ./my-vault --judge claude                    # full run
wikilens contradict ./my-vault --judge none                      # dry-run (no API)
wikilens contradict ./my-vault --judge claude --sample 20        # cap API calls

# Gap — find unanswered questions the vault implies but doesn't answer.
wikilens gap ./my-vault --judge claude                           # full run
wikilens gap ./my-vault --judge none                             # dry-run (no API)
wikilens gap ./my-vault --judge claude --max-clusters 10         # budget cap
wikilens gap ./my-vault --judge claude --top-gaps-per-cluster 2  # fewer per cluster
```

`contradict` and `gap` both exit 0 when nothing found, 1 when findings are
reported. Set `ANTHROPIC_API_KEY` in your shell or in a `.env` file at the
repo root before running `--judge claude`.

## Benchmark

Four eval suites, all reproducible from a fresh clone.

**Retrieval** (P2): Hit@5 = 1.00 in all four modes on the 36-note synthetic vault. Latency p95: 37 ms (dense) to 1846 ms (rerank).

**Link audit** (P3): Precision = Recall = F1 = 1.00 on all four detector classes (16-note fixture, 19 planted defects).

**Contradiction finder** (P4): F1 = 0.82, retrieval recall = 0.90 on the 24-pair hand-labeled fixture. Wall clock 67.7s.

**Gap generator** (P5): Cluster-stage recall = 1.00, matcher-stage F1 = 0.65 on 10 gold gaps. All 10 gold gaps surfaced by some cluster.

See [`BENCHMARK.md`](./BENCHMARK.md) for full tables. Reproduce any suite:

```bash
# P5 gap generator
pip install -e '.[dev,judge]'
wikilens ingest fixtures/gaps_vault --db .wikilens_p5_eval/db
python scripts/eval_p5.py --judge claude
```

## Writing / research

Design decisions and methodology writeups are published as they happen. Index will live at [`/docs`](./docs/) once P2 is done.

## License

MIT — see [LICENSE](./LICENSE).

## Author

Built by [Boris Manzov](https://github.com/Universe8888). Feedback and ideas welcome in [Issues](https://github.com/Universe8888/wikilens/issues).
