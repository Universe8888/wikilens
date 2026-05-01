"""Tests for the Drafter protocol, MockDrafter, OpenAIDrafter, ClaudeDrafter.

Phase 6.1 covered the protocol contract, MockDrafter, and _validate_body.
Phase 6.2 adds OpenAIDrafter and ClaudeDrafter with mocked SDK clients:
prompt structure, footnote enforcement, retry-on-bad-structure, abstention.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wikilens.drafter import (
    Drafter,
    DraftInput,
    MockDrafter,
    _validate_body,
)


# ─── helpers ──────────────────────────────────────────────────────────────────


def _mk_input(
    gap_question: str = "What is the Calvin cycle?",
    chunks: tuple[tuple[str, str, str], ...] = (
        ("c1", "photosynthesis.md", "Light reactions produce ATP and NADPH."),
        ("c2", "chlorophyll.md", "Chlorophyll absorbs photons at 680nm."),
    ),
    is_external_research: bool = False,
) -> DraftInput:
    return DraftInput(
        gap_question=gap_question,
        suggested_note_title="calvin-cycle",
        rationale="notes describe light reactions but not dark reactions",
        chunks=chunks,
        is_external_research=is_external_research,
    )


_VALID_BODY = (
    "## What the vault says\n\n"
    "The vault notes ATP production.[^1]\n\n"
    "## Evidence gaps\n\n"
    "- No coverage of RuBisCO.\n\n"
    "## Related notes\n\n"
    "## Citations\n\n"
    '[^1]: `c1` — "Light reactions produce..."\n'
)

_INVALID_BODY_MISSING_SECTION = (
    "## What the vault says\n\nSomething.[^1]\n\n## Citations\n\n[^1]: `c1` — \"x\"\n"
)


# ─── Drafter protocol ─────────────────────────────────────────────────────────


def test_mock_drafter_conforms_to_protocol():
    drafter = MockDrafter()
    assert isinstance(drafter, Drafter)
    assert drafter.name == "mock"


def test_drafter_protocol_is_runtime_checkable():
    class FakeDrafter:
        name = "fake"

        def draft_stub(self, draft_input: DraftInput) -> str:
            return _VALID_BODY

    assert isinstance(FakeDrafter(), Drafter)


# ─── MockDrafter ──────────────────────────────────────────────────────────────


def test_mock_drafter_default_returns_four_sections():
    drafter = MockDrafter()
    body = drafter.draft_stub(_mk_input())
    assert "## What the vault says" in body
    assert "## Evidence gaps" in body
    assert "## Related notes" in body
    assert "## Citations" in body


def test_mock_drafter_cites_first_chunk():
    drafter = MockDrafter()
    body = drafter.draft_stub(_mk_input())
    assert "c1" in body


def test_mock_drafter_increments_call_counter():
    drafter = MockDrafter()
    drafter.draft_stub(_mk_input())
    drafter.draft_stub(_mk_input())
    assert drafter.calls == 2


def test_mock_drafter_cycles_seeded_bodies():
    bodies = [_VALID_BODY, _VALID_BODY.replace("ATP", "ADP")]
    drafter = MockDrafter(bodies=bodies)
    b0 = drafter.draft_stub(_mk_input())
    b1 = drafter.draft_stub(_mk_input())
    b2 = drafter.draft_stub(_mk_input())
    assert b0 == bodies[0]
    assert b1 == bodies[1]
    assert b2 == bodies[0]  # cycles


def test_mock_drafter_external_research_variant():
    drafter = MockDrafter()
    body = drafter.draft_stub(_mk_input(is_external_research=True))
    assert "external research" in body.lower() or "no relevant coverage" in body.lower()
    assert "## What the vault says" in body
    assert "## Evidence gaps" in body


def test_mock_drafter_no_chunks_still_valid():
    drafter = MockDrafter()
    body = drafter.draft_stub(_mk_input(chunks=()))
    assert _validate_body(body)


# ─── _validate_body ───────────────────────────────────────────────────────────


def test_validate_body_accepts_complete_stub():
    assert _validate_body(_VALID_BODY)


def test_validate_body_rejects_missing_section():
    assert not _validate_body(_INVALID_BODY_MISSING_SECTION)


def test_validate_body_rejects_empty_string():
    assert not _validate_body("")


# ─── DraftInput ───────────────────────────────────────────────────────────────


def test_draft_input_defaults_not_external_research():
    inp = _mk_input()
    assert not inp.is_external_research


def test_draft_input_external_research_flag():
    inp = _mk_input(is_external_research=True)
    assert inp.is_external_research


# ─── API key guard (OpenAIDrafter / ClaudeDrafter) ────────────────────────────


def test_openai_drafter_missing_key_raises():
    from wikilens.drafter import OpenAIDrafter

    with (
        patch("wikilens.drafter.load_dotenv_if_present"),
        patch.dict("os.environ", {}, clear=True),
        pytest.raises(OSError, match="OPENAI_API_KEY"),
    ):
        OpenAIDrafter()


def test_claude_drafter_missing_key_raises():
    from wikilens.drafter import ClaudeDrafter

    with (
        patch("wikilens.drafter.load_dotenv_if_present"),
        patch.dict("os.environ", {}, clear=True),
        pytest.raises(OSError, match="ANTHROPIC_API_KEY"),
    ):
        ClaudeDrafter()


# ─── OpenAIDrafter (mocked openai client) ─────────────────────────────────────


def _make_openai_response(body: str) -> MagicMock:
    msg = MagicMock()
    msg.content = body
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _make_openai_drafter(responses: list[str]) -> "OpenAIDrafter":
    from wikilens.drafter import OpenAIDrafter

    drafter = OpenAIDrafter.__new__(OpenAIDrafter)
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        _make_openai_response(r) for r in responses
    ]
    drafter._client = mock_client
    drafter._model = "gpt-4o"
    drafter._max_tokens = 1536
    drafter.calls = 0
    drafter.abstentions = 0
    return drafter


def _make_claude_drafter(responses: list[str]) -> "ClaudeDrafter":
    from wikilens.drafter import ClaudeDrafter

    drafter = ClaudeDrafter.__new__(ClaudeDrafter)
    mock_client = MagicMock()
    content_blocks = []
    for r in responses:
        block = MagicMock()
        block.text = r
        content_blocks.append(block)
    # Each call pops the next response.
    mock_client.messages.create.side_effect = [
        MagicMock(content=[block]) for block in content_blocks
    ]
    drafter._client = mock_client
    drafter._model = "claude-sonnet-4-6"
    drafter._max_tokens = 1536
    drafter.calls = 0
    drafter.abstentions = 0
    return drafter


# Shared valid body that passes _validate_body.
_VALID_BODY = (
    "## What the vault says\n\n"
    "Light reactions produce ATP and NADPH.[^1]\n\n"
    "## Evidence gaps\n\n"
    "- The Calvin cycle mechanism is not described.\n\n"
    "## Related notes\n\n"
    "## Citations\n\n"
    '[^1]: `c1` — "Light reactions produce ATP..."\n'
)

_INVALID_BODY = "Some text without the required sections."


def test_openai_drafter_returns_valid_body():
    drafter = _make_openai_drafter([_VALID_BODY])
    body = drafter.draft_stub(_mk_input())
    assert _validate_body(body)
    assert drafter.calls == 1
    assert drafter.abstentions == 0


def test_openai_drafter_retries_on_invalid_structure():
    drafter = _make_openai_drafter([_INVALID_BODY, _VALID_BODY])
    body = drafter.draft_stub(_mk_input())
    assert _validate_body(body)
    assert drafter._client.chat.completions.create.call_count == 2


def test_openai_drafter_abstains_when_all_retries_fail():
    # 3 invalid responses (_MAX_RETRIES=2 means 3 attempts total)
    drafter = _make_openai_drafter([_INVALID_BODY, _INVALID_BODY, _INVALID_BODY])
    body = drafter.draft_stub(_mk_input())
    # Fallback stub still has all four sections.
    assert _validate_body(body)
    assert "DRAFT FAILED" in body
    assert drafter.abstentions == 1


def test_openai_drafter_external_research_uses_different_template():
    drafter = _make_openai_drafter([_VALID_BODY])
    inp = _mk_input(is_external_research=True)
    drafter.draft_stub(inp)
    call_kwargs = drafter._client.chat.completions.create.call_args
    messages = call_kwargs[1]["messages"] if call_kwargs[1] else call_kwargs[0][0]
    # Find user message content.
    user_msg = next(m for m in messages if m["role"] == "user")
    assert "insufficient coverage" in user_msg["content"].lower() or \
           "external" in user_msg["content"].lower()


def test_openai_drafter_system_prompt_contains_four_sections():
    drafter = _make_openai_drafter([_VALID_BODY])
    drafter.draft_stub(_mk_input())
    call_kwargs = drafter._client.chat.completions.create.call_args
    messages = call_kwargs[1]["messages"] if call_kwargs[1] else call_kwargs[0][0]
    system_msg = next(m for m in messages if m["role"] == "system")
    for section in [
        "## What the vault says",
        "## Evidence gaps",
        "## Related notes",
        "## Citations",
    ]:
        assert section in system_msg["content"]


def test_openai_drafter_conforms_to_drafter_protocol():
    from wikilens.drafter import Drafter, OpenAIDrafter
    drafter = _make_openai_drafter([_VALID_BODY])
    assert isinstance(drafter, Drafter)
    assert drafter.name == "openai"


# ─── ClaudeDrafter (mocked anthropic client) ──────────────────────────────────


def test_claude_drafter_returns_valid_body():
    drafter = _make_claude_drafter([_VALID_BODY])
    body = drafter.draft_stub(_mk_input())
    assert _validate_body(body)
    assert drafter.calls == 1
    assert drafter.abstentions == 0


def test_claude_drafter_retries_on_invalid_structure():
    drafter = _make_claude_drafter([_INVALID_BODY, _VALID_BODY])
    body = drafter.draft_stub(_mk_input())
    assert _validate_body(body)
    assert drafter._client.messages.create.call_count == 2


def test_claude_drafter_abstains_when_all_retries_fail():
    drafter = _make_claude_drafter([_INVALID_BODY, _INVALID_BODY, _INVALID_BODY])
    body = drafter.draft_stub(_mk_input())
    assert _validate_body(body)
    assert "DRAFT FAILED" in body
    assert drafter.abstentions == 1


def test_claude_drafter_system_prompt_enforces_citation_discipline():
    drafter = _make_claude_drafter([_VALID_BODY])
    drafter.draft_stub(_mk_input())
    system = drafter._client.messages.create.call_args.kwargs["system"]
    assert "[^N]" in system or "footnote" in system.lower()


def test_claude_drafter_conforms_to_drafter_protocol():
    from wikilens.drafter import ClaudeDrafter, Drafter
    drafter = _make_claude_drafter([_VALID_BODY])
    assert isinstance(drafter, Drafter)
    assert drafter.name == "claude"


def test_claude_drafter_retry_adds_critical_instruction():
    """Second-attempt system prompt must include the CRITICAL retry instruction."""
    drafter = _make_claude_drafter([_INVALID_BODY, _VALID_BODY])
    drafter.draft_stub(_mk_input())
    calls = drafter._client.messages.create.call_args_list
    assert len(calls) == 2
    second_system = calls[1][1].get("system", "")
    assert "CRITICAL" in second_system
