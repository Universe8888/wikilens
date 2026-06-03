"""Tests for the cost accounting + budget cap module (M5).

Pure stdlib, no network. Covers the price table, USD estimation, the
provider-usage adapters (OpenAI vs Anthropic field names), the
CostContext accumulator, warm-cache hits, the pre-egress budget gate
(the invariant that matters most: abort BEFORE the call that would
exceed budget), and the unknown-model one-time warning.
"""

from __future__ import annotations

import wikilens.cost as cost_mod
from wikilens.cost import (
    PRICES,
    ZERO_PRICE,
    BudgetExceeded,
    CostContext,
    ModelPrice,
    Usage,
    estimate_usd,
    from_anthropic_usage,
    from_openai_usage,
)


class TestModelPriceTable:
    def test_prices_seed_the_two_centralized_defaults(self):
        # backends.DEFAULT_OPENAI_MODEL / DEFAULT_CLAUDE_MODEL
        assert "gpt-4o" in PRICES
        assert "claude-sonnet-4-6" in PRICES

    def test_model_price_is_frozen(self):
        from dataclasses import FrozenInstanceError

        import pytest

        p = ModelPrice(prompt_usd_per_1k=1.0, completion_usd_per_1k=2.0)
        with pytest.raises(FrozenInstanceError):
            p.prompt_usd_per_1k = 0.0  # type: ignore[misc]

    def test_zero_price_is_zero(self):
        assert ZERO_PRICE.prompt_usd_per_1k == 0.0
        assert ZERO_PRICE.completion_usd_per_1k == 0.0


class TestEstimateUsd:
    def test_known_model_uses_table(self):
        price = PRICES["gpt-4o"]
        expected = (
            1000 / 1000 * price.prompt_usd_per_1k
            + 2000 / 1000 * price.completion_usd_per_1k
        )
        assert estimate_usd("gpt-4o", 1000, 2000) == expected

    def test_zero_tokens_is_zero(self):
        assert estimate_usd("gpt-4o", 0, 0) == 0.0

    def test_unknown_model_returns_zero(self):
        # ZERO_PRICE fallback — never crashes.
        assert estimate_usd("some-future-model-xyz", 5000, 5000) == 0.0

    def test_estimate_is_pure_no_mutation(self):
        before = PRICES["gpt-4o"]
        estimate_usd("gpt-4o", 123, 456)
        assert PRICES["gpt-4o"] is before


class TestUsageAdapters:
    def test_usage_total_is_sum(self):
        u = Usage(prompt_tokens=10, completion_tokens=5)
        assert u.total_tokens == 15

    def test_usage_is_frozen(self):
        from dataclasses import FrozenInstanceError

        import pytest

        u = Usage(prompt_tokens=1, completion_tokens=1)
        with pytest.raises(FrozenInstanceError):
            u.prompt_tokens = 9  # type: ignore[misc]

    def test_from_openai_usage_field_names(self):
        # OpenAI: prompt_tokens / completion_tokens / total_tokens
        class _OAUsage:
            prompt_tokens = 100
            completion_tokens = 40
            total_tokens = 140

        u = from_openai_usage(_OAUsage())
        assert u.prompt_tokens == 100
        assert u.completion_tokens == 40
        assert u.total_tokens == 140

    def test_from_anthropic_usage_field_names(self):
        # Anthropic: input_tokens / output_tokens (no total_tokens field)
        class _AntUsage:
            input_tokens = 70
            output_tokens = 30

        u = from_anthropic_usage(_AntUsage())
        assert u.prompt_tokens == 70
        assert u.completion_tokens == 30
        assert u.total_tokens == 100

    def test_from_openai_usage_handles_none(self):
        u = from_openai_usage(None)
        assert u.prompt_tokens == 0
        assert u.completion_tokens == 0

    def test_from_anthropic_usage_handles_none(self):
        u = from_anthropic_usage(None)
        assert u.prompt_tokens == 0
        assert u.completion_tokens == 0


class TestCostContextRecording:
    def test_record_accumulates_calls_and_tokens(self):
        ctx = CostContext()
        ctx.record(family="contradict", model="gpt-4o", prompt_tokens=100, completion_tokens=50)
        ctx.record(family="contradict", model="gpt-4o", prompt_tokens=200, completion_tokens=60)
        import pytest

        assert ctx.calls == 2
        assert ctx.prompt_tokens == 300
        assert ctx.completion_tokens == 110
        # Accumulated per-call; equals the single-shot estimate within fp tolerance.
        assert ctx.usd == pytest.approx(estimate_usd("gpt-4o", 300, 110))

    def test_record_hit_does_not_change_spend(self):
        ctx = CostContext()
        ctx.record(family="contradict", model="gpt-4o", prompt_tokens=100, completion_tokens=50)
        spend_before = ctx.usd
        tokens_before = (ctx.prompt_tokens, ctx.completion_tokens)
        ctx.record_hit()
        ctx.record_hit()
        assert ctx.cached_calls == 2
        assert ctx.calls == 1  # unchanged — cache hits are not live calls
        assert ctx.usd == spend_before
        assert (ctx.prompt_tokens, ctx.completion_tokens) == tokens_before

    def test_unknown_model_records_zero_usd(self):
        ctx = CostContext()
        ctx.record(family="x", model="future-model", prompt_tokens=9999, completion_tokens=9999)
        assert ctx.usd == 0.0
        assert ctx.calls == 1


