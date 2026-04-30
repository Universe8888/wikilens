"""Tests for the Matcher protocol, MatchVerdict, and SubstringMatcher (P5).

ClaudeMatcher tests land in Phase 5.2 with a monkeypatched Anthropic
client.
"""

from __future__ import annotations

import pytest

from wikilens.matcher import (
    DEFAULT_MATCH_THRESHOLD,
    RUBRIC_DESCRIPTIONS,
    RUBRIC_SCORES,
    Matcher,
    MatchVerdict,
    SubstringMatcher,
)


def test_match_verdict_accepts_valid_scores():
    for s in RUBRIC_SCORES:
        v = MatchVerdict(score=s, rationale="r")
        assert v.score == s


def test_match_verdict_rejects_out_of_range_scores():
    for bad in [0, 6, -1, 10]:
        with pytest.raises(ValueError, match="matcher score"):
            MatchVerdict(score=bad, rationale="r")


def test_match_verdict_is_match_respects_default_threshold():
    assert MatchVerdict(score=5, rationale="r").is_match() is True
    assert MatchVerdict(score=4, rationale="r").is_match() is True
    assert MatchVerdict(score=3, rationale="r").is_match() is False
    assert MatchVerdict(score=1, rationale="r").is_match() is False


def test_match_verdict_is_match_respects_custom_threshold():
    v = MatchVerdict(score=3, rationale="r")
    assert v.is_match(threshold=3) is True
    assert v.is_match(threshold=4) is False


def test_match_verdict_is_borderline_covers_3_and_4_only():
    assert MatchVerdict(score=3, rationale="r").is_borderline() is True
    assert MatchVerdict(score=4, rationale="r").is_borderline() is True
    assert MatchVerdict(score=5, rationale="r").is_borderline() is False
    assert MatchVerdict(score=2, rationale="r").is_borderline() is False
    assert MatchVerdict(score=1, rationale="r").is_borderline() is False


def test_default_match_threshold_is_four():
    # Pinned — changing this value is a breaking eval change.
    assert DEFAULT_MATCH_THRESHOLD == 4


def test_rubric_descriptions_cover_every_score():
    assert set(RUBRIC_DESCRIPTIONS.keys()) == set(RUBRIC_SCORES)


def test_substring_matcher_conforms_to_matcher_protocol():
    m = SubstringMatcher()
    assert isinstance(m, Matcher)
    assert m.name == "substring"


def test_substring_matcher_scores_identical_strings_high():
    m = SubstringMatcher()
    v = m.score_pair("What is the Calvin cycle?", "What is the Calvin cycle?")
    assert v.score == 5


def test_substring_matcher_scores_paraphrase_as_match():
    m = SubstringMatcher()
    # Shared content words: "calvin", "cycle" out of 3 gold content words.
    # Ratio = 2/3 ≈ 0.67 → score 4 (clear match).
    v = m.score_pair(
        "What is the Calvin cycle works?",
        "How does Calvin cycle?",
    )
    assert v.score == 4


def test_substring_matcher_scores_unrelated_low():
    m = SubstringMatcher()
    v = m.score_pair(
        "What is the Calvin cycle?",
        "What is the electoral college?",
    )
    # Stopwords (<3 chars) filtered; remaining sets disjoint.
    assert v.score == 1


def test_substring_matcher_handles_empty_inputs():
    m = SubstringMatcher()
    v = m.score_pair("?", "")
    assert v.score == 1
    assert "no content tokens" in v.rationale.lower()


def test_substring_matcher_rationale_reports_overlap():
    m = SubstringMatcher()
    v = m.score_pair("alpha beta gamma", "alpha beta delta")
    assert "overlap" in v.rationale.lower()
