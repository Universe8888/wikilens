# Benchmark

Honest numbers on the synthetic `fixtures/sample_vault/` corpus. Every run is reproducible from a fresh clone: `wikilens ingest fixtures/sample_vault && python scripts/eval_p2.py`.

## 2026-04-30 18:47:38 — P2 eval (a289d2c)

- Corpus: 152 chunks across the sample vault.
- Eval: 20 hand-written queries, mixed easy/medium/hard.
- Hardware: developer laptop, CPU-only (no GPU).

| Mode | Hit@5 | Recall@5 | Easy | Medium | Hard | p50 (ms) | p95 (ms) | mean (ms) |
|------|-------|----------|------|--------|------|----------|----------|-----------|
| `dense` | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 34 | 37 | 34 |
| `bm25` | 1.00 | 0.97 | 1.00 | 1.00 | 1.00 | 6 | 7 | 6 |
| `hybrid` | 1.00 | 0.97 | 1.00 | 1.00 | 1.00 | 58 | 65 | 58 |
| `rerank` | 1.00 | 0.97 | 1.00 | 1.00 | 1.00 | 1574 | 1846 | 1584 |

Eval set: 20 queries.
