# Close-out Tier 1 — Portfolio Polish Plan

**Goal (one sentence):** Make wikilens recruiter-ready in the 45-second skim by surfacing
the proof that already exists — badges, a real sample-output block, and a demo recording —
without touching any source code.

**Status:** COMPLETE (Phases A, B done + verified; C anchor+recipe done, GIF render pending on user machine).
**Owner:** Boris Manzov · **Date:** 2026-06-15 · **Repo tip:** 32c7920 (M6)

### Outcome
- **Phase A — Badges:** DONE. 5 badges (PyPI, CI, Python, MIT, coverage). All URLs verified 200.
  Coverage worded as `≥84%` (the CI-enforced floor) — provably true, not a fabricated measured %.
- **Phase B — Sample output:** DONE + VERIFIED byte-faithful against live `wikilens audit` (exit 1, 19 findings).
- **Phase C — Demo:** `demo.tape` committed (vhs, verified "sound" vs live docs) + README `<!-- DEMO -->`
  anchor. **GIF render deferred to user** — no recorder + no TTY in this headless session; recipe in demo.tape.
- **Cleanup:** removed agent's stray 0-byte junk (`84%)`, `84)`, `Launch`, `gaps.json`); deleted orphan
  `demo-tape` branch (agent overstepped + committed there); re-created demo.tape on `main`; added
  `gaps.json` to `.gitignore`.

---

## Source of Truth

- Real `audit` output captured live on `fixtures/audit_vault` (16 notes, 19 findings) —
  verified at session time, exit 0, no API key required. This is the demo payload.
- PyPI: `wikilens 0.11.0` is the latest published version (verified via `pip index versions`).
- CI: last 4 runs `success` on Ubuntu + Windows matrix (verified via `gh run list`).
- Entry point: `wikilens = "wikilens.cli:main"` (verified in pyproject.toml). Note:
  `python -m wikilens` does NOT work (no `__main__.py`); the `wikilens` console script does.

## Boundaries

**In scope:**
- README header badges (PyPI, CI, Python, license, coverage)
- One real sample-output block in README (the captured `audit` report)
- A committed `demo.tape` (vhs script) + a short "regenerate the demo" note, so the GIF
  is reproducible
- Deleting nothing, fixing no source code

**Out of scope (explicitly):**
- Any change under `src/` — this is presentation only
- Tier 2 items (stale `dist/` cleanup, `drift --since` fix, "Why I built this" para) — deferred
- Actually recording/embedding a binary GIF in this session (no TTY, no recorder installed)
- The P12.7 launch (Tier 3)

## Logic Contracts

```
CONTRACT: every number/claim added to the README must be independently verified this session
  | VIOLATION: do not write the claim; mark it TODO and tell the user what couldn't be verified
CONTRACT: sample output pasted in README must be byte-faithful to real captured output
  | VIOLATION: abort the block, never hand-edit output to look better
CONTRACT: no edits to any file under src/
  | VIOLATION: abort phase, alert user
CONTRACT: badge URLs must resolve to the real repo (Universe8888/wikilens) and real PyPI pkg
  | VIOLATION: fix the slug before committing; a 404 badge is worse than no badge
CONTRACT: if the demo GIF cannot be generated+verified headless, say so — do not commit a
  placeholder image or claim a GIF exists | VIOLATION: silent downgrade; flag as pending instead
```

## Risks & Rollback

- **Risk:** badge slug wrong → broken image. **Mitigation:** curl each badge URL before commit.
- **Risk:** GIF can't be recorded headless. **Mitigation:** ship `demo.tape` + instructions;
  mark GIF embed as `pending (user runs `vhs demo.tape` locally)`. No fake asset.
- **Rollback:** every change is in README.md + one new `demo.tape` file. `git checkout README.md`
  and `rm demo.tape` fully reverts. No source, no schema, no external system touched.

## Phased Roadmap with Verification Evidence

### Phase A — Badges in README header
- **Do:** add a badge row under the title: PyPI version, CI status, Python 3.12+, MIT license,
  coverage 84%.
- **Verify:** `curl -sI` each badge URL returns 200; visually confirm slug = `Universe8888/wikilens`
  and PyPI pkg = `wikilens`.
- **Rollback:** `git checkout README.md`

### Phase B — Real sample-output block
- **Do:** insert a fenced "what you actually see" block right after the Agents table, using the
  byte-faithful `audit fixtures/audit_vault` output captured this session.
- **Verify:** re-run `wikilens audit fixtures/audit_vault`, diff against the pasted block — must
  match exactly (exit 0, 19 findings).
- **Rollback:** `git checkout README.md`

### Phase C — Reproducible demo recipe (GIF deferred to user machine)
- **Do:** commit `demo.tape` (vhs script) that runs `ingest` + `audit` on the fixture; add a
  one-line "Demo" section in README that references it and leaves an `<!-- demo.gif -->` anchor.
- **Verify:** `vhs validate demo.tape` if vhs is installable; otherwise mark Phase C `pending`
  and hand the user the exact `winget install charmbracelet.vhs && vhs demo.tape` command.
- **Rollback:** `rm demo.tape` + `git checkout README.md`

---

**Ready to proceed?** Reply **APPROVED** (or `/go`) to start Phase A, or give corrections first.
