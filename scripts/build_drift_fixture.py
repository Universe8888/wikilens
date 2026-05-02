"""Build the fixtures/drift_vault fixture repo with a planted git history.

Produces:
  fixtures/drift_vault/            — note files at HEAD
  fixtures/drift_vault/dotgit/     — the .git directory (renamed for safe tracking)

The fixture plants 10 labeled events:
  5 semantic drifts  (reversal x2, refinement x1, scope_change x2)
  5 surface-only revisions  (typo, voice, list-reorder, added-example, heading-rename)

Run this script once; after that, commit the output.  Do NOT run it again
unless you intentionally want to rebuild the history (SHAs will change).

Usage:
    python scripts/build_drift_fixture.py [--out fixtures/drift_vault]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "fixtures" / "drift_vault"

# Fixed author/date so SHAs are reproducible across machines.
AUTHOR_NAME = "Fixture Author"
AUTHOR_EMAIL = "fixture@example.com"
# Simulated dates — one per commit, spaced ~2 weeks apart.
DATES = [
    "2026-01-01T10:00:00+00:00",
    "2026-01-15T10:00:00+00:00",
    "2026-02-01T10:00:00+00:00",
    "2026-02-15T10:00:00+00:00",
    "2026-03-01T10:00:00+00:00",
    "2026-03-15T10:00:00+00:00",
    "2026-04-01T10:00:00+00:00",
    "2026-04-15T10:00:00+00:00",
    "2026-05-01T10:00:00+00:00",
    "2026-05-15T10:00:00+00:00",
    "2026-06-01T10:00:00+00:00",
]


class Commit(NamedTuple):
    date: str
    message: str
    files: dict[str, str]  # rel_path → content


# ---------------------------------------------------------------------------
# Note content — each note has 2+ commits.  The label column is for ground
# truth and is NOT written into the note content.
#
# Event index  Note              Before commit  After commit  Label    Type
#     E1       chemistry.md          C0             C2        drift    reversal
#     E2       biology.md            C0             C3        drift    reversal
#     E3       philosophy.md         C0             C4        drift    refinement
#     E4       physics.md            C0             C5        drift    scope_change
#     E5       cooking.md            C0             C6        drift    scope_change
#     E6       history.md            C0             C1        surface  typo
#     E7       programming.md        C1             C3        surface  voice
#     E8       music.md              C2             C5        surface  list_reorder
#     E9       chemistry.md          C2             C7        surface  added_example
#     E10      biology.md            C3             C8        surface  heading_rename
# ---------------------------------------------------------------------------

COMMITS: list[Commit] = [
    # C0 — initial versions of all notes
    Commit(
        date=DATES[0],
        message="initial notes",
        files={
            "chemistry.md": """\
---
tags: [chemistry, thermodynamics]
---

# Chemistry

Water boils at 100 degrees Celsius at all altitudes.
Altitude has no effect on the boiling point of water.
""",
            "biology.md": """\
---
tags: [biology, nutrition]
---

# Biology

Sugar consumption directly causes hyperactivity in children.
This has been confirmed by multiple studies.
""",
            "philosophy.md": """\
---
tags: [philosophy, epistemology]
---

# Philosophy

The scientific method has proven beyond all doubt that free will does not exist.
Neuroscience confirms this with certainty.
""",
            "physics.md": """\
---
tags: [physics, ai]
---

# Physics

Artificial intelligence will replace all human workers across every profession within a decade.
No job category will be immune to full automation.
""",
            "cooking.md": """\
---
tags: [cooking]
---

# Cooking

Cast iron cookware must never be washed with water or it will be permanently ruined.
Water instantly destroys the seasoning and causes irreversible rust.
""",
            "history.md": """\
---
tags: [history]
---

# History

The Treaty of Westfalia in 1648 established the principle of state souvereignty.
It ended the Thirty Years War in Europe.
""",
            "programming.md": """\
---
tags: [programming]
---

# Programming

It is recommended that one uses explicit type annotations in Python code.
This improves readability and helps catch errors early.
""",
            "music.md": """\
---
tags: [music]
---

# Music

The three primary elements of music are melody, harmony, and rhythm.
Together they define every musical composition.
""",
        },
    ),
    # C1 — surface fix E6: fix typos in history.md (Westfalia→Westphalia, souvereignty→sovereignty)
    Commit(
        date=DATES[1],
        message="fix typos in history note",
        files={
            "history.md": """\
---
tags: [history]
---

# History

The Treaty of Westphalia in 1648 established the principle of state sovereignty.
It ended the Thirty Years War in Europe.
""",
        },
    ),
    # C2 — semantic drift E1: chemistry.md boiling point claim revised (reversal)
    Commit(
        date=DATES[2],
        message="correct boiling point claim in chemistry",
        files={
            "chemistry.md": """\
---
tags: [chemistry, thermodynamics]
---

# Chemistry

