# Roadmap

> Where `wikilens` is going. Every phase ships measurable capability and lands a launch artifact (writeup, demo, or distribution surface) so the project accumulates visible progress rather than vanishing into a long v1 march.

**Current tip:** P5 shipped (`v0.5.0`). P6 in progress.

---

## Shipped

### P1 — Bootstrap · `v0.1.0`
Repo, manifesto, CLI scaffold, test harness.

### P2 — RAG core · `v0.2.0`
Markdown ingestion, hybrid retrieval (dense + BM25 + RRF + rerank), `query` CLI. **Hit@5 = 1.00** in every mode on the 36-note vault; p95 rerank latency 1846ms.

### P3 — Link Auditor · `v0.3.0`
Broken / one-way / orphan / shadowed detectors. **P = R = F1 = 1.00** on every class (19 planted defects on a 16-note fixture). Pure-function graph, no models in the hot path. Exit code 0/1/2 — usable as a CI gate.

### P4 — Contradiction Finder · `v0.4.0`
Retrieval-based pair generation (O(n·k)), pluggable LLM judge (Claude / OpenAI), factual + temporal scope. **F1 = 0.82**, retrieval recall = 0.90 on 24 hand-labeled pairs.

### P5 — Gap Generator · `v0.5.0`
K-means on chunk embeddings → per-cluster LLM generation → pinned-rubric matcher eval. **Cluster recall = 1.00**, matcher F1 = 0.65 on 10 gold gaps. Budgeted autonomy via `--min-cluster-size` / `--max-clusters` / `--sample`.

---

## In progress

### P6 — Answer Generator · `v0.6.0`
Close the gap loop. Given `wikilens gap` output, retrieve supporting evidence and draft note stubs that actually answer the identified questions. Stubs carry proof-carrying citations: every factual sentence carries a `[^N]` footnote that resolves to a retrieved `chunk_id`.

- **Status:** P6.1 (plumbing) + P6.2 (cognitive kernel + prompt hardening) complete. P6.3 (gold answer sketches) next.
- **Eval:** 4-axis LLM-judge rubric (faithfulness / coverage / attribution / structure) + automated attribution-rate check. Target: faithfulness ≥ 0.80.
- **Launch hook:** *"My vault told me what was missing. Then it wrote the first draft."*

---

## Next

### P7 — PyPI + Installer Polish · `v0.7.0`
`pip install wikilens` from PyPI. Docs site (probably MkDocs Material). Quickstart that works in under 2 minutes on a fresh machine. **This is the gate for any public launch — no launch before this ships.** Converts the project from "clone + install-from-source" to "real tool someone can try without reading the README twice."

### P8 — Temporal Drift Detector · `v0.8.0`
Walk the `git log` of the vault. Surface notes where thinking has shifted semantically over time — not typo-level diffs, genuine belief changes.

- **Eval:** Precision on a hand-labeled drift-vs-revision fixture (planted semantic changes + planted surface-only edits in the same vault).
- **Launch hook:** *"I ran an AI over my git history. It found 12 beliefs I quietly abandoned."*

### P9 — Unnamed Concept Detector · `v0.9.0`
Find clusters of notes that paraphrase the same idea without ever naming it. Propose the missing term.

- **Eval:** Expert-rated "yes, I should have named this" on proposed concepts across 5 real-vault runs.
- **Launch hook:** *"My second brain was circling a concept 18 times without ever naming it. Here's what it found."*

### P10 — Epistemic Confidence Mapper · `v0.10.0`
Classify claims across notes on the **hypothesis → verified fact** spectrum. Flag conclusions that outrun their evidence.

- **Eval:** Precision / recall on a hand-labeled confidence fixture (each claim tagged on a 5-point scale).
- **Launch hook:** *"I audited my own vault for epistemic debt. Here's what I found."*

### P11 — Obsidian Plugin · `v0.11.0`
Thin wrapper calling the `wikilens` CLI, displays findings in a side pane. Submit to the Obsidian community plugin directory.

- **Why:** Passive discovery via the plugin marketplace — ongoing traffic, not a one-shot launch.
- **Scope:** Plugin is a view layer, not a reimplementation. All reasoning stays in the CLI so the plugin benefits from every future agent automatically.

### P12 — v1.0 Launch
Product Hunt + Show HN + `r/ObsidianMD` simultaneously. **Requires P6 – P11 all shipped.** Bundle all benchmark numbers into a single writeup: *"Here's what `wikilens` caught on 5 real vaults."* One post, five agents, real numbers.

---

## Design principles carried through every phase

1. **No silent steps.** Every agent explains what it did and why.
2. **Reproducible evaluation.** A hand-labeled fixture and a reported number per agent. No "it seems to work."
3. **No vendor lock.** Swappable embeddings, swappable LLMs, swappable vector stores.
4. **Fail loud.** Broken inputs are surfaced, never guessed.
5. **Budgeted autonomy.** Every LLM-calling phase ships with layered caps (`--sample`, `--min-*`, `--max-*`) so runs never blow the cost budget.

---

## What this roadmap is NOT

- **Not a hosted SaaS.** v1 is local-first. Remote LLM calls are opt-in and gated behind API-key presence.
- **Not a note editor.** Bring your own — Obsidian, VS Code, plain text. `wikilens` reads your vault; it doesn't own it.
- **Not a chatbot.** "Chat with your notes" is table stakes and not differentiated. Every phase above is a measurable agent that produces artifacts you can verify.
