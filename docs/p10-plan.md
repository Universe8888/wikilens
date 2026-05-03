# P10 — Epistemic Confidence Mapper (SDD)

**Status:** Specification — HITL-approved 2026-05-03, awaiting implementation.
**Created:** 2026-05-03
**Preceded by:** P9 (Unnamed Concept Detector) — complete, tag `v0.9.0`.
**Target effort:** ~15–20h, part-time.

---

## Goal

`wikilens confidence <vault>` reads each note in a vault, extracts sentence-level
declarative claims, and classifies every claim on a five-level **epistemic scale**:

| Level | Label        | Signal in the text                                           |
|-------|--------------|--------------------------------------------------------------|
| 1     | speculation  | explicit hedge (“I think”, “maybe”, “I suspect”, “could be”) |
| 2     | conjecture   | stated flat, zero support                                    |
| 3     | inference    | reasoned from other vault claims (“because”, “given that”)   |
| 4     | attributed   | cited to a named external source                             |
| 5     | verified     | textbook-empirical, well-established                         |

The default output (markdown, or `--json`) reports claims **below a threshold**
(default `--threshold 2`, i.e. levels 1–2) — "claims that outrun their
evidence." Claims at level 3–5 are summarized in the header but not listed in
full. Exit codes match P3/P4/P5/P6/P8/P9: `0` clean / `1` findings / `2` bad
input.

Launch hook: *"I audited my own vault for epistemic debt. Here's what I
found."*

This is the first phase that:

- **Operates on individual sentences, not clusters or pairs.** Claim count
  scales linearly with vault size; cost control is per-claim, not per-cluster.
- **Uses an ordinal output label.** Unlike P4's binary contradiction verdict or
  P9's single-string concept proposal, the judge emits an integer 1–5 with
  known failure modes (center bias, adjacent-class collapse). Eval explicitly
  measures for this.
- **Reuses the P8 claim extractor unchanged.** `drift.extract_claims()` is the
  canonical sentence splitter in this codebase (G3-safe line-scanner frontmatter
  stripping, code-fence removal, `_MAX_NOTE_BYTES` guard). P10 imports it
  directly; does not re-implement.

## Pass/Fail criterion

`wikilens confidence fixtures/confidence_vault --judge openai`:

1. **Precision ≥ 0.70** on the binary **low-confidence class** (ground-truth
   `level ≤ 2`). Target is symmetric with P9 and one notch tighter than P8's
   0.80 — P10's labeling task is harder and more subjective, and the class
   imbalance is less extreme.