Water boils at 100 degrees Celsius only at sea-level atmospheric pressure.
The boiling point drops significantly with increasing altitude.
""",
        },
    ),
    # C3 — semantic drift E2: biology.md sugar-hyperactivity claim revised (reversal)
    #       surface fix E7: programming.md voice change (passive→active)
    Commit(
        date=DATES[3],
        message="update biology and programming notes",
        files={
            "biology.md": """\
---
tags: [biology, nutrition]
---

# Biology

Research does not support the claim that sugar causes hyperactivity in children.
Multiple controlled studies have found no causal link.
""",
            "programming.md": """\
---
tags: [programming]
---

# Programming

Developers should use explicit type annotations in Python code.
This improves readability and helps catch errors early.
""",
        },
    ),
    # C4 — semantic drift E3: philosophy.md free-will claim softened (refinement)
    Commit(
        date=DATES[4],
        message="soften free will claim in philosophy",
        files={
            "philosophy.md": """\
---
tags: [philosophy, epistemology]
---

# Philosophy

Some neuroscientific evidence suggests that free will may be more constrained than we assume,
though philosophers debate whether the findings actually rule out free will entirely.
""",
        },
    ),
    # C5 — semantic drift E4: physics.md AI-jobs claim narrowed (scope_change)
    #       surface fix E8: music.md list reordered (rhythm, melody, harmony)
    Commit(
        date=DATES[5],
        message="narrow AI jobs claim and reorder music elements",
        files={
            "physics.md": """\
---
tags: [physics, ai]
---

# Physics

Artificial intelligence is likely to automate many routine cognitive tasks across various professions.
The degree of displacement will vary significantly by job type and skill level.
""",
            "music.md": """\
---
tags: [music]
---

# Music

The three primary elements of music are rhythm, melody, and harmony.
Together they define every musical composition.
""",
        },
    ),
    # C6 — semantic drift E5: cooking.md cast iron claim narrowed (scope_change)
    Commit(
        date=DATES[6],
        message="refine cast iron care advice in cooking",
        files={
            "cooking.md": """\
---
tags: [cooking]
---

# Cooking

Cast iron cookware can be washed with a small amount of water if dried immediately and re-oiled.
Prolonged soaking should be avoided, but brief washing does not ruin the seasoning.
""",
        },
    ),
    # C7 — surface fix E9: chemistry.md added example (no claim change)
    Commit(
        date=DATES[7],
        message="add altitude example to chemistry",
        files={
            "chemistry.md": """\
---
tags: [chemistry, thermodynamics]
---

# Chemistry

Water boils at 100 degrees Celsius only at sea-level atmospheric pressure.
The boiling point drops significantly with increasing altitude.
At the summit of Mount Everest (8849 m), water boils at approximately 70 degrees Celsius.
""",
        },
    ),
    # C8 — surface fix E10: biology.md heading renamed (no claim change)
    Commit(
        date=DATES[8],
        message="rename biology heading",
        files={
            "biology.md": """\
---
tags: [biology, nutrition]
---

# Biology and Nutrition

Research does not support the claim that sugar causes hyperactivity in children.
Multiple controlled studies have found no causal link.
""",
        },
    ),
]


def _git(repo: Path, *args: str, env: dict | None = None) -> str:
    full_env = os.environ.copy()
    full_env["GIT_AUTHOR_NAME"] = AUTHOR_NAME
    full_env["GIT_AUTHOR_EMAIL"] = AUTHOR_EMAIL
    full_env["GIT_COMMITTER_NAME"] = AUTHOR_NAME
    full_env["GIT_COMMITTER_EMAIL"] = AUTHOR_EMAIL
    if env:
        full_env.update(env)
    result = subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True,
        text=True,
        check=True,
        env=full_env,
    )
    return result.stdout.strip()


def build(out: Path) -> None:
    if out.exists():
        print(f"Removing existing {out} ...")
        shutil.rmtree(out)
    out.mkdir(parents=True)

    _git(out, "init", "--initial-branch=main")
    _git(out, "config", "user.email", AUTHOR_EMAIL)
    _git(out, "config", "user.name", AUTHOR_NAME)

    for i, commit in enumerate(COMMITS):
        date_env = {
            "GIT_AUTHOR_DATE": commit.date,
            "GIT_COMMITTER_DATE": commit.date,
        }
        for rel, content in commit.files.items():
            path = out / rel
            path.write_text(content, encoding="utf-8")
            _git(out, "add", rel, env=date_env)
        _git(out, "commit", "-m", commit.message, env=date_env)
        sha = _git(out, "rev-parse", "HEAD", env=date_env)
        print(f"C{i}: {sha[:12]}  {commit.message}")

    # Rename .git → dotgit so it can be committed into the parent repo.
    git_dir = out / ".git"
    dotgit_dir = out / "dotgit"
    git_dir.rename(dotgit_dir)
    print(f"\nBuilt {out}")
    print("Renamed .git → dotgit  (restore at eval time)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the P8 drift fixture repo.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    build(args.out)


if __name__ == "__main__":
    main()
