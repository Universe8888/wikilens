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

- **Answer generator** (`fixtures/gaps_vault/` + `fixtures/eval/p6_answer_sketches.json`):
  ```
  wikilens ingest fixtures/gaps_vault --db .wikilens_p5_eval/db
  python scripts/eval_p6.py --judge openai
  ```

Each harness **appends** a timestamped section below; prior runs are preserved so regressions are visible side-by-side.

## 2026-05-01 18:27:23 — P6 eval (0eab57a)

- Vault: `C:/Projects2026/wikilens/fixtures/gaps_vault` (10 gaps evaluated).
- Drafter: `openai`. Judge: `openai`.
- Judged: 10. Skipped: 0.
- Wall clock: 90.3s.

Pass rate (all 4 axes >= 4): 8/10 = 0.80
Skip / external-research rate: 0/10 = 0.00
Attribution rate (automated): 1.00  (target >= 0.9)

| gap_id | faith | cov | attr_q | struct | pass |
|--------|-------|-----|--------|--------|------|
| calvin-cycle                        | 4 | 4 | 4 | 5 | ✓ |
| async-await-python-web              | 4 | 4 | 5 | 5 | ✓ |
| peace-of-westphalia-terms           | 5 | 4 | 5 | 5 | ✓ |
| photosystem-mechanisms              | 5 | 4 | 5 | 5 | ✓ |
| spanish-dutch-1648                  | 5 | 3 | 4 | 5 | ✗ |
| cast-iron-seasoning                 | 4 | 2 | 4 | 5 | ✗ |
| reducing-sugars-definition          | 5 | 4 | 5 | 5 | ✓ |
| django-database-migrations          | 5 | 5 | 5 | 5 | ✓ |
| wsgi-vs-asgi                        | 4 | 4 | 4 | 5 | ✓ |
| fond-and-deglazing                  | 5 | 4 | 5 | 5 | ✓ |

| **mean** | 4.6 | 3.8 | 4.6 | 5.0 | — |

## 2026-05-01 16:53:42 — P6 eval (0eab57a)

- Vault: `C:/Projects2026/wikilens/fixtures/gaps_vault` (10 gaps evaluated).
- Drafter: `openai`. Judge: `openai`.
- Judged: 10. Skipped: 0.
- Wall clock: 93.1s.

Pass rate (all 4 axes >= 4): 4/10 = 0.40
Skip / external-research rate: 0/10 = 0.00
Attribution rate (automated): 0.90  (target >= 0.9)

| gap_id | faith | cov | attr_q | struct | pass |
|--------|-------|-----|--------|--------|------|
| calvin-cycle                        | 5 | 4 | 5 | 5 | ✓ |
| async-await-python-web              | 4 | 5 | 4 | 5 | ✓ |
| peace-of-westphalia-terms           | 4 | 3 | 4 | 5 | ✗ |
| photosystem-mechanisms              | 5 | 5 | 5 | 5 | ✓ |
| spanish-dutch-1648                  | 5 | 3 | 5 | 5 | ✗ |
| cast-iron-seasoning                 | 2 | 3 | 3 | 5 | ✗ |
| reducing-sugars-definition          | 5 | 4 | 5 | 5 | ✓ |
| django-database-migrations          | 5 | 4 | 1 | 5 | ✗ |
| wsgi-vs-asgi                        | 3 | 4 | 3 | 5 | ✗ |
| fond-and-deglazing                  | 4 | 4 | 3 | 5 | ✗ |

| **mean** | 4.2 | 3.9 | 3.8 | 5.0 | — |

## 2026-05-01 16:50:52 — P6 eval (0eab57a)

- Vault: `C:/Projects2026/wikilens/fixtures/gaps_vault` (10 gaps evaluated).
- Drafter: `openai`. Judge: `openai`.
- Judged: 10. Skipped: 0.
- Wall clock: 105.7s.

Pass rate (all 4 axes >= 4): 4/10 = 0.40
Skip / external-research rate: 0/10 = 0.00
Attribution rate (automated): 0.90  (target >= 0.9)

