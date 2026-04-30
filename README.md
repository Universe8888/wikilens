# wikilens

> An agentic intelligence layer for Markdown / Obsidian vaults.
> RAG + evaluated metacognitive agents, built in public.

**Status:** Pre-alpha · scaffolding phase (P1). Nothing works yet. [Follow along →](#roadmap)

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
| P1 — Bootstrap | Repo, scaffold, manifesto | **In progress** |
| P2 — RAG core | Markdown ingestion + local vector store + `query` CLI | — |
| P3 — Link Auditor agent | Detect broken wikilinks, orphan notes, one-way links | — |
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

Not published yet. When P2 lands:

```bash
pip install wikilens
wikilens ingest ./my-vault
wikilens query "what do I know about X?"
```

## Writing / research

Design decisions and methodology writeups are published as they happen. Index will live at [`/docs`](./docs/) once P2 is done.

## License

MIT — see [LICENSE](./LICENSE).

## Author

Built by [Boris Manzov](https://github.com/Universe8888). Feedback and ideas welcome in [Issues](https://github.com/Universe8888/wikilens/issues).
