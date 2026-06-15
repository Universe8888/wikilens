#!/usr/bin/env python3
"""Pre-fetch the BGE models the test suite needs, with retry on transient errors.

CI ingests vaults, which downloads two ~270 MB models from HuggingFace. A
transient HF rate-limit (HTTP 429) or 5xx during that download would error the
model-dependent tests at setup, drop coverage below the gate, and red-fail an
otherwise-green build. This script fetches both models up front and retries the
download with exponential backoff so a flaky HF response doesn't fail the build.

It is a no-op when the models are already cached (e.g. restored from the CI
cache), and it fails loudly with a clear message only after exhausting retries.
"""

from __future__ import annotations

import sys
import time

# The two models the pipeline loads (embedder + reranker). Keep in sync with
# README install notes and src/wikilens/embed.py / rerank.py.
MODELS = ["BAAI/bge-small-en-v1.5", "BAAI/bge-reranker-base"]

MAX_ATTEMPTS = 4
BASE_DELAY_SECONDS = 5.0


def _is_transient(exc: Exception) -> bool:
    """True if the error looks like a retryable HF/network hiccup (429, 5xx, conn)."""
    text = f"{type(exc).__name__}: {exc}".lower()
    signals = ("429", "too many requests", "timeout", "timed out",
               "connection", "temporarily", "503", "502", "500", "504")
    return any(s in text for s in signals)


def _fetch(model_id: str) -> str:
    from huggingface_hub import snapshot_download

    return snapshot_download(model_id)


def main() -> int:
    for model_id in MODELS:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                path = _fetch(model_id)
                print(f"OK  {model_id} -> {path}")
                break
            except Exception as exc:  # noqa: BLE001 - we classify and re-raise below
                last = attempt == MAX_ATTEMPTS
                if last or not _is_transient(exc):
                    print(
                        f"FAIL {model_id}: {type(exc).__name__}: {exc}",
                        file=sys.stderr,
                    )
                    return 1
                delay = BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                print(
                    f"transient error fetching {model_id} "
                    f"(attempt {attempt}/{MAX_ATTEMPTS}): {exc}\n"
                    f"  retrying in {delay:.0f}s ...",
                    file=sys.stderr,
                )
                time.sleep(delay)
    print(f"All {len(MODELS)} model(s) present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
