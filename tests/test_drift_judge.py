"""Tests for the drift judge kernels (P8.3).

Unit-tests cover:
- DriftVerdict dataclass invariants.
- _parse_verdict: valid JSON, missing keys, bad type, bad score, incoherent drift/type.
- MockDriftJudge: default no-drift, seeded sequence, cycling, call counter.
- OpenAIDriftJudge: missing API key error, prompt structure, retry on bad JSON,
  abstention after exhausted retries. (SDK client mocked — no network.)
- ClaudeDriftJudge: same set as OpenAI, parallel structure.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from wikilens.drift_judge import (
    ClaudeDriftJudge,
    DriftVerdict,
    MockDriftJudge,
    OpenAIDriftJudge,
    _parse_verdict,
    _SYSTEM_PROMPT,
    _USER_TEMPLATE,
)


# ---------------------------------------------------------------------------
# DriftVerdict invariants
# ---------------------------------------------------------------------------


def test_drift_verdict_valid_reversal():
    v = DriftVerdict(drift=True, type="reversal", score=5, reasoning="Clear flip.")
    assert v.drift is True
    assert v.type == "reversal"
    assert v.score == 5


def test_drift_verdict_valid_no_drift():
    v = DriftVerdict(drift=False, type="none", score=1, reasoning="Same claim.")
    assert v.drift is False


def test_drift_verdict_invalid_score_low():
    with pytest.raises(ValueError, match="score must be in"):
        DriftVerdict(drift=False, type="none", score=0, reasoning="x")


def test_drift_verdict_invalid_score_high():
    with pytest.raises(ValueError, match="score must be in"):
        DriftVerdict(drift=True, type="reversal", score=6, reasoning="x")


def test_drift_verdict_invalid_type():
    with pytest.raises(ValueError, match="type must be one of"):
        DriftVerdict(drift=True, type="unknown", score=4, reasoning="x")  # type: ignore[arg-type]


def test_drift_verdict_drift_true_with_none_type():
    with pytest.raises(ValueError, match="drift=True requires type"):
        DriftVerdict(drift=True, type="none", score=4, reasoning="x")


def test_drift_verdict_drift_false_with_real_type():
    with pytest.raises(ValueError, match="drift=False requires type='none'"):
        DriftVerdict(drift=False, type="reversal", score=2, reasoning="x")


# ---------------------------------------------------------------------------
# _parse_verdict
# ---------------------------------------------------------------------------


def _make_raw(drift=False, type_="none", score=1, reasoning="ok") -> str:
    return json.dumps({"drift": drift, "type": type_, "score": score, "reasoning": reasoning})


def test_parse_verdict_valid_no_drift():
    v = _parse_verdict(_make_raw())
    assert v.drift is False
    assert v.type == "none"
    assert v.score == 1


def test_parse_verdict_valid_drift():
    v = _parse_verdict(_make_raw(drift=True, type_="refinement", score=4, reasoning="Softened claim."))
    assert v.drift is True
    assert v.type == "refinement"
    assert v.score == 4


def test_parse_verdict_not_json():
    with pytest.raises(ValueError, match="not valid JSON"):
        _parse_verdict("not json at all")


def test_parse_verdict_missing_keys():
    with pytest.raises(ValueError, match="missing keys"):
        _parse_verdict(json.dumps({"drift": True, "type": "reversal"}))


def test_parse_verdict_bad_score_string():
    with pytest.raises((ValueError, TypeError)):
        _parse_verdict(_make_raw(drift=True, type_="reversal", score="high"))


def test_parse_verdict_incoherent_drift_type():
    with pytest.raises(ValueError):
        _parse_verdict(_make_raw(drift=True, type_="none", score=4))


# ---------------------------------------------------------------------------
# MockDriftJudge
# ---------------------------------------------------------------------------


def test_mock_default_returns_no_drift():
    judge = MockDriftJudge()
    v = judge.score_pair("note.md", "before", "2026-01-01", "after", "2026-02-01")
    assert v.drift is False
    assert v.type == "none"
    assert judge.calls == 1


def test_mock_seeded_sequence():
    verdicts = [
        DriftVerdict(drift=True, type="reversal", score=5, reasoning="Flip."),
        DriftVerdict(drift=False, type="none", score=1, reasoning="Same."),
    ]
    judge = MockDriftJudge(verdicts=verdicts)
    v1 = judge.score_pair("n", "b", "d1", "a", "d2")
    v2 = judge.score_pair("n", "b", "d1", "a", "d2")
    assert v1.type == "reversal"
    assert v2.type == "none"
    assert judge.calls == 2


def test_mock_cycles_when_exhausted():
    verdicts = [DriftVerdict(drift=True, type="refinement", score=4, reasoning="r")]
    judge = MockDriftJudge(verdicts=verdicts)
    for _ in range(5):
        v = judge.score_pair("n", "b", "d1", "a", "d2")
        assert v.type == "refinement"
    assert judge.calls == 5


# ---------------------------------------------------------------------------
# Prompt shape validation
# ---------------------------------------------------------------------------


def test_user_template_contains_xml_delimiters():
    rendered = _USER_TEMPLATE.format(
        note="notes/chem.md",
        before_claim="Water boils at 100C.",
        before_date="2026-01-01",
        after_claim="Water boils at 100C only at sea level.",
        after_date="2026-03-01",
    )
    assert "<note>" in rendered
    assert "<before>" in rendered
    assert "<after>" in rendered
    assert "<date>" in rendered


def test_system_prompt_covers_all_types():
    for t in ("reversal", "refinement", "scope_change", "none"):
        assert t in _SYSTEM_PROMPT


def test_system_prompt_specifies_score_scale():
    assert "1-5" in _SYSTEM_PROMPT or "1–5" in _SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# OpenAIDriftJudge — missing key
# ---------------------------------------------------------------------------


def test_openai_judge_missing_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with patch("wikilens.drift_judge.load_dotenv_if_present"):
        with pytest.raises(OSError, match="OPENAI_API_KEY"):
            OpenAIDriftJudge()


# ---------------------------------------------------------------------------
# OpenAIDriftJudge — mocked SDK
# ---------------------------------------------------------------------------


def _openai_response(content: str) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@pytest.fixture()
def openai_judge(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with patch("openai.OpenAI") as mock_cls:
        client = MagicMock()
        mock_cls.return_value = client
        judge = OpenAIDriftJudge(model="gpt-4o")
        judge._client = client
        yield judge, client


def test_openai_judge_valid_response(openai_judge):
    judge, client = openai_judge
    client.chat.completions.create.return_value = _openai_response(
        _make_raw(drift=True, type_="reversal", score=5, reasoning="Position flipped.")
    )
    v = judge.score_pair("note.md", "before", "2026-01-01", "after", "2026-03-01")
    assert v.drift is True
    assert v.type == "reversal"
    assert v.score == 5
    assert judge.calls == 1
    assert judge.abstentions == 0


def test_openai_judge_retry_on_bad_json(openai_judge):
    judge, client = openai_judge
    good = _make_raw(drift=False, type_="none", score=1, reasoning="No change.")
    client.chat.completions.create.side_effect = [
        _openai_response("not json"),
        _openai_response(good),
    ]
    v = judge.score_pair("note.md", "b", "d1", "a", "d2")
    assert v.drift is False
    assert client.chat.completions.create.call_count == 2


def test_openai_judge_retry_adds_critical_note(openai_judge):
    judge, client = openai_judge
    good = _make_raw(drift=False, type_="none", score=1, reasoning="ok")
    client.chat.completions.create.side_effect = [
        _openai_response("bad"),
        _openai_response(good),
    ]
    judge.score_pair("note.md", "b", "d1", "a", "d2")
    second_call_args = client.chat.completions.create.call_args_list[1]
    messages = second_call_args.kwargs.get("messages") or second_call_args.args[0]
    system_msg = next(m for m in messages if m["role"] == "system")
    assert "CRITICAL" in system_msg["content"]


def test_openai_judge_abstains_after_all_retries(openai_judge):
    judge, client = openai_judge
    client.chat.completions.create.return_value = _openai_response("bad json always")
    v = judge.score_pair("note.md", "b", "d1", "a", "d2")
    assert v.drift is False
    assert "abstained" in v.reasoning
    assert judge.abstentions == 1
    assert client.chat.completions.create.call_count == 3  # 1 + _MAX_RETRIES


def test_openai_judge_prompt_contains_note_and_claims(openai_judge):
    judge, client = openai_judge
    client.chat.completions.create.return_value = _openai_response(
        _make_raw(drift=False, type_="none", score=1, reasoning="ok")
    )
    judge.score_pair(
        "notes/chem.md",
        "Water boils at 100C.",
        "2026-01-15",
        "Water boils at 100C only at sea level.",
        "2026-03-10",
    )
    call_args = client.chat.completions.create.call_args
    messages = call_args.kwargs.get("messages") or call_args.args[0]
    user_msg = next(m for m in messages if m["role"] == "user")
    assert "notes/chem.md" in user_msg["content"]
    assert "Water boils at 100C." in user_msg["content"]
    assert "2026-01-15" in user_msg["content"]


# ---------------------------------------------------------------------------
# ClaudeDriftJudge — missing key
# ---------------------------------------------------------------------------


def test_claude_judge_missing_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("wikilens.drift_judge.load_dotenv_if_present"):
        with pytest.raises(OSError, match="ANTHROPIC_API_KEY"):
            ClaudeDriftJudge()


# ---------------------------------------------------------------------------
# ClaudeDriftJudge — mocked SDK
# ---------------------------------------------------------------------------


def _claude_response(content: str) -> MagicMock:
    block = MagicMock()
    block.text = content
    resp = MagicMock()
    resp.content = [block]
    return resp


@pytest.fixture()
def claude_judge(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("anthropic.Anthropic") as mock_cls:
        client = MagicMock()
        mock_cls.return_value = client
        judge = ClaudeDriftJudge(model="claude-sonnet-4-6")
        judge._client = client
        yield judge, client


def test_claude_judge_valid_response(claude_judge):
    judge, client = claude_judge
    client.messages.create.return_value = _claude_response(
        _make_raw(drift=True, type_="scope_change", score=4, reasoning="Narrowed.")
    )
    v = judge.score_pair("note.md", "before", "2026-01-01", "after", "2026-03-01")
    assert v.drift is True
    assert v.type == "scope_change"
    assert v.score == 4
    assert judge.calls == 1


def test_claude_judge_retry_on_bad_json(claude_judge):
    judge, client = claude_judge
    good = _make_raw(drift=False, type_="none", score=1, reasoning="ok")
    client.messages.create.side_effect = [
        _claude_response("not json"),
        _claude_response(good),
    ]
    v = judge.score_pair("note.md", "b", "d1", "a", "d2")
    assert v.drift is False
    assert client.messages.create.call_count == 2


def test_claude_judge_abstains_after_all_retries(claude_judge):
    judge, client = claude_judge
    client.messages.create.return_value = _claude_response("bad json always")
    v = judge.score_pair("note.md", "b", "d1", "a", "d2")
    assert v.drift is False
    assert "abstained" in v.reasoning
    assert judge.abstentions == 1


def test_claude_judge_prompt_contains_note_and_claims(claude_judge):
    judge, client = claude_judge
    client.messages.create.return_value = _claude_response(
        _make_raw(drift=False, type_="none", score=1, reasoning="ok")
    )
    judge.score_pair(
        "notes/bio.md",
        "Meditation is proven to reduce anxiety.",
        "2026-01-01",
        "Some studies suggest meditation may help with anxiety.",
        "2026-04-01",
    )
    call_args = client.messages.create.call_args
    user_msg = call_args.kwargs["messages"][0]["content"]
    assert "notes/bio.md" in user_msg
    assert "Meditation is proven" in user_msg
    assert "2026-01-01" in user_msg
