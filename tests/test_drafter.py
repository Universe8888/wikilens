"""Tests for the Drafter protocol and MockDrafter (P6.1 step 2).

OpenAIDrafter and ClaudeDrafter are tested in Phase 6.2 with mocked SDK
clients. This file covers the protocol contract, MockDrafter behaviour,
and the structural validator so Phase 6.2 tests can reuse those helpers.
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
