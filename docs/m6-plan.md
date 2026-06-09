# M6 — ThreadPool Concurrency + Backoff (SDD Plan)

> **Status:** ✅ DONE (2026-06-09). Shipped across 8 commits `0e53867`..`0385af8`.
> **Author:** Agentic Engineering Protocol session, 2026-06-09
> **Tip at planning:** `8a4cdd2` (M5 shipped). 576 tests pass, 84.67% cov, lint+mypy clean.
>
> **Delivered (vs plan):** Phase 1 thread-safe `CostContext` (reserve-then-settle).
> Phase 2 `retry.py` backoff. Phase 3 `executor.py` `parallel_map`. Phase 4 wired all
> 6 commands (+ thread-safe `VerdictCache` — a prerequisite the original plan missed).
> Phase 5 docs/changelog/memory. Deviations from plan: (a) determinism proven by
> in-test `workers=1`==`workers=8` identity with content-deterministic judges, not
> on-disk golden files (cleaner, matches repo's mock style); (b) the "call-count bug"
> in the plan was verified user-invisible (footer reads `cost_ctx.calls`, already
> correct) so no behavior change was needed there; (c) `--max-pairs` was already
> resolved in M5 (`--sample` is the cap).

---

## Source of Truth

1. **Locked refactor sequence** (`memory/project_v2_architecture_decisions.md`): M6 = "ThreadPool
   concurrency + backoff (L)". Owner decisions that bind M6:
   - **Decision 3 — cost-sensitive + interactive** → M6 uses `ThreadPoolExecutor`, **NOT** the Batch API.
   - Cost-guard caps stay ON by default; concurrency must not let parallel calls race past the cap.
2. **M6 scout report** (this session, verified on disk): 6 serial LLM loops, the shared helper signature,
   and the budget-gate race. Cited inline below.
3. **M5 residuals** (this session, spot-checked on disk) folded in per owner choice "M6 + fold in M5 fixes".

---

## Boundaries

### In scope
- Parallelize the 6 serial LLM loops (contradict, gap, drift, concepts, confidence, answer) with a
  bounded `concurrent.futures.ThreadPoolExecutor`.
- Make `CostContext` (`cost.py`) **thread-safe** so the budget cap holds under concurrency.
- Add **exponential backoff with jitter** + 429/rate-limit/transient-error retry to the networked backends
  (currently retries are immediate and only on malformed JSON — no backoff, no rate-limit handling).
- Preserve current **output ordering** for order-sensitive commands (drift, concepts, confidence, answer).
- Add a `--workers N` (a.k.a. `--concurrency`) CLI flag, default conservative, `1` = today's serial behavior.
- **Fold-in M5 fix:** correct the call-count double-count (`self.calls += 1` before cache check).

### Out of scope (explicitly)
- **Batch API** — ruled out by owner Decision 3.
- **asyncio rewrite** — stdlib `concurrent.futures` only; no event-loop migration.
- **New dependencies** — no `tenacity`/`backoff`; hand-roll backoff with stdlib `time`/`random`.
- **`contradict` re-embed → `fetch_vectors()`** — a *separate* tradeoff (deliberate per code comment at
  `contradict.py:172-175`). Noted here, NOT done in M6. Revisit as its own task.
- **M7 (CI/supply-chain) and M8 (privacy egress)** — later milestones, untouched.
- **JSON schema version** — must stay `1`. M6 changes execution order, not output shape.

---

## Logic Contracts

```
CONTRACT: total spend never exceeds --max-cost, even with N concurrent in-flight calls
VIOLATION: this is the core M6 risk — if the cap can be breached, the budget gate is wrong; abort the design and re-do thread-safety. Test must prove it with a forced-race fixture.

CONTRACT: the budget gate is a single atomic reserve-then-settle under one lock (check + reserve estimate happen together; actual cost reconciled after the call)
VIOLATION: if check and record are separate unlocked steps, TOCTOU race at cost.py:154/190 lets N threads pass the same check — revert to atomic reserve.

CONTRACT: JSON output for a given input + seed is byte-identical to the serial (pre-M6) output, ordering included
VIOLATION: collect futures into a list indexed by input position, then re-sort by each command's existing sort key (drift/confidence: (note_rel, level); concepts: confidence desc; answer: input gap order). If output differs, the parallel collection is wrong — fix collection, never change the schema.

CONTRACT: --workers 1 reproduces exact today's serial behavior (escape hatch + regression anchor)
VIOLATION: if N=1 differs from pre-M6, the executor wrapper has a side effect — isolate it.

CONTRACT: backend.calls and cost_ctx counters agree — a warm cache hit is NOT counted as a live call
VIOLATION: move self.calls increment below the cache check, or report cost_ctx.calls. (M5 fold-in: judge.py:203, generator.py:240, drafter.py:286 currently increment at method top.)

CONTRACT: a 429 / transient error retries with exponential backoff + jitter; a BudgetExceeded does NOT retry (it's terminal → exit 2)
VIOLATION: catching BudgetExceeded in the backoff loop would spin forever against the cap — backoff must only wrap rate-limit/transient errors and let BudgetExceeded propagate.
```

---

## Risks & Rollback

| Risk | Likelihood | Mitigation | Rollback |
|---|---|---|---|
| Budget cap breached under concurrency (TOCTOU on `self.usd`, `cost.py:154/190`) | **High if naive** | Atomic reserve-then-settle under `threading.Lock`; forced-race test | Per-phase `git revert`; `--workers 1` disables concurrency at runtime |
| Non-deterministic output order breaks JSON consumers / eval fixtures | High | Index-and-resort collection; assert byte-identical vs serial on fixture | `--workers 1` |
| `_families.add()` set corruption under threads (`cost.py`) | Medium | Same lock covers set mutation | revert |
| Backoff loop catches `BudgetExceeded` and spins | Medium | Explicit exception allowlist in retry wrapper | revert |
| Thread explosion / API connection limits | Low | Bounded pool, conservative default workers | lower `--workers` |
| Embedder/torch thread-safety on shared model | Low | Only LLM *judge/generate* calls parallelized; embedding stays on main thread | revert |

Every phase is a separate commit → `git revert <sha>` is the unit rollback. Runtime kill-switch: `--workers 1`.

---

## Phased Roadmap with Verification Evidence

> Baseline to beat: 576 pass / 0 fail, 84.67% cov, ruff+mypy clean (`make check`).
> Each phase ends with `make check` green + its phase-specific evidence.

### Phase 0 — Capture serial golden output (no src change)
**Goal:** Freeze current output as the determinism oracle before touching anything.
**Do:** Run each LLM command (or its existing test fixture path) with `--judge none` / mock backend, capture JSON to `tests/golden/m6_serial_*.json`. These are the byte-identical targets for Phase 4.
**Verify:** `git status` shows only new golden files; `make test` still green.
**Expected:** golden files written, suite 576 pass.
**Rollback:** delete golden files.

### Phase 1 — Thread-safe CostContext (the keystone)
**Goal:** `cost.py` budget gate holds under concurrency. **Do this first — everything else depends on it.**
**Do:** Add `threading.Lock` to `CostContext`. Replace separate `check_before_call`/`record` with an atomic
**reserve-then-settle**: under the lock, check cap against `usd + reserved + estimate` → reserve the estimate;
after the call, under the lock, settle (`reserved -= estimate; usd += actual`). Lock also guards `_families.add`
and all `+=` accumulation. Fix the M5 call-count double-count in the same pass (counter agrees with `cost_ctx`).
**Verify:** New test `test_cost_concurrency.py` spawns N=50 threads each reserving against a cap that allows
~10 calls; assert final `calls <= cap_allows` and `usd <= max_cost` **every run** (loop the test 20×).
**Expected:** `pytest tests/test_cost_concurrency.py -q` → all pass, 20/20 iterations, zero cap breaches.
**Rollback:** `git revert` (cost.py is self-contained; backends untouched this phase).

### Phase 2 — Backoff + retry wrapper
**Goal:** A 429 no longer aborts a run; transient errors retry with exp backoff + jitter.
**Do:** Add a small stdlib retry helper (`time.sleep(base * 2**attempt + jitter)`, capped attempts). Wire it into
the existing per-backend retry loops (judge/generator/drafter/drift/concept/confidence). Allowlist: retry on
rate-limit/transient; **never** retry `BudgetExceeded`. Backoff sleeps must be injectable/mocked so tests don't wait.
**Verify:** Test with a mock backend that raises 429 twice then succeeds → asserts success + 2 backoff sleeps
recorded (mocked clock); a `BudgetExceeded`-raising mock → asserts no retry, propagates.
**Expected:** `pytest tests/test_backoff.py -q` → pass; no real sleeping (clock mocked).
**Rollback:** `git revert`.

### Phase 3 — ThreadPool executor wrapper
**Goal:** A reusable bounded-parallel-map that wraps `complete_with_cache_and_cost` call sites.
**Do:** Add a helper that maps a function over items via `ThreadPoolExecutor(max_workers)`, returns results
**indexed by input position**, propagates `BudgetExceeded` immediately (cancel remaining), and surfaces the first
fatal error. Add `--workers` flag (default conservative, e.g. 4; `1` = serial). Thread cache/cost_ctx are already
shared objects — now safe per Phase 1.
**Verify:** Unit test the executor with a pure function (no LLM): order preserved, `--workers 1` == serial path,
`BudgetExceeded` from one task cancels the batch.
**Expected:** `pytest tests/test_executor.py -q` → pass.
**Rollback:** `git revert` (flag + helper only; not yet wired into commands).

### Phase 4 — Wire executor into the 6 commands (one at a time)
**Goal:** Each command runs its LLM loop in parallel, output byte-identical to Phase 0 golden.
**Do:** Replace the serial `for` loop in each of contradict, gap, drift, concepts, confidence, answer with the
Phase 3 executor. **After collection, apply each command's existing sort** (drift/confidence `(note_rel, level)`;
concepts `confidence` desc; answer input-gap order; contradict/gap order-independent). One commit per command.
**Verify (per command):** diff parallel output vs `tests/golden/m6_serial_*.json` → **byte-identical**. Run with
`--workers 8` and `--workers 1`, both must match golden.
**Expected:** `diff` empty for all 6; `make check` green; full suite still 576+ pass, cov ≥ 84%.
**Rollback:** `git revert` the specific command's commit (others unaffected).

### Phase 5 — Docs + changelog + memory
**Goal:** M6 landed and recorded.
**Do:** Update `CHANGELOG.md`, `ROADMAP.md` engineering note, `--workers` in README/help. Append any new
gotchas mid-session (already doing so). Update `memory/project_v2_architecture_decisions.md` status: M6 done,
M7 next. Commit `M6: ThreadPool concurrency + backoff — N× throughput, cap-safe`.
**Verify:** `make check` green; `wikilens contradict --help` shows `--workers`; CHANGELOG diff present.
**Expected:** clean commit, no Claude co-author trailer (portfolio repo — `memory/feedback_no_claude_trailer.md`).

---

## Verification philosophy (per CLAUDE.md)
- No live API calls in tests — mock backends + golden files are the oracle.
- "Construction tests pass" is **not** verification; the cap-breach test and byte-diff against golden are.
- Test-before-bulk: Phase 4 wires **one** command, proves byte-identical, then the rest.
