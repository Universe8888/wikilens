"""Tests for the Generator protocol, GapCandidate, MockGenerator, and
ClaudeGenerator (P5).

No real API calls. ClaudeGenerator is tested with a monkeypatched
Anthropic client so prompt structure, JSON parsing, and error paths are
verified without network access or spending tokens.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wikilens.generator import (
    GapCandidate,
    GapFinding,
    Generator,
    MockGenerator,
    _parse_candidates,
)


def test_gap_candidate_accepts_valid_shape():
    c = GapCandidate(
        gap_question="What is X?",
        suggested_note_title="what-is-x",
        rationale="three notes mention X but none define it",
        supporting_chunk_ids=("c1", "c2", "c3"),
    )
    assert c.gap_question == "What is X?"
    assert c.suggested_note_title == "what-is-x"


def test_gap_candidate_rejects_empty_question():
    with pytest.raises(ValueError, match="gap_question"):
        GapCandidate(
            gap_question="   ",
            suggested_note_title="stub",
            rationale="r",
        )


def test_gap_candidate_rejects_empty_title():
    with pytest.raises(ValueError, match="suggested_note_title"):
        GapCandidate(
            gap_question="q?",
            suggested_note_title="",
            rationale="r",
        )


def test_gap_candidate_rejects_non_kebab_title():
    for bad in ["Not Kebab", "with_underscore", "UPPER", "has space", "-leading", "trailing-"]:
        with pytest.raises(ValueError, match="kebab-case"):
            GapCandidate(
                gap_question="q?",
                suggested_note_title=bad,
                rationale="r",
            )


def test_gap_candidate_accepts_kebab_with_digits():
    c = GapCandidate(
        gap_question="q?",
        suggested_note_title="python-3-asyncio",
        rationale="r",
    )
    assert c.suggested_note_title == "python-3-asyncio"


def test_gap_finding_binds_cluster_metadata():
    c = GapCandidate(gap_question="q?", suggested_note_title="s", rationale="r")
    f = GapFinding(cluster_id=3, cluster_size=7, candidate=c)
    assert f.cluster_id == 3
    assert f.cluster_size == 7
    assert f.candidate is c


def test_mock_generator_default_returns_single_gap():
    g = MockGenerator()
    out = g.propose_gaps([("c1", "text 1"), ("c2", "text 2")], top_k=3)
    assert len(out) == 1
    assert out[0].suggested_note_title == "mock-gap-1"
    assert out[0].supporting_chunk_ids == ("c1", "c2")
    assert g.calls == 1


def test_mock_generator_default_respects_top_k():
    g = MockGenerator()
    # Default returns one candidate, so top_k=0 should truncate to empty.
    out = g.propose_gaps([("c1", "x")], top_k=0)
    assert out == []


def test_mock_generator_cycles_seeded_batches():
    batches = [
        [
            GapCandidate(gap_question="q1?", suggested_note_title="a", rationale="r1"),
            GapCandidate(gap_question="q2?", suggested_note_title="b", rationale="r2"),
        ],
        [
            GapCandidate(gap_question="q3?", suggested_note_title="c", rationale="r3"),
        ],
    ]
    g = MockGenerator(candidates=batches)
    call1 = g.propose_gaps([("x", "t")], top_k=5)
    call2 = g.propose_gaps([("x", "t")], top_k=5)
    call3 = g.propose_gaps([("x", "t")], top_k=5)  # cycles back to batch[0]
    assert [c.suggested_note_title for c in call1] == ["a", "b"]
    assert [c.suggested_note_title for c in call2] == ["c"]
    assert [c.suggested_note_title for c in call3] == ["a", "b"]
    assert g.calls == 3


def test_mock_generator_truncates_seeded_batch_to_top_k():
    batch = [
        GapCandidate(gap_question="q1?", suggested_note_title="a", rationale="r"),
        GapCandidate(gap_question="q2?", suggested_note_title="b", rationale="r"),
        GapCandidate(gap_question="q3?", suggested_note_title="c", rationale="r"),
    ]
    g = MockGenerator(candidates=[batch])
    out = g.propose_gaps([("x", "t")], top_k=2)
    assert [c.suggested_note_title for c in out] == ["a", "b"]


def test_mock_generator_conforms_to_generator_protocol():
    g = MockGenerator()
    assert isinstance(g, Generator)
    assert g.name == "mock"


# ---------------------------------------------------------------------------
# _parse_candidates unit tests (no client needed)
# ---------------------------------------------------------------------------

def test_parse_candidates_valid_array():
    raw = '''[
      {
        "gap_question": "What is the Calvin cycle?",
        "suggested_note_title": "calvin-cycle",
        "rationale": "three notes mention NADPH but none explain its use",
        "supporting_chunk_ids": ["c1", "c2"]
      }
    ]'''
    out = _parse_candidates(raw, valid_ids={"c1", "c2", "c3"})
    assert len(out) == 1
    assert out[0].suggested_note_title == "calvin-cycle"
    assert out[0].supporting_chunk_ids == ("c1", "c2")


def test_parse_candidates_filters_unknown_chunk_ids():
    raw = '''[{
        "gap_question": "q?",
        "suggested_note_title": "stub",
        "rationale": "r",
        "supporting_chunk_ids": ["real", "hallucinated"]
    }]'''
    out = _parse_candidates(raw, valid_ids={"real"})
    assert out[0].supporting_chunk_ids == ("real",)


def test_parse_candidates_invalid_json_raises():
    with pytest.raises(ValueError, match="not valid JSON"):
        _parse_candidates("not json", valid_ids=set())


def test_parse_candidates_non_array_raises():
    with pytest.raises(ValueError, match="JSON array"):
        _parse_candidates('{"key": "val"}', valid_ids=set())


def test_parse_candidates_missing_keys_raises():
    raw = '[{"gap_question": "q?"}]'
    with pytest.raises(ValueError, match="missing keys"):
        _parse_candidates(raw, valid_ids=set())


def test_parse_candidates_rejects_non_kebab_title():
    raw = '''[{
        "gap_question": "q?",
        "suggested_note_title": "Not Kebab",
        "rationale": "r",
        "supporting_chunk_ids": []
    }]'''
    with pytest.raises(ValueError, match="kebab-case"):
        _parse_candidates(raw, valid_ids=set())


# ---------------------------------------------------------------------------
# ClaudeGenerator tests (Anthropic client monkeypatched — no real API calls)
# ---------------------------------------------------------------------------

def _make_mock_response(json_body: str) -> MagicMock:
    content_block = MagicMock()
    content_block.text = json_body
    response = MagicMock()
    response.content = [content_block]
    return response


def _make_claude_generator(responses: list[str]):
    from wikilens.generator import ClaudeGenerator

    with (
        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-test"}),
        patch("anthropic.Anthropic") as mock_cls,
    ):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.side_effect = [
            _make_mock_response(r) for r in responses
        ]
        gen = ClaudeGenerator.__new__(ClaudeGenerator)
        gen._client = mock_client
        gen._model = "claude-sonnet-4-6"
        gen._max_tokens = 1024
        gen.calls = 0
        gen.abstentions = 0
        return gen


def test_claude_generator_returns_valid_candidates():
    response_json = '''[
      {
        "gap_question": "What is the Calvin cycle?",
        "suggested_note_title": "calvin-cycle",
        "rationale": "notes mention NADPH but never explain dark reactions",
        "supporting_chunk_ids": ["c1", "c2"]
      }
    ]'''
    gen = _make_claude_generator([response_json])
    chunks = [("c1", "light reactions produce NADPH"), ("c2", "chlorophyll absorbs photons")]
    out = gen.propose_gaps(chunks, top_k=3)
    assert len(out) == 1
    assert out[0].suggested_note_title == "calvin-cycle"
    assert gen.calls == 1
    assert gen.abstentions == 0


def test_claude_generator_respects_top_k():
    response_json = '''[
      {"gap_question": "q1?", "suggested_note_title": "a",
       "rationale": "r", "supporting_chunk_ids": []},
      {"gap_question": "q2?", "suggested_note_title": "b",
       "rationale": "r", "supporting_chunk_ids": []},
      {"gap_question": "q3?", "suggested_note_title": "c",
       "rationale": "r", "supporting_chunk_ids": []}
    ]'''
    gen = _make_claude_generator([response_json])
    out = gen.propose_gaps([("x", "text")], top_k=2)
    assert len(out) == 2
    assert [c.suggested_note_title for c in out] == ["a", "b"]


def test_claude_generator_abstains_after_retries_exhausted():
    gen = _make_claude_generator(["not json", "still not json", "nope"])
    out = gen.propose_gaps([("c1", "text")], top_k=3)
    assert out == []
    assert gen.abstentions == 1


def test_claude_generator_retries_on_bad_json_then_succeeds():
    bad = "not json"
    good = (
        '[{"gap_question": "q?", "suggested_note_title": "s",'
        ' "rationale": "r", "supporting_chunk_ids": []}]'
    )
    gen = _make_claude_generator([bad, good])
    out = gen.propose_gaps([("c1", "text")], top_k=3)
    assert len(out) == 1
    assert gen.abstentions == 0


def test_claude_generator_missing_key_raises_without_api_key():
    from wikilens.generator import ClaudeGenerator

    with (
        patch("wikilens.generator.load_dotenv_if_present"),
        patch.dict("os.environ", {}, clear=True),
        pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"),
    ):
        ClaudeGenerator()


def test_claude_generator_conforms_to_generator_protocol():
    gen = _make_claude_generator([])
    assert isinstance(gen, Generator)
    assert gen.name == "claude"
