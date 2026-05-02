# P8 — Temporal Drift Detector (SDD)

**Status:** Specification — awaiting HITL approval before any implementation.
**Created:** 2026-05-02
**Preceded by:** P7 (PyPI + installer polish) — complete, tag `v0.7.0`, live on PyPI.
**Target effort:** ~15–20h, part-time.

---

## Goal

`wikilens drift <vault>` walks the vault's `git` history and surfaces notes where the author's **beliefs changed over time** — not typo fixes, not reformatting, not additions, not reorganisation. Genuine semantic shift in a claim between two revisions of the same note.

Output (markdown default, `--json` for machines): one entry per detected drift event, scoped to a single note, naming:

1. the **before** claim (commit SHA, date, sentence),
2. the **after** claim (commit SHA, date, sentence),
3. the **drift type** (`reversal`, `refinement`, `scope_change`),
4. the judge's one-sentence reasoning.

Exit 0 clean / 1 findings / 2 bad input — same convention as P3/P4/P5/P6.

This is the first phase that:

- **Reads `git log`** — the repo's history, not just the current tree. New surface, new failure modes (detached HEAD, shallow clones, bare repos, sub-dir vaults).
- **Requires temporal reasoning from the judge** — "did this position change?" is subtler than P4's binary contradiction call.
- **Has no "ground-truth at current HEAD"** — drift is inherently about pairs of past states. Eval requires a fixture repo with a crafted commit history.

## Pass/Fail criterion

`wikilens drift fixtures/drift_vault --judge openai`:

1. **Precision ≥ 0.80** on 10 planted events (5 semantic drifts + 5 surface-only revisions). At most 1 false positive among the surface-only set.
2. **Recall ≥ 0.80** — at least 4 of the 5 planted drifts surfaced.
3. **Wall clock < 2 min** on the fixture with `--judge openai`. `--judge none` (mock) < 5s.
4. **Exit codes correct** — 0 when no drifts found, 1 when at least one, 2 on bad input / not-a-git-repo / missing API key with `--judge openai`.
5. **100% of existing tests (317) still green; new tests green.**
6. **Budgeted autonomy enforced:** `--sample`, `--since`, `--min-score` respected; verified via unit test.

No "vibes" pass — numbers or it didn't ship. Bars set before eval runs. Precision is weighted above recall because a false "you abandoned belief X" claim is more costly to the user's trust in the tool than a missed one — drift surfacing is a *proposal* for review, not a verdict.

## Scope

### In

- New CLI subcommand `wikilens drift <vault>`:
  - `--since REF` — oldest commit / ref / date to walk (default: full history).
  - `--judge {none,openai,claude}` — backend (default: `openai`, per P5.4 memory).
  - `--model NAME` — judge model (default: `gpt-4o`).
  - `--min-score N` — drift threshold on judge's 1–5 score (default: 4).
  - `--sample N` — cap total pairs sent to the judge (smoke mode).
  - `--align-threshold F` — cosine floor for "same claim" alignment (default: 0.75). Hidden from `--help` noise (advanced).
  - `--identical-threshold F` — cosine ceiling above which pairs are surface edits (default: 0.98). Hidden.
  - `--granularity {sentence,paragraph}` — claim unit (default: `sentence`).
  - `--only NOTE` — restrict to a single note path.
  - `--json` — structured report instead of markdown.
  - `-v / --verbose` — per-commit progress to stderr.
- Git walker: shell out via `subprocess`, no new dependency.
- Claim extractor: strip frontmatter, headings, code fences, wikilinks/links, tables → deterministic sentence list. Reuses logic compatible with `ingest.py` parsing where sensible.
- Aligner: BGE embeddings (`BGEEmbedder` already in-project) + cosine similarity. Pairs aligned across adjacent revisions within `[τ_align, τ_identical)`.
- Filters: whitespace-only diff drop, list-reorder drop (sorted-equal check), proper-name typo drop (Levenshtein < 3 after stripping punctuation).
- Pluggable drift judge: `MockDriftJudge`, `OpenAIDriftJudge`, `ClaudeDriftJudge`. Prompt returns `{drift: bool, type, score, reasoning}`.
- Markdown renderer + JSON emitter.
- `fixtures/drift_vault/` — hand-crafted vault-inside-repo with ~8 notes and 10-ish commits planting the 10 eval events.
- `fixtures/eval/p8_ground_truth.json` — labels for each planted event: `{note, before_sha, after_sha, label: "drift"|"surface", type?}`.
- `scripts/eval_p8.py` — run end-to-end, compute precision/recall per class, append to `BENCHMARK.md`.
- Borderline-decision log `docs/p8-judge-notes.md` — any score-3 calls written for human review (same pattern as P5/P6).
- Unit tests for git walker, claim extractor, aligner, filters, judge kernels, CLI, end-to-end with mock.
- Docs: `docs/p8-decisions.md`, README section, `BENCHMARK.md` append, `HANDOFF.md` updates.

