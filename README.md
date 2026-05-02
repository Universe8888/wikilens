# wikilens

> An agentic intelligence layer for Markdown / Obsidian vaults.
> RAG + evaluated metacognitive agents, built in public.

**Status:** Alpha · P7 shipped (`v0.7.0`). `ingest`, `query`, `audit`, `contradict`, `gap`, and `answer` all work end-to-end on local Markdown vaults. [See benchmark →](./BENCHMARK.md)

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

Shipped: **P1 – P6** (RAG core, Link Auditor, Contradiction Finder, Gap Generator, Answer Generator, all with hand-labeled evals).

Next: **P7 — PyPI + installer polish**, then **P8 — Temporal Drift Detector**, **P9 — Unnamed Concept Detector**, **P10 — Epistemic Confidence Mapper**, **P11 — Obsidian plugin**, **P12 — v1.0 launch**.

Full phase list, launch hooks, and eval targets in [`ROADMAP.md`](./ROADMAP.md).

## Design principles

1. **No silent steps.** Every agent explains what it did and why.
2. **Reproducible evaluation.** `make benchmark` produces the numbers in `BENCHMARK.md`.
3. **No vendor lock.** Swappable embeddings, swappable LLMs, swappable vector stores.
4. **Fail loud.** Broken inputs are surfaced, never guessed.

## Install

```bash
pip install wikilens
```

Python 3.12+ is required. The first run of `ingest` or `query` downloads two
local models (~270 MB total, cached for all subsequent runs):
`BAAI/bge-small-en-v1.5` (embedder) and `BAAI/bge-reranker-base` (reranker).

For `contradict`, `gap`, and `answer` you also need a remote LLM key:

```bash
pip install 'wikilens[judge]'         # adds openai, anthropic, scikit-learn
export OPENAI_API_KEY=sk-...          # or ANTHROPIC_API_KEY for --judge claude
```

**From source** (dev / contributor install):

```bash
git clone https://github.com/Universe8888/wikilens.git
cd wikilens
pip install -e '.[dev]'
```

On Windows, if the `wikilens` command is not found after install, add the
Python Scripts directory to `PATH` (e.g. `%APPDATA%\Python\Python312\Scripts`)
or run `python -m wikilens.cli` while developing.

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
# Contradict — find conflicting chunk pairs.
pip install -e '.[judge]'
wikilens contradict ./my-vault --judge claude                    # full run
wikilens contradict ./my-vault --judge none                      # dry-run (no API)
wikilens contradict ./my-vault --judge claude --sample 20        # cap API calls

# Gap — find unanswered questions the vault implies but doesn't answer.
wikilens gap ./my-vault --judge claude                           # full run
wikilens gap ./my-vault --judge none                             # dry-run (no API)
wikilens gap ./my-vault --judge claude --max-clusters 10         # budget cap
wikilens gap ./my-vault --judge claude --top-gaps-per-cluster 2  # fewer per cluster

# Answer — for each gap, retrieve vault evidence and draft a note stub.
wikilens gap ./my-vault --judge openai --json > gaps.json        # generate gaps first
wikilens answer ./my-vault --gaps gaps.json --judge openai       # draft stubs to stdout
wikilens answer ./my-vault --gaps gaps.json --judge openai \
    --write --out ./stubs/                                       # write .md files
wikilens answer ./my-vault --gaps gaps.json --judge none         # dry-run (no API)
```

`contradict`, `gap`, and `answer` exit 0 when clean, 1 when findings / partial
coverage reported. `answer` exits 2 on bad input or file collisions when
`--write` is set. Set `OPENAI_API_KEY` (or `ANTHROPIC_API_KEY` for
`--judge claude`) in your shell or in a `.env` file at the repo root.

## Benchmark

Four eval suites, all reproducible from a fresh clone.

**Retrieval** (P2): Hit@5 = 1.00 in all four modes on the 36-note synthetic vault. Latency p95: 37 ms (dense) to 1846 ms (rerank).

**Link audit** (P3): Precision = Recall = F1 = 1.00 on all four detector classes (16-note fixture, 19 planted defects).

**Contradiction finder** (P4): F1 = 0.82, retrieval recall = 0.90 on the 24-pair hand-labeled fixture. Wall clock 67.7s.

**Gap generator** (P5): Cluster-stage recall = 1.00, matcher-stage F1 = 0.65 on 10 gold gaps. All 10 gold gaps surfaced by some cluster.

**Answer generator** (P6): Pass rate = 0.80 (8/10 drafts pass all 4 axes: faithfulness, coverage, attribution quality, stub structure). Attribution rate = 1.00 (automated). Wall clock 90s for 10 gaps.

See [`BENCHMARK.md`](./BENCHMARK.md) for full tables. Reproduce any suite:

```bash
# P6 answer generator
pip install -e '.[dev,judge]'
rm -rf .wikilens_p5_eval
wikilens ingest fixtures/gaps_vault --db .wikilens_p5_eval/db
python scripts/eval_p6.py --judge openai
```

Local checks:

```bash
make lint
make typecheck
make test
make benchmark
```

`make benchmark` uses no-API mock judges for P4-P6 by default. To reproduce
published LLM-judged numbers, run the individual eval scripts with
`--judge claude` or `--judge openai` after setting the relevant API key.

## Writing / research

Design decisions and methodology writeups are published as they happen. Index will live at [`/docs`](./docs/) once P2 is done.

## License

MIT — see [LICENSE](./LICENSE).

## Author

Built by [Boris Manzov](https://github.com/Universe8888). Feedback and ideas welcome in [Issues](https://github.com/Universe8888/wikilens/issues).
