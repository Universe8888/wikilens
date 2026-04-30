# audit_vault — deliberate defects for P3

Purpose-built fixture for the Link Auditor eval (P3). Every defect class
is represented ≥ 2× so precision/recall metrics have signal. Ground
truth lives at `fixtures/eval/p3_ground_truth.json`.

Do not rely on this vault for retrieval benchmarks — it's intentionally
broken. Retrieval benchmarks use `fixtures/sample_vault/`.

## What's planted

- **Broken wikilinks:** `mars → pluto`, `jupiter → great-red-spot`,
  `telescopes → hubble` (embed), `solo-comet → nonexistent-meteor`.
- **Shadowed basenames:** two files share the basename `ideas.md`
  (`notes/ideas.md` and `journal/ideas.md`). `ideas-overview` links to
  the unqualified `[[ideas]]`.
- **Orphans** (outbound ≥ 1, zero inbound): `mercury`, `telescopes`,
  `lonely-rock`, `drifter`, `solo-comet`, `ideas-overview`.
- **Not orphans:** `isolated-dwarf` has no outbound links at all —
  isolated, not orphaned.
- **Reciprocal (negative signal):** `saturn ↔ moons`.
- **One-way:** multiple clean one-way edges so the detector has
  non-trivial true positives.