### Out (deferred)

- **Rename detection beyond `git log --follow`** — documented known gap. Heavy renames / splits / merges not tracked.
- **Cross-note drift** — belief stated in `A.md`, later restated differently in `B.md`. P8 is scoped to single-file history only.
- **Branch-aware drift** — only `main`'s linear history is walked. Merge commits collapsed to their first parent. Feature branches ignored.
- **Auto-patch suggestions** — P8 surfaces drift, does not edit notes.
- **Ollama judge** — interface-compatible, implementation deferred (same status as P4–P6).
- **Confidence calibration** — no meta-eval of judge vs. human beyond the borderline log.
- **Streaming output for very long histories** — full-result buffered then printed. `--sample` is the cost cap.
- **Per-sentence provenance embedding caching** — embeddings recomputed per run. Caching is a future optimisation.
- **Windowed / non-adjacent pairing** — only adjacent revisions are compared (revision N vs N+1). Long-horizon belief changes are captured transitively through chained adjacent drifts.

## Design decisions

### D1. Git backend — **shell out via `subprocess`** (approved)

No new dep. The project already uses `subprocess` elsewhere and `git` itself is a stable ABI on developer machines. GitPython / pygit2 would add install surface (wheels, C deps) for marginal API prettiness.

Commands used:

- `git -C <vault_root> rev-parse --show-toplevel` — locate the git root. Allows the vault to be a sub-dir of a larger repo.
- `git -C <repo_root> log --follow --name-status --format=%H%x00%ct%x00%s -M -- <rel_path>` — per-note revision list. `%x00` NUL separator avoids collisions with commit-message whitespace.
- `git -C <repo_root> show <sha>:<rel_path>` — fetch a specific revision's content.
- Any `git` failure → caught `subprocess.CalledProcessError` → surfaced as exit 2 with the underlying stderr.

All paths quoted; shell=False throughout; no user input ever interpolated without validation. Note paths validated as "inside repo root" before any `git show`.

**Rejected:**
- **GitPython** — adds ~2MB install footprint, wraps `git` we'd shell out to anyway for edge cases.
- **pygit2 / dulwich** — heavier native deps for no user-facing win.

### D2. Scope resolution — **vault may be a sub-dir of the repo** (approved)

The vault path passed to `wikilens drift` may or may not be the git root. P8 walks `git -C <root> --show-toplevel` from the vault path; if that fails, exit 2 with a clear "not a git repo" message. If the vault is `repo_root/notes/`, only `notes/`-scoped commits are walked via `-- <rel_path>`.

Relative paths computed with `Path.relative_to(repo_root)`. Windows path separators normalised (`\\` → `/`) for `git show` arguments.

**Rejected:**
- **Vault must equal git root.** Breaks the common "dotfiles repo with an `obsidian/` sub-dir" layout.
- **Auto-init a git repo if absent.** Never. Destructive / surprising.

### D3. Claim granularity — **sentence-level by default, `--granularity paragraph` escape hatch** (approved)

Each revision's body (post frontmatter / heading / fence stripping) is split into sentences via a simple rule-based splitter (periods / question marks / exclamations at end of line or followed by whitespace + capital, with a small abbreviation list). This is the claim unit for alignment.

`--granularity paragraph` — paragraphs are claim units instead (blank-line-separated blocks). Coarser, noisier individual diffs but cleaner alignments on notes that use long prose.

Sentence splitter lives in `src/wikilens/drift.py`; reuse avoided over a new dep because nltk/spacy pull weight we don't need. If the splitter misbehaves on the fixture, we fix the rules, not add a dep.

