"""On-disk verdict cache (M5) — stop re-paying compute/$ on unchanged inputs.

A re-run on an unchanged vault must cost ZERO LLM calls. This module is the
mechanism: a sqlite sidecar keyed by ``sha256`` over a canonical
``(family, model, prompt_version, system, user)`` tuple, storing the RAW
completion text *pre-parse*.

Storing raw text — never a typed verdict — keeps the cache agnostic to all six
agent families (contradict/gap/answer/drift/concepts/confidence) and their six
different return types, so this module imports no verdict-home module. The
per-call-site lambda (which knows the SDK response shape) normalises usage into
``RawCompletion`` so neither ``cache.py`` nor ``cost.py`` ever imports an SDK.

Design notes:
- ``family`` is the command/agent discriminator, NOT ``self.name``. Every
  networked backend shares the literal ``self.name`` of ``'openai'``/``'claude'``/
  ``'mock'`` across all six families; keying on it would silently replay one
  command's completion for another. ``family`` is the collision guard.
- ``PROMPT_VERSION`` is a key component, so bumping it invalidates EVERY cached
  entry at once. Bump it whenever a prompt template changes so stale completions
  are not replayed.
- ``CACHE_SCHEMA_VERSION`` is the internal sqlite schema version; it is
  orthogonal to the public ``JSON_SCHEMA_VERSION`` in ``contradict_format.py``.
- Mirrors ``manifest.py`` house style: version constant, sqlite sidecar, and
  graceful corruption handling (a broken cache degrades to "always miss", never
  crashes the run).

Stdlib-only at module top (``sqlite3``, ``hashlib``) so importing this never
pulls in sentence-transformers/lancedb/openai/anthropic (heavy-import deferral).
"""

from __future__ import annotations

import hashlib
import math
import sqlite3
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Lazy/forward-ref only: avoids any import cycle and keeps cost.py off the
    # import path at runtime. complete_with_cache_and_cost duck-types this.
    from wikilens.cost import CostContext

PROMPT_VERSION = 1
CACHE_SCHEMA_VERSION = 1
CACHE_FILENAME = "verdicts.sqlite3"

# ASCII unit separator: a byte that cannot appear in model/prompt text, so it
# cannot be forged inside a field to fake a boundary shift (collision guard).
_SEP = "\x1f"


