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

import json
import os
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from wikilens._env import load_dotenv_if_present

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


def _build_rubric_text() -> str:
    lines = []
    for score in sorted(RUBRIC_DESCRIPTIONS, reverse=True):
        lines.append(f"  {score} — {RUBRIC_DESCRIPTIONS[score]}")
    return "\n".join(lines)


_MATCHER_SYSTEM_PROMPT = f"""\
You are a precise evaluator comparing two gap descriptions from a
knowledge-base gap-analysis system.

Your task: score how well PROPOSED_GAP matches GOLD_GAP on this pinned rubric:

{_build_rubric_text()}

Rules:
- Apply the rubric literally. Do not infer intent beyond what is written.
- Score 4 or 5 only when both gaps refer to the same missing concept, even if
  phrased differently.
- Score 3 only when the concepts are related but one is clearly broader/narrower.
- Score 1 or 2 when the gaps address genuinely different questions.
- reasoning must be one sentence, no longer.
- Return ONLY valid JSON, starting with "{{".

JSON schema:
{{
  "score": <integer 1-5>,
  "reasoning": "<one sentence>"
}}
"""

_MATCHER_USER_TEMPLATE = """\
<gold_gap>
{gold_gap}
</gold_gap>

<proposed_gap>
{proposed_gap}
</proposed_gap>
"""

_MATCHER_MAX_TOKENS = 128
_MATCHER_MAX_RETRIES = 2
DEFAULT_CLAUDE_MODEL_MATCHER = "claude-sonnet-4-6"


def _parse_match_verdict(raw: str) -> MatchVerdict:
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"matcher response is not valid JSON: {e}") from e
    required = {"score", "reasoning"}
    missing = required - doc.keys()
    if missing:
        raise ValueError(f"matcher response missing keys: {missing}")
    return MatchVerdict(score=int(doc["score"]), rationale=str(doc["reasoning"]))


class ClaudeMatcher:
    """Claude-backed gap matcher using the pinned 1–5 rubric.

    Used ONLY by ``scripts/eval_p5.py`` — never by the production CLI.
    Loads ``ANTHROPIC_API_KEY`` from env, same pattern as ClaudeJudge.
    """

    name = "claude"

    def __init__(
        self,
        model: str = DEFAULT_CLAUDE_MODEL_MATCHER,
        max_tokens: int = _MATCHER_MAX_TOKENS,
    ):
        load_dotenv_if_present()
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise OSError(
                "ANTHROPIC_API_KEY is not set. "
                "Export it in your shell or add it to .env at the repo root."
            )
        try:
            import anthropic as _anthropic
        except ImportError as e:
            raise ImportError(
                "The 'anthropic' package is required for ClaudeMatcher. "
                "Install it with: pip install -e '.[judge]'"
            ) from e

        self._client = _anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self.calls: int = 0
        self.abstentions: int = 0

    def score_pair(self, gold_gap: str, proposed_gap: str) -> MatchVerdict:
        """Score one (gold, proposed) pair. Retries on malformed JSON."""
        self.calls += 1
        user_content = _MATCHER_USER_TEMPLATE.format(
            gold_gap=gold_gap, proposed_gap=proposed_gap
        )
        last_err: Exception | None = None

        for attempt in range(_MATCHER_MAX_RETRIES + 1):
            system = _MATCHER_SYSTEM_PROMPT
            if attempt > 0:
                system += (
                    "\nCRITICAL: Your previous response was not valid JSON. "
                    'Output ONLY the JSON object, starting with "{".'
                )
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
            raw = getattr(response.content[0], "text", "").strip()
            try:
                return _parse_match_verdict(raw)
            except ValueError as e:
                last_err = e
                continue

        self.abstentions += 1
        return MatchVerdict(
            score=1,
            rationale=f"matcher abstained after {_MATCHER_MAX_RETRIES + 1} attempts: {last_err}",
        )


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