**Rejected:**
- **Paragraph-only.** Too coarse — two distinct belief changes in the same paragraph collapse.
- **Heading-section-level.** Useful but would miss sentence-scoped drifts (the common case).
- **Full-document diff.** No alignment possible; diff noise swamps the signal.

### D4. Alignment + filters — **BGE cosine in `[0.75, 0.98)`, three filters** (approved)

For each adjacent revision pair (rev_i, rev_{i+1}) of a note:

1. Extract claims (sentences) from each.
2. Embed all claims (`BGEEmbedder`, already in the project, warm on disk).
3. Build cosine similarity matrix; for each rev_i claim, take its best match in rev_{i+1}.
4. Classify:
   - cosine ≥ 0.98 → **identical / surface edit**, drop.
   - cosine in `[0.75, 0.98)` → **candidate drift pair**, forward to filters + judge.
   - cosine < 0.75 → no alignment (addition or deletion), drop.

Then three deterministic filters cut noise before the judge:

- **Whitespace-only diff drop.** Normalise whitespace on both sides; if equal, drop. (Catches pairs where splitter gave different tokenisations of identical text.)
- **List-reorder drop.** If both claims contain commas / semicolons and the multiset of tokens is equal, drop. (Catches "A, B, C" → "C, B, A".)
- **Proper-name typo drop.** Levenshtein distance after lowercasing and punctuation-stripping < 3 → drop. (Catches "Einstien" → "Einstein", "Westphalian" → "Westfalian".)

Thresholds are tunable via `--align-threshold` / `--identical-threshold` for P8.5 refinement; defaults set up-front to avoid post-hoc bar-moving.

**Rejected:**
- **Pure string-diff filtering (no embeddings).** Misses semantically-similar paraphrases; swamps the judge with noise.
- **Sentence-level BERTScore or BLEURT.** Heavier, no clear win over BGE cosine at this scale.
- **Edit-distance-only alignment.** Too brittle to wording changes that are not drifts (voice, tone).

### D5. Drift judge — **pluggable, 1–5 score, typed output, default `openai/gpt-4o`** (approved)

Per candidate pair, prompt the judge with:

- Note path + before SHA + before date + before claim + after SHA + after date + after claim.
- A one-shot exemplar of each type (reversal / refinement / scope change / none).
- Strict JSON schema: `{drift: bool, type: "reversal"|"refinement"|"scope_change"|"none", score: 1-5, reasoning: "≤ 200 chars"}`.

Drift accepted iff `drift == true AND score >= --min-score AND type != none`.

Prompt engineering principles carried from P4/P5/P6:

- XML delimiters around user content (inherits security hardening from May 2026 memory).
- "Abstain if uncertain" clause — judge may return `{drift: false, type: "none"}` without penalty.
- Explicit instruction: *"A reformulation that preserves the position is refinement, not drift. Drift requires a change in what the author holds to be true."*

Judge backends:

- `MockDriftJudge` — deterministic, seeded, for tests and `--judge none`.
- `OpenAIDriftJudge` — Chat Completions, structured output mode, retry on malformed JSON. Default. Model: `gpt-4o`.
- `ClaudeDriftJudge` — Anthropic Messages API, parallel structure. Model: `claude-sonnet-4-6`.

Borderline (score == 3) pairs are still *not* accepted as drifts (threshold is 4) but are written to `docs/p8-judge-notes.md` for human review — same pattern as P5's matcher-notes and P6's judge-notes.

### D6. Output shape — **markdown by default, `--json` for machines** (approved)

Markdown (default):

```
# Temporal drift findings

3 drift events across 2 notes, walking 42 commits from main@{2026-01-01} to HEAD.

## notes/chemistry.md

### 2026-02-14 → 2026-04-03 (reversal, score 5)

- `3fce99d` (2026-02-14): Water boils at 100°C at all altitudes.
- `a89d2c1` (2026-04-03): Water boils at 100°C only at sea-level atmospheric pressure; the boiling point drops with altitude.

  _Judge:_ The original absolute claim is replaced by a corrected, pressure-aware claim.

### 2026-03-10 → 2026-04-03 (refinement, score 4)

...
```

JSON (`--json`):

