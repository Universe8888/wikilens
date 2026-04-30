# Gotchas

Failure-driven learning register. One entry per class of mistake, so the same bug doesn't get paid for twice.

---

## G1 — `sentence-transformers>=5.0` pulls in `torchcodec`, breaks on Windows

**Phase:** P2, step 1 (install deps)
**Date:** 2026-04-30

**Symptom:** `import sentence_transformers` fails with
`RuntimeError: Could not load libtorchcodec` and a stack of `libtorchcodec_coreN.dll`
load failures.

**Root cause:** Starting with the 5.x line, `sentence-transformers` added `torchcodec`
as a hard dependency to support multi-modal (audio/video) encoding. `torchcodec` ships
a native library that dynamically loads FFmpeg shared libs at import time. On Windows,
without FFmpeg DLLs discoverable on the DLL search path, the module import itself fails
— even if you only want text embeddings.

**Fix:** Pin `sentence-transformers>=3.0,<5.0` in `pyproject.toml`. The 4.x line is
text-only and has no `torchcodec` edge.

**When this bites again:** Any time a transitive dep forces an upgrade past 5.0, or a
new contributor relaxes the upper bound "because 5.x is out." Keep the cap until we
actually need multi-modal and have FFmpeg handled.