2. **Recall ≥ 0.70** on the same binary class.
3. **QWK (Quadratic Weighted Kappa) reported as a secondary metric** across the
   full 5-level ordinal. No hard target for v1; log it. **Flag if QWK < 0.30** —
   that's the early-warning signal that the LLM judge has collapsed the
   ordinal into 2–3 clusters (the literature's well-documented failure mode).
4. **5-class confusion matrix reported as a diagnostic.**
5. **Wall clock < 3 min** on the fixture with `--judge openai`. `--judge none`
   (mock) < 5s.
6. **Exit codes correct** — 0 when no low-confidence claims found, 1 when at
   least one, 2 on bad input / empty vault / missing API key with
   `--judge openai`.
7. **100% of existing tests (427) still green; new tests green.**
8. **Budgeted autonomy enforced:** `--sample`, `--only`, `--threshold`,
   `--min-confidence` respected; verified via unit test.

No "vibes" pass — numbers or it didn't ship. Bars set before eval runs.
Precision and recall are weighted equally because P10 is *surfacing* material
for human review, not making an irreversible call.

## Scope

### In

- New CLI subcommand `wikilens confidence <vault>`:
  - `--judge {none,openai,claude}` — backend (default: `openai`, per P5.4 memory).
  - `--model NAME` — judge model (default: `gpt-4o`).
  - `--threshold N` — report claims with `level ≤ N` (default: `2`; valid 1–5).
  - `--sample N` — cap total judge calls (smoke mode).
  - `--only NOTE` — restrict to a single note path (same semantics as P8).
  - `--min-confidence F` — drop verdicts whose self-reported confidence is
    below `F` (default: `0.0`, i.e. no filter). Guards against
    "confidently wrong in out-of-distribution settings."
  - `--json` — structured report instead of markdown.
  - `-v / --verbose` — per-note progress to stderr.
- Claim extractor: **reuse `drift.extract_claims()` verbatim.** Same scope
  rules (frontmatter / headings / code fences / tables excluded; list items and
  blockquotes included).
- Per-claim context pack: judge sees the claim sentence plus ±2 surrounding
  sentences from the same note (context window kept small; a long prefix is a
  token cost with marginal accuracy benefit, per research-phase findings).
- Judge interface: `ConfidenceJudge` Protocol, with `Mock` /
  `OpenAIConfidenceJudge` / `ClaudeConfidenceJudge` backends — 1:1 mirror of
  the P8/P9 `@runtime_checkable` Protocol pattern.
- Output: markdown (per-note sections, low-confidence claims listed with
  level, rationale, line span) + `--json` (schema-versioned).
- Eval fixture: `fixtures/confidence_vault/` — 15 public-domain hobbyist notes
  (~130 total sentences worth labeling). `fixtures/eval/p10_ground_truth.json`
  with per-claim levels, spans, rationales.
- Eval harness: `scripts/eval_p10.py` — copy-paste skeleton from `eval_p9.py`,
  augmented with QWK computation and 5-class confusion matrix. Appends to
  `BENCHMARK.md`.

### Out (deferred)

- **Atomic-proposition decomposition** (sub-sentence claims). Research phase
  flagged this as the standard in the FactScore/ClaimBuster literature but
  declared sentence-level the pragmatic v1 default; multi-clause sentences get
  a single level (the lowest of their constituents, by judge's discretion).
- **Vault-graph inference signals.** Level 3 ("inference") is judged by
  surface cues in the sentence itself (connectives, cross-refs). We do NOT
  walk outbound wikilinks to verify that the referenced note *actually*
  supports the inference. Future phase.
- **Per-claim remediation suggestions** ("add a citation here"). P6's answer
  generator can fill this role when paired with P10 output in a later
  pipeline; this phase does not cross that boundary.
- **Multi-judge ensemble.** One judge call per claim.

## Architecture

Strict P8 template. Three new modules, no inlining of formatters into `cli.py`
(P9's shortcut is explicitly avoided).

```
src/wikilens/
  confidence.py          # pipeline: extract → pack context → iterate judge
  confidence_judge.py    # Protocol + MockConfidenceJudge + OpenAI + Claude
  confidence_format.py   # format_markdown(report), format_json(report)
```

### Reused (imported, not copied)

- `drift.extract_claims(note_text)` — sentence splitter, frontmatter/fence
  stripping, G3-safe.
- `drift._MAX_NOTE_BYTES` — adversarial-input safety guard.
- `_env.load_dotenv_if_present()` — shared dotenv loader.
- `store.VaultStore` — LanceDB reader. P10 reads chunk metadata only for
  `source_rel` / note enumeration; does not use embeddings.
- XML sanitisation pattern from `drift_judge._sanitize_for_xml()` — prompt
  injection defense. Every user-supplied string interpolated into an
  XML-tagged prompt gets `<` / `>` → `&lt;` / `&gt;`.

### Judge interface

```python
@dataclass(frozen=True)
class ConfidenceVerdict:
    level: int           # 1..5
    rationale: str       # one sentence, judge's reasoning
    confidence: float    # 0.0..1.0, judge's self-reported certainty

@runtime_checkable
class ConfidenceJudge(Protocol):
    name: str
    def classify(self, claim: str, note_context: str) -> ConfidenceVerdict: ...
```

Each backend class follows the P8/P9 skeleton exactly:
- class attribute `name`;
- `__init__` calls `load_dotenv_if_present()`, checks API key → `OSError`,
  lazy-imports SDK → `ImportError`, stores `_client` / `_model` / `_max_tokens`,
  zeroes `self.calls` and `self.abstentions`;
- `_MAX_RETRIES = 2` (3 total attempts), JSON-only system prompt, "CRITICAL:"
  suffix on retry, returns a `_FALLBACK_VERDICT` (level `3`, confidence `0.0`)
  on exhaustion and increments `self.abstentions`;
- **Never raises from `classify`.**

### CLI handler

`_cmd_confidence` in `cli.py` follows `_cmd_drift` exactly (not `_cmd_concepts`
— it has a broad `try/except Exception` we do not want to copy):

1. Deferred imports inside the function.
2. Empty-vault guard → `stderr` + `return 2`.
3. Judge resolution block (`none` / `openai` / `claude`, catch
   `(OSError, ImportError)` → `return 2`).
4. Pipeline call.
5. Output branching on `args.json`.
6. Exit code from `len(low_confidence_claims) > 0 ? 1 : 0`.

## Evaluation

### Fixture: `fixtures/confidence_vault/`

**15 notes**, public-domain hobbyist topics (sanitization-clean by
construction). Proposed set (ordering arbitrary):

- `astronomy.md`, `sourdough-baking.md`, `chess-openings.md`,
  `photography-exposure.md`, `roman-history.md`, `knot-tying.md`,
  `birdwatching.md`, `guitar-tuning.md`, `bicycle-maintenance.md`,
  `coffee-brewing.md`, `woodworking-joints.md`, `meditation-practice.md`,
  `rust-ownership.md`, `geology-plate-tectonics.md`, `home-gardening.md`.

Topic mix is deliberately broad: claims of different kinds live in different
disciplines (attributed claims are natural in history + rust docs; inference
chains in coffee + bicycle; speculation in birdwatching + meditation;
textbook-verified in astronomy + geology).

### Ground truth: `fixtures/eval/p10_ground_truth.json`

~130 labeled claims across the 15 notes. Target distribution:

| Level          | Target share | Rationale                                        |
|----------------|--------------|--------------------------------------------------|
| 1 speculation  | 15 % (~20)   | enough TPs to stabilize P/R at the 0.70 bar      |
| 2 conjecture   | 15 % (~20)   | symmetric with level 1                           |
| 3 inference    | 35 % (~45)   | majority class — prevents "always predict low"   |
| 4 attributed   | 25 % (~33)   | natural in history/programming notes             |
| 5 verified     | 10 % (~13)   | bounded — most claims aren't textbook-empirical  |

Low-confidence class (levels 1 + 2) = ~30 % ≈ ~40 claims. This gives at least
10 TPs needed for precision to stabilize near 0.70.

Schema (per-entry):

```json
{
  "id": "C001",
  "note": "sourdough-baking.md",
  "claim_id_sha256": "a3f1...e7",
  "claim_text": "I think a wetter starter ferments faster in my kitchen.",
  "span": {"start": 412, "end": 468},
  "level": 1,
  "rationale": "Explicit hedge 'I think' + personal qualifier 'my kitchen'."
}
```

`claim_id_sha256` is stable against whitespace normalization (matches the
security-hardening pattern from May 2026's SHA-256 chunk IDs).

### Matcher (predicted ↔ gold)

Two-stage, deterministic, no embeddings in the happy path:

1. **Primary:** note match + char-span Jaccard ≥ 0.50 on `(start, end)`
   offsets.
2. **Fallback:** normalized-text exact match (lowercase, collapse whitespace,
   strip trailing punctuation) within the same note. Covers tokenization drift
   between extractor versions.

No embedding fallback in v1. Embedding-based matching turns the P/R number
into noise if the corpus or threshold drifts.

### Metrics

- **Primary:** Precision / Recall / F1 on binary `level ≤ 2`. Targets:
  P ≥ 0.70, R ≥ 0.70.
- **Secondary:** QWK across the 5-level ordinal. Report with no target;
  hand-flag in the decisions doc if < 0.30.
- **Diagnostic:** 5-class confusion matrix (rows = gold, cols = predicted).
- **Cost:** total judge calls + abstentions, wall clock, mean time/claim.

### Edge cases (extractor scope)

Identical to P8 behaviour. Exclusions and inclusions, stated once for the
record:

| Case                       | Behaviour                                                    |
|----------------------------|--------------------------------------------------------------|
| YAML frontmatter           | excluded                                                     |
| Markdown headings          | excluded                                                     |
| Fenced code blocks         | excluded                                                     |
| Inline code spans          | kept as part of the sentence; never the sole content         |
| Tables                     | excluded (rows = structural, not prose)                      |
| Blockquotes (`>`)          | included, treated as the author's endorsement                |
| List items                 | included (each bullet = one claim if declarative)            |
| Multi-sentence claims      | split on `.?!` — one sentence = one claim                    |
| Questions / imperatives    | excluded (not declarative)                                   |
| `_MAX_NOTE_BYTES` exceeded | truncated; warning emitted (reuse P8 guard)                  |

## Step plan

One in-progress task at a time; each step ends with a HITL checkpoint before
the next begins.

| # | Step                                                                  | Exit gate                                 |
|---|-----------------------------------------------------------------------|-------------------------------------------|
| 1 | `docs/p10-plan.md` (this SDD, tracked)                                | user approves                             |
| 2 | `fixtures/confidence_vault/` — 15 public-domain notes                 | sanitization gate clean                   |
| 3 | `fixtures/eval/p10_ground_truth.json` — ~130 labeled claims           | manual review, distribution check         |
| 4 | `confidence.py` skeleton + mock-only pipeline                         | unit tests green                          |
| 5 | `confidence_judge.py` (Mock + OpenAI + Claude)                        | unit tests green, no live API calls       |
| 6 | `confidence_format.py` (markdown + JSON)                              | unit tests green                          |
| 7 | Wire `_cmd_confidence` into `cli.py`                                  | CLI smoke test with `--judge none`        |
| 8 | `scripts/eval_p10.py` (P/R/F1 + QWK + confusion matrix)               | mock-judge dry run clean                  |
| 9 | Eval run with OpenAI → P ≥ 0.70, R ≥ 0.70                             | `BENCHMARK.md` updated                    |
| 10 | `ruff`, `mypy`, full test suite green                                | 427 + new tests pass                      |
| 11 | Version bump, CHANGELOG, HANDOFF (public + `.local/`), sanitization  | diff review                               |
| 12 | Tag `v0.10.0` locally — **do not push without explicit approval**    | user decision                             |

## Design principles carried from P1–P9

1. **No silent steps.** Every claim reported carries the judge's rationale.
2. **Reproducible evaluation.** Hand-labeled fixture, fixed metric, single
   number per run. QWK reported as guardrail, not target.
3. **No vendor lock.** `--judge none/openai/claude` symmetric with P8/P9.
4. **Fail loud.** Broken inputs are surfaced, never guessed.
5. **Budgeted autonomy.** `--sample`, `--only`, `--threshold`,
   `--min-confidence` all cap blast radius of a bad vault or runaway cost.

## Open questions settled at SDD approval (2026-05-03)

- **Fixture scale:** approved (a) 15 notes / ~130 claims.
- **Secondary metric:** approved QWK reporting (no hard target).
- **Default judge:** `openai/gpt-4o` confirmed.
- **Release posture:** tag locally after eval passes; public push requires
  separate explicit approval.