```json
{
  "schema_version": 1,
  "vault": "fixtures/drift_vault",
  "repo_root": ".../drift_vault",
  "walked_commits": 42,
  "pairs_considered": 108,
  "pairs_filtered": 77,
  "pairs_judged": 31,
  "findings": [
    {
      "note": "notes/chemistry.md",
      "before": {"sha": "3fce99d", "timestamp": "2026-02-14T12:00:00Z", "claim": "..."},
      "after":  {"sha": "a89d2c1", "timestamp": "2026-04-03T09:30:00Z", "claim": "..."},
      "type": "reversal",
      "score": 5,
      "reasoning": "..."
    }
  ]
}
```

`schema_version: 1` — bumped on breaking changes, per P3/P4/P5/P6 convention.

### D7. Eval fixture — **hand-craft `fixtures/drift_vault/`** (approved)

Not mined from `sample_vault/` or any real history. Discipline-matching: P3/P4/P5/P6 all use hand-crafted fixtures for precise ground truth.

Structure:

```
fixtures/drift_vault/
├── .git/                      # committed fixture git dir (see sub-decision below)
├── notes/
│   ├── chemistry.md
│   ├── cooking.md
│   ├── history.md
│   ├── biology.md
│   ├── physics.md
│   ├── music.md
│   ├── programming.md
│   └── meta.md
└── README.md
```

**~10 commits** over a simulated 3-month span planting:

- **5 semantic drifts** (label: `drift`) — examples:
  1. Absolute → conditional (`reversal`) — "water boils at 100°C" → "water boils at 100°C only at sea level".
  2. Causation → correlation (`reversal`) — "X causes Y" → "X correlates with Y but does not cause it".
  3. Tech switch (`reversal`) — "we should use Postgres for the side project" → "we should use SQLite".
  4. Narrowing (`scope_change`) — "AI will replace all coders" → "AI will automate routine coding tasks".
  5. Softening (`refinement`, still a drift) — "meditation is proven to reduce anxiety" → "some studies suggest meditation may help with anxiety, though replication is mixed".

- **5 surface-only revisions** (label: `surface`) — examples:
  1. Typo fix on a proper noun.
  2. Heading renamed without changing claim.
  3. List re-ordered without changing members.
  4. Passive → active voice, same claim.
  5. Example added that illustrates an unchanged claim.

**Sub-decision — committing `.git/` vs. a replay script. RESOLVED: Option A (committed `dotgit/`).**

Fixture needs reproducible history. Committing `fixtures/drift_vault/dotgit/` (renamed at eval/test time to `.git/`) into the wikilens repo gives reproducibility-by-clone alone: no setup step, exact SHAs pinned in ground truth. The alternative — a `scripts/build_drift_fixture.sh` replay — was rejected because content-hash-dependent SHAs change on every rebuild, breaking the ground-truth file.

Implementation: a `conftest.py` / `eval_p8.py` setup hook copies / renames `dotgit/` → `.git/` into a temp dir before any `git` command runs against the fixture. The fixture `.git/` is never mutated in place. Rejected alternative (committing a real `.git/` at `fixtures/drift_vault/.git/`) would trip parent-repo gitignore precedence and confuse IDEs.

### D8. Budgeted autonomy — **`--sample`, `--since`, `--min-score`, `--only`** (approved)

Layered caps, same philosophy as P4/P5/P6:

- `--sample N` — cap candidate pairs sent to the judge. Default: unlimited.
- `--since REF` — walk only commits after `REF` (commit / tag / date). Default: full history.
- `--min-score N` — judge score floor, default 4.
- `--only NOTE` — restrict to a single note. Default: all notes.

On a real user vault with 500 commits × 50 notes the unfiltered pair count could hit the thousands; the three filters cut aggressively before the judge, but `--sample` is the hard cost cap.

Estimated eval cost: ~30 judge calls × ~100 output tokens at `gpt-4o` pricing ≈ < $0.05 per full eval run.

### D9. Exit codes — **0 clean / 1 findings / 2 bad input** (approved)

- `0` — no drifts found (all candidate pairs either filtered out or judged as refinement/none below threshold).
- `1` — at least one drift surfaced.
- `2` — bad input: not a git repo, missing vault path, malformed `--since` ref, missing API key with `--judge openai/claude`, unsupported `--granularity`.

### D10. Known gap — **heavy renames / splits not tracked** (approved, documented)