| gap_id | faith | cov | attr_q | struct | pass |
|--------|-------|-----|--------|--------|------|
| calvin-cycle                        | 4 | 3 | 4 | 5 | ✗ |
| async-await-python-web              | 4 | 3 | 4 | 5 | ✗ |
| peace-of-westphalia-terms           | 5 | 4 | 5 | 5 | ✓ |
| photosystem-mechanisms              | 3 | 3 | 3 | 5 | ✗ |
| spanish-dutch-1648                  | 4 | 5 | 4 | 5 | ✓ |
| cast-iron-seasoning                 | 3 | 1 | 3 | 5 | ✗ |
| reducing-sugars-definition          | 5 | 4 | 5 | 5 | ✓ |
| django-database-migrations          | 5 | 3 | 3 | 5 | ✗ |
| wsgi-vs-asgi                        | 4 | 4 | 3 | 5 | ✗ |
| fond-and-deglazing                  | 4 | 5 | 5 | 5 | ✓ |

| **mean** | 4.1 | 3.5 | 3.9 | 5.0 | — |

## 2026-05-01 16:31:30 — P6 eval (0eab57a)

- Vault: `C:/Projects2026/wikilens/fixtures/gaps_vault` (10 gaps evaluated).
- Drafter: `openai`. Judge: `openai`.
- Judged: 10. Skipped: 0.
- Wall clock: 168.4s.

Pass rate (all 4 axes >= 4): 1/10 = 0.10
Skip / external-research rate: 0/10 = 0.00
Attribution rate (automated): 0.90  (target >= 0.9)

| gap_id | faith | cov | attr_q | struct | pass |
|--------|-------|-----|--------|--------|------|
| calvin-cycle                        | 5 | 3 | 4 | 5 | ✗ |
| async-await-python-web              | 4 | 4 | 4 | 5 | ✓ |
| peace-of-westphalia-terms           | 4 | 2 | 3 | 5 | ✗ |
| photosystem-mechanisms              | 3 | 3 | 3 | 5 | ✗ |
| spanish-dutch-1648                  | 5 | 2 | 4 | 5 | ✗ |
| cast-iron-seasoning                 | 2 | 2 | 3 | 5 | ✗ |
| reducing-sugars-definition          | 5 | 3 | 5 | 5 | ✗ |
| django-database-migrations          | 1 | 1 | 1 | 5 | ✗ |
| wsgi-vs-asgi                        | 4 | 4 | 3 | 5 | ✗ |
| fond-and-deglazing                  | 4 | 4 | 3 | 5 | ✗ |

| **mean** | 3.7 | 2.8 | 3.3 | 5.0 | — |

## 2026-05-01 16:22:40 — P6 eval (f27fee4)

- Vault: `C:/Projects2026/wikilens/fixtures/gaps_vault` (10 gaps evaluated).
- Drafter: `mock`. Judge: `mock`.
- Judged: 10. Skipped: 0.
- Wall clock: 17.6s.

Pass rate (all 4 axes >= 4): 10/10 = 1.00
Skip / external-research rate: 0/10 = 0.00
Attribution rate (automated): 1.00  (target >= 0.9)

| gap_id | faith | cov | attr_q | struct | pass |
|--------|-------|-----|--------|--------|------|
| calvin-cycle                        | 4 | 4 | 4 | 4 | ✓ |
| async-await-python-web              | 4 | 4 | 4 | 4 | ✓ |
| peace-of-westphalia-terms           | 4 | 4 | 4 | 4 | ✓ |
| photosystem-mechanisms              | 4 | 4 | 4 | 4 | ✓ |
| spanish-dutch-1648                  | 4 | 4 | 4 | 4 | ✓ |
| cast-iron-seasoning                 | 4 | 4 | 4 | 4 | ✓ |
| reducing-sugars-definition          | 4 | 4 | 4 | 4 | ✓ |
| django-database-migrations          | 4 | 4 | 4 | 4 | ✓ |
| wsgi-vs-asgi                        | 4 | 4 | 4 | 4 | ✓ |
| fond-and-deglazing                  | 4 | 4 | 4 | 4 | ✓ |

| **mean** | 4.0 | 4.0 | 4.0 | 4.0 | — |

## 2026-05-01 16:21:00 — P6 eval (f27fee4)

- Vault: `C:/Projects2026/wikilens/fixtures/gaps_vault` (16 gaps evaluated).
- Drafter: `mock`. Judge: `mock`.
- Judged: 0. Skipped: 16.
- Wall clock: 25.8s.

