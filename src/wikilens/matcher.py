"""Pluggable matcher interface for gap eval (P5).

The matcher answers ONE question: "does this proposed gap describe the
same missing concept as this gold gap?" It's used only by
``scripts/eval_p5.py`` — production ``wikilens gap`` runs never invoke
a matcher.

Two backends:

- ``SubstringMatcher`` — deterministic, dependency-free. Used for
  dry-runs and as a sanity floor for the eval harness.
- ``ClaudeMatcher`` — pinned 1–5 rubric, landing in Phase 5.2.

The rubric is the ONLY way to compare matcher scores across runs. It's
pinned here (not in the prompt) so any change is a breaking eval
change and must bump ``schema_version`` in ``p5_ground_truth.json``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# Pinned rubric. DO NOT edit without bumping the p5_ground_truth.json
# schema_version — the threshold is baked into the eval, and shifting
# it retroactively makes historical BENCHMARK.md numbers non-comparable.
RUBRIC_SCORES = (1, 2, 3, 4, 5)
DEFAULT_MATCH_THRESHOLD = 4

RUBRIC_DESCRIPTIONS = {
    5: "Proposed and gold describe the same missing concept with equivalent semantics.",
    4: "Same missing concept, different wording or framing.",
    3: "Related concept, different scope (broader or narrower).",
    2: "Same general topic area, but a different specific question.",
    1: "Unrelated.",
}


@dataclass(frozen=True)
class MatchVerdict:
    """Structured output of one matcher call.

    Attributes:
        score: integer 1–5 per the pinned rubric. Callers apply the
            threshold (default ``DEFAULT_MATCH_THRESHOLD``) to decide
            match/non-match.
        rationale: one-line explanation for audit. Borderline verdicts
            (score 3 or 4) are logged so the human architect can
            review them after each eval run.
    """

    score: int
    rationale: str

    def __post_init__(self) -> None:
        if self.score not in RUBRIC_SCORES:
            raise ValueError(
                f"matcher score must be one of {RUBRIC_SCORES}, got {self.score!r}"
            )

    def is_match(self, threshold: int = DEFAULT_MATCH_THRESHOLD) -> bool:
        return self.score >= threshold

    def is_borderline(self) -> bool:
        """True for rubric scores of 3 or 4 — the zone worth logging."""
        return self.score in (3, 4)


@runtime_checkable
class Matcher(Protocol):
    """Protocol every matcher backend implements."""

    name: str

    def score_pair(self, gold_gap: str, proposed_gap: str) -> MatchVerdict:
        """Score how well ``proposed_gap`` matches ``gold_gap`` on the 1–5 rubric."""
        ...


def _normalize(s: str) -> str:
    return " ".join(s.lower().strip().split())


# Common function / question words that would otherwise inflate overlap
# between semantically unrelated prompts ("What is X?" / "What is Y?").
# Deliberately small — SubstringMatcher is a sanity-floor backend, not
# a semantic engine; the real work lives in ClaudeMatcher.
_STOPWORDS = frozenset(
    {
        "the", "and", "but", "for", "nor", "yet", "with", "from", "that",
        "this", "these", "those", "what", "when", "where", "which", "who",
        "whom", "how", "why", "does", "did", "are", "was", "were", "have",
        "has", "had", "can", "will", "would", "could", "should", "into",
        "about", "such", "than", "then", "also", "only", "very",
    }
)


def _token_set(s: str) -> set[str]:
    # Split on whitespace and strip trailing punctuation commonly found in
    # question strings. Deliberately crude — this is a sanity-floor matcher,
    # not a semantic engine.
    toks = _normalize(s).replace("?", "").replace(".", "").replace(",", "").split()
    return {t for t in toks if len(t) >= 3 and t not in _STOPWORDS}


class SubstringMatcher:
    """Deterministic, dependency-free matcher for dry-runs and sanity tests.

    Uses token-overlap on content words (length >= 3) to approximate the
    pinned rubric. It's coarse — that's the point. ``ClaudeMatcher``
    handles the fuzzy cases the eval actually cares about.

    Mapping:
    - Overlap ratio >= 0.80 → score 5 (near-identical).
    - Overlap ratio >= 0.50 → score 4 (clear match).
    - Overlap ratio >= 0.25 → score 3 (borderline).
    - Overlap ratio >= 0.10 → score 2 (same topic area).
    - Otherwise             → score 1 (unrelated).

    The thresholds are chosen so that two paraphrases of a 6–10 word
    question usually land at 4 (half the content words overlap) without
    inflating to 5 unless they are genuinely identical.
    """

    name = "substring"

    def score_pair(self, gold_gap: str, proposed_gap: str) -> MatchVerdict:
        gold_tokens = _token_set(gold_gap)
        prop_tokens = _token_set(proposed_gap)
        if not gold_tokens or not prop_tokens:
            return MatchVerdict(score=1, rationale="one side has no content tokens")
        overlap = len(gold_tokens & prop_tokens)
        ratio = overlap / max(len(gold_tokens), len(prop_tokens))
        if ratio >= 0.80:
            score = 5
        elif ratio >= 0.50:
            score = 4
        elif ratio >= 0.25:
            score = 3
        elif ratio >= 0.10:
            score = 2
        else:
            score = 1
        return MatchVerdict(
            score=score,
            rationale=f"token overlap ratio {ratio:.2f} ({overlap} shared)",
        )