`git log --follow` handles single-file rename detection reasonably but fails on:

- Splits (one note → two notes), which are rare in practice.
- Heavy rewrites triggering `--follow`'s similarity threshold.
- File deleted then re-created at a new path outside the similarity heuristic.

These are out of scope for v0.8.0. Documented as a known limitation in `README.md` and `docs/p8-decisions.md`. A future `--rename-threshold` knob could expose `git log`'s `-M<N>%` parameter.

## Deliverables checklist

- [ ] `src/wikilens/drift.py` — git walker + claim extractor + aligner + filters + pipeline.
- [ ] `src/wikilens/drift_judge.py` — `DriftJudge` protocol + `MockDriftJudge`, `OpenAIDriftJudge`, `ClaudeDriftJudge`.
- [ ] `src/wikilens/drift_format.py` — markdown renderer + JSON emitter.
- [ ] `src/wikilens/cli.py` — wire up `drift` subcommand.
- [ ] `fixtures/drift_vault/` — crafted fixture repo (see §D7).
- [ ] `fixtures/eval/p8_ground_truth.json` — labels for 10 planted events.
- [ ] `scripts/eval_p8.py` — eval runner, appends to `BENCHMARK.md`.
- [ ] `tests/test_drift_git.py` — git walker unit tests (uses a temp-dir mini-repo, not the fixture).
- [ ] `tests/test_drift_extract.py` — claim extractor + aligner + filters.
- [ ] `tests/test_drift_judge.py` — judge protocol, prompt shape, retry, missing-key errors.
- [ ] `tests/test_drift_format.py` — markdown snapshot + JSON schema.
- [ ] `tests/test_cli_drift.py` — CLI end-to-end with `MockDriftJudge`, exit codes.
- [ ] `docs/p8-decisions.md` — actual choices (may diverge from SDD).
- [ ] `docs/p8-judge-notes.md` — borderline-decision log.
- [ ] `README.md` — drift usage section.
- [ ] `BENCHMARK.md` — P8 section appended.
- [ ] `CHANGELOG.md` — v0.8.0 entry.
- [ ] `HANDOFF.md` + `.local/HANDOFF.md` — bumped on completion.
- [ ] `gotchas.md` — G6+ entries if anything bites.
- [ ] Tag release `v0.8.0` (after HITL push approval).

## CLI surface

```
wikilens drift <vault>
    [--since REF]                         # oldest commit / ref / date (default: full history)
    [--judge {none,openai,claude}]        # backend (default: openai)
    [--model NAME]                        # judge model (default: gpt-4o)
    [--min-score N]                       # drift threshold 1-5 (default: 4)
    [--sample N]                          # cap judged pairs
    [--granularity {sentence,paragraph}]  # claim unit (default: sentence)
    [--only NOTE]                         # restrict to one note
    [--json]                              # structured output
    [-v | --verbose]                      # per-commit progress
    # advanced (hidden from --help):
    [--align-threshold F]                 # default 0.75
    [--identical-threshold F]             # default 0.98
```

**Exit codes:** 0 clean / 1 findings / 2 bad input.

## Breakdown into atomic actions (15-min rule)

Ordered for the PIV loop. Each step has a single dominant risk and a validation check. Phase 8.1–8.2 are model-free so plumbing + extraction are validated without tokens.

### Phase 8.1 — Git walker (no LLM)

1. **Data classes in `src/wikilens/drift.py`:** `Revision`, `CandidatePair`, `DriftEvent`, `DriftReport`. Validate: module imports; dataclass round-trip test.
2. **Git-root resolver** — shell to `git rev-parse --show-toplevel` from the vault path, handle not-a-repo. Validate: unit tests on (a) vault == root, (b) vault is sub-dir, (c) vault outside a repo. Uses `pytest`'s `tmp_path` + `git init`.
3. **Per-note revision walker** — `git log --follow --name-status --format=... -M -- <rel>` parsing, returns ordered `list[Revision]`. Validate: temp-repo fixture with 3 commits; walker returns 3 revisions in order.
4. **Content fetcher** — `git show <sha>:<rel>` with path validation (inside-repo check, separator normalisation). Validate: unit test fetches content, path-traversal attempt raises.

### Phase 8.2 — Claim extractor + aligner + filters (no LLM)

