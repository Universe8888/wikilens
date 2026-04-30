"""Tests for the Judge protocol, MockJudge, and ClaudeJudge (P4).

No real API calls. ClaudeJudge is tested with a monkeypatched Anthropic
client so prompt structure + JSON parsing + error paths can be verified
without network access or spending tokens.
"""

from __future__ import annotations
from unittest.mock import MagicMock, patch

import pytest

from wikilens.judge import ALL_TYPES, Judge, JudgeVerdict, MockJudge, _parse_verdict


def test_judge_verdict_accepts_valid_shapes():
    v = JudgeVerdict(
        verdict=True, type="factual", score=0.9, reasoning="Paris vs Berlin"
    )
    assert v.verdict is True
    assert v.type == "factual"
    assert v.score == 0.9


def test_judge_verdict_rejects_score_out_of_range():
    with pytest.raises(ValueError, match="score must be in"):
        JudgeVerdict(verdict=False, type="none", score=1.5, reasoning="x")
    with pytest.raises(ValueError, match="score must be in"):
        JudgeVerdict(verdict=False, type="none", score=-0.1, reasoning="x")


def test_judge_verdict_rejects_unknown_type():
    with pytest.raises(ValueError, match="type must be one of"):
        JudgeVerdict(verdict=True, type="values", score=0.5, reasoning="x")  # type: ignore[arg-type]


def test_judge_verdict_enforces_verdict_type_coherence():
    # verdict=True requires type != "none"
    with pytest.raises(ValueError, match="verdict=True"):
        JudgeVerdict(verdict=True, type="none", score=0.9, reasoning="x")
    # verdict=False requires type == "none"
    with pytest.raises(ValueError, match="verdict=False"):
        JudgeVerdict(verdict=False, type="factual", score=0.1, reasoning="x")


def test_all_types_constant_matches_literal():
    assert ALL_TYPES == ("factual", "temporal", "none")


def test_mock_judge_default_returns_no_contradiction():
    j = MockJudge()
    v = j.score_pair("A says X", "B says Y")
    assert v.verdict is False
    assert v.type == "none"
    assert v.score == 0.0
    assert j.calls == 1


def test_mock_judge_cycles_through_seeded_verdicts():
    seeded = [
        JudgeVerdict(verdict=True, type="factual", score=0.9, reasoning="1"),
        JudgeVerdict(verdict=False, type="none", score=0.0, reasoning="2"),
        JudgeVerdict(verdict=True, type="temporal", score=0.7, reasoning="3"),
    ]
    j = MockJudge(verdicts=seeded)
    out = [j.score_pair("a", "b") for _ in range(7)]
    # Cycled: 1, 2, 3, 1, 2, 3, 1
    assert [v.reasoning for v in out] == ["1", "2", "3", "1", "2", "3", "1"]
    assert j.calls == 7


def test_mock_judge_conforms_to_judge_protocol():
    j = MockJudge()
    assert isinstance(j, Judge)
    assert j.name == "mock"


# ---------------------------------------------------------------------------
# _parse_verdict unit tests (no client needed)
# ---------------------------------------------------------------------------

def test_parse_verdict_valid_factual():
    raw = '{"verdict": true, "type": "factual", "score": 0.95, "reasoning": "A says X, B says Y"}'
    v = _parse_verdict(raw)
    assert v.verdict is True
    assert v.type == "factual"
    assert v.score == 0.95


def test_parse_verdict_valid_none():
    raw = '{"verdict": false, "type": "none", "score": 0.1, "reasoning": "Same claim"}'
    v = _parse_verdict(raw)
    assert v.verdict is False
    assert v.type == "none"


def test_parse_verdict_invalid_json_raises():
    with pytest.raises(ValueError, match="not valid JSON"):
        _parse_verdict("not json at all")


def test_parse_verdict_missing_keys_raises():
    with pytest.raises(ValueError, match="missing keys"):
        _parse_verdict('{"verdict": true}')


def test_parse_verdict_coherence_violation_raises():
    # Model returns verdict=true but type=none — schema violation.
    raw = '{"verdict": true, "type": "none", "score": 0.8, "reasoning": "oops"}'
    with pytest.raises(ValueError):
        _parse_verdict(raw)


# ---------------------------------------------------------------------------
# ClaudeJudge tests (Anthropic client monkeypatched — no real API calls)
# ---------------------------------------------------------------------------

def _make_mock_response(json_body: str) -> MagicMock:
    content_block = MagicMock()
    content_block.text = json_body
    response = MagicMock()
    response.content = [content_block]
    return response


def _make_claude_judge_with_mock(responses: list[str]):
    """Build a ClaudeJudge with a patched Anthropic client."""
    from wikilens.judge import ClaudeJudge

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-test"}):
        with patch("anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create.side_effect = [
                _make_mock_response(r) for r in responses
            ]
            judge = ClaudeJudge.__new__(ClaudeJudge)
            judge._client = mock_client
            judge._model = "claude-sonnet-4-6"
            judge._max_tokens = 256
            judge.calls = 0
            judge.abstentions = 0
            return judge


def test_claude_judge_returns_factual_verdict():
    response_json = '{"verdict": true, "type": "factual", "score": 0.97, "reasoning": "Paris vs Berlin"}'
    judge = _make_claude_judge_with_mock([response_json])
    v = judge.score_pair("Paris is the capital of France.", "Berlin is the capital of France.")
    assert v.verdict is True
    assert v.type == "factual"
    assert v.score == 0.97
    assert judge.calls == 1
    assert judge.abstentions == 0


def test_claude_judge_returns_temporal_verdict():
    response_json = '{"verdict": true, "type": "temporal", "score": 0.85, "reasoning": "db changed"}'
    judge = _make_claude_judge_with_mock([response_json])
    v = judge.score_pair("We use Postgres (2022).", "We use MySQL (2024).")
    assert v.type == "temporal"


def test_claude_judge_abstains_after_retries_exhausted():
    # All responses are malformed JSON.
    judge = _make_claude_judge_with_mock(["not json", "still not json", "nope"])
    v = judge.score_pair("a", "b")
    assert v.verdict is False
    assert v.type == "none"
    assert judge.abstentions == 1


def test_claude_judge_retries_on_bad_json_then_succeeds():
    bad = "not json"
    good = '{"verdict": false, "type": "none", "score": 0.1, "reasoning": "unrelated"}'
    judge = _make_claude_judge_with_mock([bad, good])
    v = judge.score_pair("a", "b")
    assert v.verdict is False
    assert judge.abstentions == 0


def test_claude_judge_missing_key_raises_env_error_without_key():
    from wikilens.judge import ClaudeJudge

    # Patch out dotenv so it can't reload the key from .env, then clear env.
    with patch("wikilens.judge._load_dotenv_if_present"):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
                ClaudeJudge()
