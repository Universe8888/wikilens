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
- **Contradiction finder** (`fixtures/contradictions_vault/` + `fixtures/eval/p4_ground_truth.json`):
  ```
  wikilens ingest fixtures/contradictions_vault --db .wikilens_p4_eval/db
  python scripts/eval_p4.py --judge claude
  ```

- **Gap generator** (`fixtures/gaps_vault/` + `fixtures/eval/p5_ground_truth.json`):
  ```
  wikilens ingest fixtures/gaps_vault --db .wikilens_p5_eval/db
  python scripts/eval_p5.py --judge claude
  ```

Each harness **appends** a timestamped section below; prior runs are preserved so regressions are visible side-by-side.

## 2026-05-01 00:20:50 — P5 eval (77148c2)

- Vault: `C:/Projects2026/wikilens/fixtures/gaps_vault` (57 chunks, 7 clusters).
- Generator: `claude`. Gap proposals: 21. Gold gaps: 10.
- Matcher: `claude` (threshold ≥ 4/5).
- Wall clock: 453.5s.

Cluster-stage recall: 10/10 = 1.00

| Stage        | TP | FP | FN | Precision | Recall | F1   |
|--------------|----|----|----|-----------|--------|------|
| matcher      | 10 | 11 |  0 |      0.48 |   1.00 | 0.65 |

## 2026-05-01 00:03:13 — P5 eval (77148c2)

- Vault: `C:/Projects2026/wikilens/fixtures/gaps_vault` (57 chunks, 7 clusters).
- Generator: `claude`. Gap proposals: 21. Gold gaps: 4.
- Matcher: `claude` (threshold ≥ 4/5).
- Wall clock: 217.9s.

Cluster-stage recall: 4/4 = 1.00

| Stage        | TP | FP | FN | Precision | Recall | F1   |
|--------------|----|----|----|-----------|--------|------|
| matcher      |  4 | 17 |  0 |      0.19 |   1.00 | 0.32 |

## 2026-04-30 23:59:15 — P5 eval (77148c2)

- Vault: `C:/Projects2026/wikilens/fixtures/gaps_vault` (57 chunks, 7 clusters).
- Generator: `mock`. Gap proposals: 7. Gold gaps: 4.
- Matcher: `substring` (threshold ≥ 4/5).
- Wall clock: 2.0s.

Cluster-stage recall: 0/4 = 0.00

| Stage        | TP | FP | FN | Precision | Recall | F1   |
|--------------|----|----|----|-----------|--------|------|
| matcher      |  0 |  7 |  4 |      0.00 |   0.00 | 0.00 |

## 2026-04-30 22:51:09 — P4 eval (1c8f318)

- Vault: `C:/Projects2026/wikilens/fixtures/contradictions_vault` (48 chunks, 202 candidate pairs).
- Judge: `claude`. Labeled pairs judged: 24.
- Wall clock: 67.7s.

| Class    | TP | FP | FN | Precision | Recall | F1   |
|----------|----|----|----|-----------|--------|------|
| factual  |  8 |  2 |  1 |      0.80 |   0.89 | 0.84 |
| temporal |  1 |  0 |  1 |      1.00 |   0.50 | 0.67 |
| overall  |  9 |  2 |  2 |      0.82 |   0.82 | 0.82 |

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