5. **Body extractor** — strip frontmatter, fenced code, headings, wikilinks, markdown links. Validate: unit tests on adversarial inputs (nested code fence, inline code with `#`, wikilinks inside code, etc.).
6. **Sentence splitter** — rule-based, small abbreviation list. Validate: unit tests on ~20 representative sentences including edge cases ("Dr. Smith.", ellipses, URLs).
7. **Paragraph splitter** — blank-line-separated blocks. Validate: unit tests for `--granularity paragraph`.
8. **BGE-cosine aligner** — embed both sides, best-match matrix, classify into identical / candidate / unaligned by the two thresholds. Validate: unit test with synthetic claim pairs at each cosine bucket.
9. **Filter pipeline** — whitespace-only, list-reorder (multiset equality), proper-name typo (Levenshtein < 3). Validate: unit tests per filter with one positive and one negative case.
10. **Pair generator** — walks all adjacent-revision pairs per note, produces filtered `CandidatePair` list. Validate: end-to-end unit test on temp-repo fixture with 2 planted drifts + 1 surface edit — produces 2 candidate pairs.

### Phase 8.3 — The cognitive kernel

11. **`DriftJudge` protocol + `MockDriftJudge`** in `src/wikilens/drift_judge.py`. Seeded deterministic scoring for tests. Validate: unit test.
12. **`OpenAIDriftJudge`** — Chat Completions with structured-output JSON; retry on malformed; XML-delimited user content per security hardening memory. Validate: mock SDK client; test prompt structure, retry path, missing `OPENAI_API_KEY` error.
13. **`ClaudeDriftJudge`** — Anthropic Messages API parallel. Validate: parallel test.
14. **Hand-tune the judge prompt** on 2 seed pairs from the fixture. Validate: prompt distinguishes a planted reversal (returns `{drift: true, type: "reversal", score >= 4}`) from a planted surface edit (returns `{drift: false, type: "none"}`).

### Phase 8.4 — CLI + format

15. **`src/wikilens/drift_format.py`** — markdown renderer + JSON emitter. Validate: snapshot tests.
16. **Wire `wikilens drift` CLI** — argparse subcommand, `--judge none` path, exit codes. Validate: `wikilens drift fixtures/drift_vault --judge none` runs end-to-end and returns 0/1 correctly.

### Phase 8.5 — Eval fixture + harness

17. **Craft `fixtures/drift_vault/`** — 8 notes, ~10 commits, 5 drifts + 5 surface edits (see §D7). Commit nested `dotgit/` (see §D7 sub-decision). Validate: walker returns expected revision counts per note; `scripts/eval_p8.py --judge none` runs clean.
18. **`fixtures/eval/p8_ground_truth.json`** — labels for 10 planted events: `{note, before_sha, after_sha, label, type?}`. Validate: schema-validation unit test; every SHA resolves via `git rev-parse`.
19. **`scripts/eval_p8.py`** — end-to-end: walk → pairs → filter → judge → score against ground truth → per-label precision/recall → append to `BENCHMARK.md` → write borderline log. Validate: `--judge none` produces deterministic numbers; `--judge openai` hits the target bars.
20. **Performance pass** — wall clock < 2 min on `--judge openai`; < 5s on `--judge none`. Verify in `BENCHMARK.md`.
21. **Meta-reasoning review** — read `docs/p8-judge-notes.md` borderline decisions; decide whether thresholds or rubric need refinement. Review outcomes → `docs/p8-decisions.md`.

### Phase 8.6 — Ship

22. **Docs + release** — `docs/p8-decisions.md`, README section, `CHANGELOG.md` v0.8.0 entry, `HANDOFF.md` + `.local/HANDOFF.md` updates, version bump to `0.8.0`, tag `v0.8.0` **locally**. `gotchas.md` updates if anything bit. Validate: fresh-clone smoke (`pip install -e '.[dev,judge]'` + drift on fixture) works end-to-end. **Do not push without explicit user approval.**

Every step ends with `pytest -q` green and `python scripts/check_sanitization.py` on the staged diff before commit. **No `Co-Authored-By: Claude` trailer on any commit** (per memory — cost two force-pushes in P3).

