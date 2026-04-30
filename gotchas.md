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

---

## G2 — LanceDB's `list_tables()` returns a paginated object, not a list

**Phase:** P2, step 7 (vector store)
**Date:** 2026-04-30

**Symptom:** After swapping the deprecated `db.table_names()` for `db.list_tables()`,
the reopen-and-keep-data test started failing. A second `LanceDBStore` instance on
the same path created a new empty table instead of opening the existing one.

**Root cause:** `table_names()` returns `list[str]`. `list_tables()` returns a
paginated wrapper object with a `.tables` attribute. `"name" in <paginated_object>`
is silently `False` because `__contains__` is not wired up for the wrapper.
Result: the existence check fell through and `create_table` ran instead of
`open_table`.

**Fix:** Unwrap defensively:
```python
raw = self._db.list_tables()
names = getattr(raw, "tables", raw)
if self._table_name in names:
    ...
```

**When this bites again:** Any time a LanceDB method returns a "Response"-style
paginated object in place of a plain collection. Rule of thumb: if the replacement
for a deprecated API breaks membership checks, inspect the object with `dir()`
before trusting it as iterable.