No drafts judged.

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

## 2026-05-03 13:02:51 — P10 eval

- Vault: `fixtures/confidence_vault` (249 claims classified).
- Judge: `none/gpt-4o`. Threshold: 2. Sample: all.
- Judge calls: 249. Abstentions: 0.
- Wall clock: 0.1s.

| Metric | Value | Target |
|--------|-------|--------|
| TP | 43 | — |
| FP | 7 | — |
| FN | 38 | — |
| Precision | 0.86 | >= 0.70 |
| Recall | 0.53 | >= 0.70 |
| F1 | 0.66 | — |
| QWK (ordinal, 5-class) | 0.000 | report only (flag if < 0.30) |

## 2026-05-03 13:36:40 — P10 eval

- Vault: `fixtures/confidence_vault` (249 claims classified).
- Judge: `openai/gpt-4o`. Threshold: 2. Sample: all.
- Judge calls: 249. Abstentions: 233.
- Wall clock: 627.5s.

| Metric | Value | Target |
|--------|-------|--------|
| TP | 8 | — |
| FP | 2 | — |
| FN | 73 | — |
| Precision | 0.80 | >= 0.70 |
| Recall | 0.10 | >= 0.70 |
| F1 | 0.18 | — |
| QWK (ordinal, 5-class) | 0.714 | report only (flag if < 0.30) |

## 2026-05-03 13:39:29 — P10 eval

- Vault: `fixtures/confidence_vault` (249 claims classified).
- Judge: `none/gpt-4o`. Threshold: 2. Sample: all.
- Judge calls: 249. Abstentions: 0.
- Wall clock: 0.1s.

| Metric | Value | Target |
|--------|-------|--------|
| TP | 43 | — |
| FP | 12 | — |
| FN | 38 | — |
| Precision | 0.78 | >= 0.70 |
| Recall | 0.53 | >= 0.70 |
| F1 | 0.63 | — |
| QWK (ordinal, 5-class) | 0.565 | report only (flag if < 0.30) |

## 2026-05-03 13:49:45 — P10 eval

- Vault: `fixtures/confidence_vault` (249 claims classified).
- Judge: `openai/gpt-4o`. Threshold: 2. Sample: all.
- Judge calls: 249. Abstentions: 229.
- Wall clock: 607.5s.

| Metric | Value | Target |
|--------|-------|--------|
| TP | 5 | — |
| FP | 6 | — |
| FN | 76 | — |
| Precision | 0.45 | >= 0.70 |
| Recall | 0.06 | >= 0.70 |
| F1 | 0.11 | — |
| QWK (ordinal, 5-class) | 0.102 | report only (flag if < 0.30) |

## 2026-05-03 14:14:04 — P10 eval

- Vault: `fixtures/confidence_vault` (249 claims classified).
- Judge: `openai/gpt-4o`. Threshold: 2. Sample: all.
- Judge calls: 249. Abstentions: 228.
- Wall clock: 676.5s.

| Metric | Value | Target |
|--------|-------|--------|
| TP | 10 | — |
| FP | 3 | — |
| FN | 71 | — |
| Precision | 0.77 | >= 0.70 |
| Recall | 0.12 | >= 0.70 |
| F1 | 0.21 | — |
| QWK (ordinal, 5-class) | 0.172 | report only (flag if < 0.30) |

## 2026-05-03 14:28:15 — P10 eval

- Vault: `fixtures/confidence_vault` (249 claims classified).
- Judge: `none/gpt-4o`. Threshold: 2. Sample: all.
- Judge calls: 249. Abstentions: 0.
- Wall clock: 0.1s.

| Metric | Value | Target |
|--------|-------|--------|
| TP | 49 | — |
| FP | 6 | — |
| FN | 32 | — |
| Precision | 0.89 | >= 0.70 |
| Recall | 0.60 | >= 0.70 |
| F1 | 0.72 | — |
| QWK (ordinal, 5-class) | 0.571 | report only (flag if < 0.30) |

## 2026-05-03 14:28:19 — P10 eval

- Vault: `fixtures/confidence_vault` (249 claims classified).
- Judge: `none/gpt-4o`. Threshold: 2. Sample: all.
- Judge calls: 249. Abstentions: 0.
- Wall clock: 0.1s.

