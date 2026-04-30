# Benchmark

Honest numbers across the project's eval suites. Every run is reproducible from a fresh clone.

- **Retrieval** (`fixtures/sample_vault/` + `fixtures/eval/p2_queries.jsonl`):
  ```
  wikilens ingest fixtures/sample_vault && python scripts/eval_p2.py
  ```
- **Link audit** (`fixtures/audit_vault/` + `fixtures/eval/p3_ground_truth.json`):
  ```
  python scripts/eval_p3.py
  ```

Each harness **appends** a timestamped section below; prior runs are preserved so regressions are visible side-by-side.

## 2026-04-30 — P3 eval (cb88311)

- Vault: `fixtures/audit_vault` (16 notes).
- Findings: 19 across four defect classes.
- Detectors: pure functions over the in-memory link graph, no models.

| Class    | TP | FP | FN | Precision | Recall | F1   |
|----------|----|----|----|-----------|--------|------|
| broken   |  4 |  0 |  0 |      1.00 |   1.00 | 1.00 |
| one_way  |  8 |  0 |  0 |      1.00 |   1.00 | 1.00 |
| orphans  |  6 |  0 |  0 |      1.00 |   1.00 | 1.00 |
| shadowed |  1 |  0 |  0 |      1.00 |   1.00 | 1.00 |

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