## Risks & mitigation

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Sentence splitter mishandles real prose | High | Med | Conservative rules; `--granularity paragraph` escape hatch; adversarial unit tests |
| BGE cosine thresholds miscalibrated on real vaults | Med | Med | Tunable via CLI; fixture eval will surface gross miscalibration; documented defaults |
| Judge model can't distinguish refinement from drift reliably | Med | High | One-shot exemplar per type; pinned score rubric; borderline log; both refinement and reversal counted as drift (see D5) |
| Git walker fails on shallow clones / detached HEAD | Med | Med | Detect and exit 2 with clear message; unit tests for both cases |
| `git log --follow` misses renames | Med | Low | Documented known gap (§D10); out of scope for v0.8.0 |
| Vault = non-git directory | Low | Low | Detected at step 2; exit 2 with "not a git repo" |
| Nested `.git/` in fixture confuses IDE or `git add` | Low | Low | Committed as `dotgit/`, renamed at eval time if D7 sub-decision holds |
| Judge hallucinates drift on identical claims | Low | Med | Pre-filtered by cosine ≥ 0.98 check; pairs never reach judge |
| Cost blowup on large vaults with long history | Low | Med | `--sample` + `--since` caps; per-pair judge cost ~$0.001 |
| Path-traversal via malicious note path | Very Low | High | `rel.resolve().relative_to(repo_root)` check before `git show` |
| Windows path-separator mismatches in `git show` | Med | Low | Normalise `\\` → `/` in all git args; Windows unit test on CI |
| API-key leak in logs | Low | Very High | Judge never logs prompts with secrets; sanitization gate on diff |
| Frozen-in-time false positives from frontmatter tag changes | Low | Low | Frontmatter stripped before claim extraction |

## Gotcha log (P8 working notes)

Empty at SDD time. Will populate during execution. Anything that bites → `gotchas.md` at repo root (G6+).

## Handoff from P7

- Repo: tip of `main` at `3fce99d`, tag `v0.7.0` pushed to origin, live on PyPI.
- 317 tests green.
- P2 `BGEEmbedder` reused for alignment — no changes needed. Warm on disk.
- P4 `OpenAIJudge` / `ClaudeJudge` SDK setup, retry loop, and `.env` loading pattern are the templates for `OpenAIDriftJudge` / `ClaudeDriftJudge`.
- `OPENAI_API_KEY` + `ANTHROPIC_API_KEY` already provisioned.
- CI matrix covers Ubuntu + Windows on Python 3.12; P8 will run on both.
- Security hardening (SHA-256 chunk IDs, XML prompt delimiters, shared `_env.py`) carried forward into P8 judge implementations.

## What we learn in P8

- **Walking the repo's history as data** — first phase that treats git itself as the source. Tests the "your vault is a time series" premise.
- **Temporal reasoning under budget** — per-pair cost control via filters that must cut 70%+ of noise before the judge sees anything.
- **Fixture-as-git-repo discipline** — constructing a reproducible planted-event dataset inside another git repo is a pattern we'll need again for P9/P10 if either goes temporal.
- Honest acknowledgment that precision > recall is the right bias for user-facing surfacing tools: one confident false "you abandoned belief X" is worse than missing one.

## Resolved sub-decisions (2026-05-02, pre-Phase 8.1)

- **D7 sub-decision — fixture `.git/` layout.** **RESOLVED: Option A.** Commit `fixtures/drift_vault/dotgit/` and rename to `.git/` at eval / test time via a setup hook. Reproducibility-by-clone is the governing property; replay-script SHA drift was disqualifying. See §D7.
- **Transitive drift chaining.** **RESOLVED: adjacent-only for v0.8.0.** If rev A → rev B is a refinement and rev B → rev C is a further refinement, the two events are emitted independently; no synthetic A → C event. Keeps precision/recall math unambiguous; chaining deferred to P8.5 iff the fixture reveals user demand.
- **Refinement as drift.** **RESOLVED: counted, with typed tag.** A softened claim ("proven" → "some studies suggest") *is* a belief change and surfaces as `type: "refinement"` in §D5's schema. The fixture plants one such event explicitly (meditation example in §D7) to make the judge's refinement-vs-surface call concrete under eval.

## Open questions the user must resolve before Phase 8.2

- **`main`-only vs. all branches.** Lean: `main` (or current branch) only, merge commits collapsed to first-parent. Multi-branch drift is rare on personal vaults. Open for user override.