class TestBudgetGate:
    """The invariant that matters most: abort BEFORE the egress that would
    exceed budget. would_exceed()/check_before_call() are the pre-call gate;
    record() is honest post-call accounting."""

    def test_no_max_cost_never_exceeds(self):
        ctx = CostContext(max_cost=None)
        assert ctx.would_exceed(99999.0) is False
        ctx.check_before_call(99999.0)  # must not raise

    def test_would_exceed_true_when_next_call_crosses_cap(self):
        ctx = CostContext(max_cost=1.0)
        ctx.usd = 0.9
        assert ctx.would_exceed(0.2) is True
        assert ctx.would_exceed(0.05) is False

    def test_would_exceed_uses_committed_plus_next(self):
        ctx = CostContext(max_cost=1.0)
        assert ctx.would_exceed(1.5) is True
        assert ctx.would_exceed(1.0) is False  # exactly at cap is allowed

    def test_check_before_call_raises_before_egress(self):
        import pytest

        ctx = CostContext(max_cost=0.50)
        ctx.usd = 0.45
        with pytest.raises(BudgetExceeded) as exc:
            ctx.check_before_call(0.10)
        # The crossing call has NOT been recorded — spend stays at committed.
        assert ctx.usd == 0.45
        assert ctx.calls == 0
        assert exc.value.spent_usd == 0.45
        assert exc.value.max_cost == 0.50

    def test_check_before_call_passes_under_cap(self):
        ctx = CostContext(max_cost=1.0)
        ctx.usd = 0.3
        ctx.check_before_call(0.2)  # must not raise

    def test_budget_exceeded_is_leaf_exception(self):
        # Not a subclass of ValueError/RuntimeError the CLI may catch for findings.
        assert issubclass(BudgetExceeded, Exception)
        assert not issubclass(BudgetExceeded, ValueError)
        assert not issubclass(BudgetExceeded, RuntimeError)

    def test_budget_exceeded_carries_fields(self):
        e = BudgetExceeded(spent_usd=1.23, max_cost=1.0)
        assert e.spent_usd == 1.23
        assert e.max_cost == 1.0
        assert "1.23" in str(e) or "1.2" in str(e)


class TestUnknownModelWarning:
    def test_unknown_model_warns_once_to_stderr(self, capsys, monkeypatch):
        # Reset the module-level dedup set so the test is independent.
        monkeypatch.setattr(cost_mod, "_warned_models", set())
        estimate_usd("brand-new-model", 100, 100)
        estimate_usd("brand-new-model", 100, 100)
        err = capsys.readouterr().err
        # Exactly one warning line for the model, repeated calls do not re-warn.
        assert err.count("brand-new-model") == 1

    def test_unknown_model_warning_goes_to_stderr_not_stdout(self, capsys, monkeypatch):
        monkeypatch.setattr(cost_mod, "_warned_models", set())
        estimate_usd("another-unknown", 50, 50)
        captured = capsys.readouterr()
        assert captured.out == ""  # stdout stays machine-readable (INV2)
        assert "another-unknown" in captured.err

    def test_known_model_does_not_warn(self, capsys, monkeypatch):
        monkeypatch.setattr(cost_mod, "_warned_models", set())
        estimate_usd("gpt-4o", 100, 100)
        assert capsys.readouterr().err == ""


class TestFooter:
    def test_footer_reports_live_and_cached_calls(self):
        ctx = CostContext()
        ctx.record(family="c", model="gpt-4o", prompt_tokens=100, completion_tokens=50)
        ctx.record_hit()
        line = ctx.footer()
        assert "1 live call" in line
        assert "1 cached" in line
        assert "100 prompt" in line
        assert "50 completion" in line
        assert "$" in line

    def test_footer_zero_for_mock_path(self):
        # --judge none never calls record() — footer shows 0 live / $0.0000.
        ctx = CostContext()
        line = ctx.footer()
        assert "0 live call" in line
        assert "$0.0000" in line

    def test_footer_is_single_line(self):
        ctx = CostContext()
        assert "\n" not in ctx.footer()


class TestModuleTopImportPurity:
    """INV6: cost.py must only use stdlib at module top — no heavy SDK imports."""

    def test_no_forbidden_module_imports(self):
        import ast
        import pathlib

        src = pathlib.Path(cost_mod.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        forbidden = {
            "openai",
            "anthropic",
            "sentence_transformers",
            "lancedb",
            "numpy",
        }
        top_imports: set[str] = set()
        for node in tree.body:  # module-top statements only
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_imports.add(node.module.split(".")[0])
        assert forbidden.isdisjoint(top_imports), top_imports
        # No wikilens backend module imports at top level either.
        assert "wikilens" not in top_imports


class TestNoJsonSerializer:
    """cost.py deliberately exposes NO JSON-stats serializer (INV4 guard)."""

    def test_no_json_stats_function(self):
        # Cost must reach the user only via footer() -> stderr, never JSON.
        assert not hasattr(cost_mod, "to_json")
        assert not hasattr(cost_mod, "as_stats")
        assert not hasattr(cost_mod, "json_stats")
