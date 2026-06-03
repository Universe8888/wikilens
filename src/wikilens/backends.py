"""Centralized LLM backend resolution and model defaults.

Every CLI command that needs an LLM judge/generator/drafter goes through
resolve_backend() instead of its own if/elif/else ladder. Model constants
are defined exactly once here.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from wikilens.cache import NullCache, VerdictCache
    from wikilens.cost import CostContext

DEFAULT_OPENAI_MODEL = "gpt-4o"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"

_AGENT_REGISTRY: dict[str, dict[str, tuple[str, str]]] = {
    "contradict": {
        "none": ("wikilens.judge", "MockJudge"),
        "openai": ("wikilens.judge", "OpenAIJudge"),
        "claude": ("wikilens.judge", "ClaudeJudge"),
    },
    "gap": {
        "none": ("wikilens.generator", "MockGenerator"),
        "openai": ("wikilens.generator", "OpenAIGenerator"),
        "claude": ("wikilens.generator", "ClaudeGenerator"),
    },
    "answer": {
        "none": ("wikilens.drafter", "MockDrafter"),
        "openai": ("wikilens.drafter", "OpenAIDrafter"),
        "claude": ("wikilens.drafter", "ClaudeDrafter"),
    },
    "drift": {
        "none": ("wikilens.drift_judge", "MockDriftJudge"),
        "openai": ("wikilens.drift_judge", "OpenAIDriftJudge"),
        "claude": ("wikilens.drift_judge", "ClaudeDriftJudge"),
    },
    "concepts": {
        "none": ("wikilens.concept_judge", "MockConceptJudge"),
        "openai": ("wikilens.concept_judge", "OpenAIConceptJudge"),
        "claude": ("wikilens.concept_judge", "ClaudeConceptJudge"),
    },
    "confidence": {
        "none": ("wikilens.confidence_judge", "MockConfidenceJudge"),
        "openai": ("wikilens.confidence_judge", "OpenAIConfidenceJudge"),
        "claude": ("wikilens.confidence_judge", "ClaudeConfidenceJudge"),
    },
}


def resolve_backend(
    command: str,
    judge_kind: str,
    *,
    model: str | None = None,
    cache: VerdictCache | NullCache | None = None,
    cost_ctx: CostContext | None = None,
) -> tuple[Any, int | None]:
    """Resolve and instantiate the correct backend for a CLI command.

    Returns (backend_instance, None) on success, or (None, exit_code) on failure.
    The exit_code is always 2 (bad input / config error).

    ``cache`` and ``cost_ctx`` are threaded into networked backends only.
    Mock backends (``judge_kind == "none"``) never receive them — structurally
    guaranteeing zero egress and zero cost accounting on the ``--judge none`` path.
    """
    registry = _AGENT_REGISTRY.get(command)
    if registry is None:
        print(f"wikilens {command}: unknown command for backend resolution", file=sys.stderr)
        return None, 2

    if judge_kind == "ollama":
        print(
            f"wikilens {command}: --judge ollama is not yet implemented. "
            "Use --judge none, --judge openai, or --judge claude.",
            file=sys.stderr,
        )
        return None, 2

    entry = registry.get(judge_kind)
    if entry is None:
        print(f"wikilens {command}: unknown judge: {judge_kind!r}", file=sys.stderr)
        return None, 2

    module_path, class_name = entry

    if judge_kind == "none":
        import importlib

        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        return cls(), None

    default_model = DEFAULT_OPENAI_MODEL if judge_kind == "openai" else DEFAULT_CLAUDE_MODEL
    effective_model = model or default_model

    try:
        import importlib

        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        return cls(model=effective_model, cache=cache, cost_ctx=cost_ctx), None
    except (OSError, ImportError) as e:
        print(f"wikilens {command}: {e}", file=sys.stderr)
        return None, 2