| Metric | Value | Target |
|--------|-------|--------|
| TP | 49 | — |
| FP | 6 | — |
| FN | 32 | — |
| Precision | 0.89 | >= 0.70 |
| Recall | 0.60 | >= 0.70 |
| F1 | 0.72 | — |
| QWK (ordinal, 5-class) | 0.571 | report only (flag if < 0.30) |

## 2026-05-03 14:40:52 — P10 eval

- Vault: `fixtures/confidence_vault` (249 claims classified).
- Judge: `openai/gpt-4o`. Threshold: 2. Sample: all.
- Judge calls: 249. Abstentions: 230.
- Wall clock: 728.2s.

| Metric | Value | Target |
|--------|-------|--------|
| TP | 4 | — |
| FP | 5 | — |
| FN | 77 | — |
| Precision | 0.44 | >= 0.70 |
| Recall | 0.05 | >= 0.70 |
| F1 | 0.09 | — |
| QWK (ordinal, 5-class) | 0.091 | report only (flag if < 0.30) |

## 2026-05-03 14:50:17 — P10 eval

- Vault: `fixtures/confidence_vault` (249 claims classified).
- Judge: `none/gpt-4o`. Threshold: 2. Sample: all.
- Judge calls: 249. Abstentions: 0.
- Wall clock: 0.1s.

| Metric | Value | Target |
|--------|-------|--------|
| TP | 49 | — |
| FP | 6 | — |
| FN | 32 | — |
| Precision | 0.89 | >= 0.70 |
| Recall | 0.60 | >= 0.70 |
| F1 | 0.72 | — |
| QWK (ordinal, 5-class) | 0.571 | report only (flag if < 0.30) |

## 2026-05-03 14:55:43 — P10 eval

- Vault: `fixtures/confidence_vault` (249 claims classified).
- Judge: `openai/gpt-4o`. Threshold: 2. Sample: all.
- Judge calls: 249. Abstentions: 0.
- Wall clock: 217.2s.

| Metric | Value | Target |
|--------|-------|--------|
| TP | 76 | — |
| FP | 65 | — |
| FN | 5 | — |
| Precision | 0.54 | >= 0.70 |
| Recall | 0.94 | >= 0.70 |
| F1 | 0.68 | — |
| QWK (ordinal, 5-class) | 0.858 | report only (flag if < 0.30) |

## 2026-05-03 14:59:45 — P10 eval

- Vault: `fixtures/confidence_vault` (249 claims classified).
- Judge: `openai/gpt-4o`. Threshold: 2. Sample: all.
- Judge calls: 249. Abstentions: 0.
- Wall clock: 217.1s.

| Metric | Value | Target |
|--------|-------|--------|
| TP | 76 | — |
| FP | 60 | — |
| FN | 5 | — |
| Precision | 0.56 | >= 0.70 |
| Recall | 0.94 | >= 0.70 |
| F1 | 0.70 | — |
| QWK (ordinal, 5-class) | 0.883 | report only (flag if < 0.30) |

## 2026-05-03 15:05:56 — P10 eval

- Vault: `fixtures/confidence_vault` (249 claims classified).
- Judge: `none/gpt-4o`. Threshold: 2. Sample: all.
- Judge calls: 249. Abstentions: 0.
- Wall clock: 0.1s.

| Metric | Value | Target |
|--------|-------|--------|
| TP | 49 | — |
| FP | 6 | — |
| FN | 32 | — |
| Precision | 0.89 | >= 0.70 |
| Recall | 0.60 | >= 0.70 |
| F1 | 0.72 | — |
| QWK (ordinal, 5-class) | 0.571 | report only (flag if < 0.30) |

## 2026-05-03 15:10:15 — P10 eval

- Vault: `fixtures/confidence_vault` (249 claims classified).
- Judge: `openai/gpt-4o`. Threshold: 2. Sample: all.
- Judge calls: 249. Abstentions: 0.
- Wall clock: 255.7s.

| Metric | Value | Target |
|--------|-------|--------|
| TP | 71 | — |
| FP | 7 | — |
| FN | 10 | — |
| Precision | 0.91 | >= 0.70 |
| Recall | 0.88 | >= 0.70 |
| F1 | 0.89 | — |
| QWK (ordinal, 5-class) | 0.881 | report only (flag if < 0.30) |
