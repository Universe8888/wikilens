"""Tests for the Matcher protocol, MatchVerdict, SubstringMatcher, and
ClaudeMatcher (P5).

No real API calls. ClaudeMatcher is tested with a monkeypatched
Anthropic client.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wikilens.matcher import (
    DEFAULT_MATCH_THRESHOLD,
    RUBRIC_DESCRIPTIONS,
    RUBRIC_SCORES,
    Matcher,
    MatchVerdict,
    SubstringMatcher,
    _parse_match_verdict,
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


# ---------------------------------------------------------------------------
# _parse_match_verdict unit tests (no client needed)
# ---------------------------------------------------------------------------

def test_parse_match_verdict_valid():
    raw = '{"score": 4, "reasoning": "same concept, different wording"}'
    v = _parse_match_verdict(raw)
    assert v.score == 4
    assert "same concept" in v.rationale


def test_parse_match_verdict_invalid_json_raises():
    with pytest.raises(ValueError, match="not valid JSON"):
        _parse_match_verdict("not json")


def test_parse_match_verdict_missing_keys_raises():
    with pytest.raises(ValueError, match="missing keys"):
        _parse_match_verdict('{"score": 3}')


def test_parse_match_verdict_out_of_range_score_raises():
    raw = '{"score": 9, "reasoning": "r"}'
    with pytest.raises(ValueError, match="matcher score"):
        _parse_match_verdict(raw)


# ---------------------------------------------------------------------------
# ClaudeMatcher tests (Anthropic client monkeypatched — no real API calls)
# ---------------------------------------------------------------------------

def _make_mock_response(json_body: str) -> MagicMock:
    content_block = MagicMock()
    content_block.text = json_body
    response = MagicMock()
    response.content = [content_block]
    return response


def _make_claude_matcher(responses: list[str]):
    from wikilens.matcher import ClaudeMatcher

    with (
        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-test"}),
        patch("anthropic.Anthropic") as mock_cls,
    ):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.side_effect = [
            _make_mock_response(r) for r in responses
        ]
        m = ClaudeMatcher.__new__(ClaudeMatcher)
        m._client = mock_client
        m._model = "claude-sonnet-4-6"
        m._max_tokens = 128
        m.calls = 0
        m.abstentions = 0
        return m


def test_claude_matcher_returns_score_5_for_identical_concept():
    response_json = '{"score": 5, "reasoning": "identical question"}'
    m = _make_claude_matcher([response_json])
    v = m.score_pair("What is the Calvin cycle?", "What is the Calvin cycle?")
    assert v.score == 5
    assert m.calls == 1
    assert m.abstentions == 0


def test_claude_matcher_returns_score_1_for_unrelated():
    response_json = '{"score": 1, "reasoning": "completely different topics"}'
    m = _make_claude_matcher([response_json])
    v = m.score_pair("What is the Calvin cycle?", "What is the electoral college?")
    assert v.score == 1
    assert v.is_match() is False


def test_claude_matcher_abstains_after_retries_returns_score_1():
    m = _make_claude_matcher(["bad", "also bad", "still bad"])
    v = m.score_pair("gold", "proposed")
    assert v.score == 1
    assert m.abstentions == 1
    assert "abstained" in v.rationale.lower()


def test_claude_matcher_retries_on_bad_json_then_succeeds():
    bad = "not json"
    good = '{"score": 3, "reasoning": "related but broader scope"}'
    m = _make_claude_matcher([bad, good])
    v = m.score_pair("gold", "proposed")
    assert v.score == 3
    assert m.abstentions == 0


def test_claude_matcher_missing_key_raises_without_api_key():
    from wikilens.matcher import ClaudeMatcher

    with (
        patch("wikilens.matcher.load_dotenv_if_present"),
        patch.dict("os.environ", {}, clear=True),
        pytest.raises(OSError, match="ANTHROPIC_API_KEY"),
    ):
        ClaudeMatcher()


def test_claude_matcher_conforms_to_matcher_protocol():
    m = _make_claude_matcher([])
    assert isinstance(m, Matcher)
    assert m.name == "claude"