@dataclass(frozen=True)
class RawCompletion:
    """One raw LLM completion plus normalised usage counts.

    Produced by the per-call-site lambda that knows the SDK response shape: it
    maps OpenAI ``prompt_tokens``/``completion_tokens`` and Claude
    ``input_tokens``/``output_tokens`` into these two ints *at the call site*,
    so ``cache.py`` and ``cost.py`` never import an SDK.
    """

    text: str
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class CacheKey:
    """The canonical cache key.

    ``family`` is the command/agent-family discriminator (e.g. ``contradict``,
    ``gap``, ``answer``, ``drift``, ``concepts``, ``confidence``) — NOT the
    backend ``self.name``, which is the shared ``openai``/``claude``/``mock``
    literal across all families. Using ``self.name`` as the only discriminator
    is the silent cross-family collision bug; ``family`` prevents it.
    """

    family: str
    model: str
    prompt_version: int
    system: str
    user: str

    def digest(self) -> str:
        """SHA-256 hexdigest over the unit-separator-joined key fields."""
        payload = _SEP.join(
            [
                self.family,
                self.model,
                str(self.prompt_version),
                self.system,
                self.user,
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_key(
    *,
    family: str,
    model: str,
    system: str,
    user: str,
    prompt_version: int = PROMPT_VERSION,
) -> CacheKey:
    """The single authoritative key constructor.

    Defined once here and never re-derived at call sites, so invalidation
    semantics are provably consistent across every networked backend class.
    """
    return CacheKey(
        family=family,
        model=model,
        prompt_version=prompt_version,
        system=system,
        user=user,
    )


class NullCache:
    """``--no-cache`` sentinel: always miss, never touch disk or network.

    Keeps ``complete_with_cache_and_cost`` branch-free — call sites use the same
    helper whether caching is on or off.
    """

    def get(self, key: CacheKey) -> str | None:
        return None

    def put(self, key: CacheKey, completion: str) -> None:
        return None

    def close(self) -> None:
        return None

    def __enter__(self) -> NullCache:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class VerdictCache:
    """sqlite-backed raw-completion cache.

    Opens (creating if needed) a sqlite file and an ``entries`` table. On a
    corrupt file it prints a stderr warning and degrades to "always miss" (the
    ``_degraded`` flag) rather than crashing the run.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._degraded = False
        self._conn: sqlite3.Connection | None = None
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS entries ("
                "key TEXT PRIMARY KEY, "
                "family TEXT, "
                "model TEXT, "
                "completion TEXT NOT NULL, "
                "created REAL)"
            )
            self._conn.commit()
        except sqlite3.DatabaseError as exc:
            # Mirror manifest.py: a broken cache must degrade, never crash.
            print(
                f"warning: verdict cache unusable, running without it: {exc}",
                file=sys.stderr,
            )
            self._degraded = True
            if self._conn is not None:
                self._conn.close()
            self._conn = None

    def get(self, key: CacheKey) -> str | None:
        """Return the cached completion text, or ``None`` on a miss."""
        if self._degraded or self._conn is None:
            return None
        row = self._conn.execute(
            "SELECT completion FROM entries WHERE key = ?", (key.digest(),)
        ).fetchone()
        return None if row is None else str(row[0])

    def put(self, key: CacheKey, completion: str) -> None:
        """Store ``completion`` for ``key`` (INSERT OR REPLACE).

        ``family``/``model``/``created`` are stored for observability and future
        selective invalidation; only ``completion`` is read back by ``get``.
        """
        if self._degraded or self._conn is None:
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO entries "
            "(key, family, model, completion, created) VALUES (?, ?, ?, ?, ?)",
            (key.digest(), key.family, key.model, completion, time.time()),
        )
        self._conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> VerdictCache:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def open_cache(no_cache: bool, db_dir: str | Path) -> VerdictCache | NullCache:
    """Return a ``NullCache`` when ``--no-cache``, else a ``VerdictCache``.

    The enabled path opens/creates ``<db_dir>/.wikilens/<CACHE_FILENAME>``. The
    ``NullCache`` path touches no disk and no network.
    """
    if no_cache:
        return NullCache()
    db_path = Path(db_dir) / ".wikilens" / CACHE_FILENAME
    return VerdictCache(db_path)


def estimate_prompt_tokens(*segments: str, overhead: int = 48) -> int:
    """Return a conservative upper bound on prompt tokens for budget gating."""
    if not segments:
        return overhead
    char_count = sum(len(part) for part in segments)
    approx_tokens = math.ceil(char_count / 3) if char_count else 0
    return max(1, approx_tokens + overhead)


def complete_with_cache_and_cost(
    fn: Callable[[], RawCompletion],
    key: CacheKey,
    *,
    cache: VerdictCache | NullCache,
    cost_ctx: CostContext,
    estimate: Callable[[], tuple[int, int]] | None = None,
) -> str:
    """Run ``fn`` through the verdict cache, budget gate, and cost accounting."""
    hit = cache.get(key)
    if hit is not None:
        cost_ctx.record_hit()
        return hit

    if estimate is not None:
        prompt_est, completion_est = estimate()
        prompt_est = int(prompt_est)
        completion_est = int(completion_est)
        if prompt_est < 0 or completion_est < 0:
            raise ValueError("token estimates must be non-negative")
        from wikilens.cost import estimate_usd as _estimate_usd

        cost_ctx.check_before_call(
            _estimate_usd(key.model, prompt_est, completion_est)
        )

    rc = fn()
    cost_ctx.record(
        family=key.family,
        model=key.model,
        prompt_tokens=rc.prompt_tokens,
        completion_tokens=rc.completion_tokens,
    )
    cache.put(key, rc.text)
    return rc.text
