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

---

## G3 — Frontmatter regex catastrophic backtracking on flow-style YAML lists

**Phase:** P2, step 11 (sample vault smoke ingest)
**Date:** 2026-04-30

**Symptom:** `parse_note()` hung indefinitely on tiny (~1 KB) markdown files
whose YAML frontmatter contained a flow-style list such as
`tags: [chemistry]`. `pytest` passed because the test fixtures happened to
avoid the pathological input shape. The diagnostic log file stayed empty — no
exception, no output, just a pegged CPU core inside `re.match`.

**Root cause:** The original pattern used a nested lazy quantifier under
`re.DOTALL`:

```python
re.compile(
    r"\A---[ \t]*\r?\n(?P<fm>(?:.*\r?\n)*?)---[ \t]*\r?\n?(?P<body>.*)\Z",
    re.DOTALL,
)
```

The inner `(?:.*\r?\n)*?` is a classic catastrophic-backtracking construct:
`.*` under DOTALL can match newlines, and the engine retries every way to
partition the file when the closing fence is not exactly where the lazy
expansion first lands. Certain body content (square-bracketed tokens like
`[chemistry]`, `[0 to 14]`) triggered an exponential blow-up.

**Fix:** Replaced the regex with a line-based O(n) scanner in
`parse_frontmatter()` — check for `---` at position 0, split on lines once,
walk forward for the next line whose `rstrip()` equals `---`. No regex, no
backtracking. Two regression tests cover (a) the exact failing input, with a
100ms wall-clock bound, and (b) the unterminated-fence edge case.

**When this bites again:** Any time a regex uses a nested quantifier where
both the outer and inner can match the same characters (`(.*\n)*`, `(.+)+`,
`(a|a)*`). If the pattern must consume lines up to a delimiter, split on
lines first and scan — it's O(n) by construction. Watch especially for this
when `re.DOTALL` is in play, because `.` matching newlines removes the usual
one-line-at-a-time anchor that makes `(.*\n)*` safe in practice.

---

## G4 — Reciprocity check on a directed graph was always-true

**Phase:** P3, step 3.2 (detectors)
**Date:** 2026-04-30

**Symptom:** `find_one_way_links()` returned an empty list on a fixture
that clearly had one-way edges. The bug would have silently shipped if not
for a pair of unit tests (`test_find_one_way_links`,
`test_audit_vault_composes_everything`) that hard-coded an expected count.

**Root cause:** The inbound map is built from outbound edges: if A links to
B, `inbound[B]` includes A. So checking "is source in `inbound[target]`?"
is trivially true *for every resolved link* and can never surface a
one-way. The correct reciprocity check asks the symmetric question —
"is target in `inbound[source]`?" — i.e., does the target also link back
to the source.

**Fix:** One-line swap in `find_one_way_links` from
`source not in graph.inbound.get(target, ())` to
`target not in graph.inbound.get(source, ())`. The tests flipped green on
the next run.

**When this bites again:** Any time you write a reciprocity / symmetry
check over a directed graph. The `inbound[x]` map by construction lists
every node that links *to* x, so querying it with the source side of the
edge you just added is a tautology. Before writing the check, say the
requirement in plain English: "does the target link back to the source?"
— then encode that literal sentence, not the mirror of it.

---

## G5 — `LanceTable.to_list()` doesn't exist; use `to_arrow().to_pylist()`

**Phase:** P4, step 4 (candidate pair generation)
**Date:** 2026-04-30

**Symptom:** `generate_candidate_pairs` raised
`AttributeError: 'LanceTable' object has no attribute 'to_list'` the
first time the CLI end-to-end test hit a real ingested store. The
`to_list()` method works on the query-result builder returned by
`table.search(...).limit(k)`, so the name looked plausible on
`Table` too — it isn't.

**Root cause:** In `lancedb==0.30.2`, `Table` has no `to_list()`
method. `to_list()` lives on the query-result object, not the table.
For an unfiltered full-table scan the canonical materialization is
`table.to_arrow().to_pylist()` (Arrow table → list of dicts). This
matters because existing P2 code touches tables almost exclusively
through `.search(...)` paths, so the full-scan primitive never came
up until P4 needed to walk every chunk to generate pairs.

**Fix:** In `src/wikilens/contradict.py::_iter_all_chunks`,
`table.to_list()` → `table.to_arrow().to_pylist()`. Unit and CLI
end-to-end tests both flipped green on the next run.

**When this bites again:** Any time you need a full scan of a
LanceDB table and reach for a `.to_list()`-style shortcut. The
Arrow detour (`to_arrow().to_pylist()`) is the stable path. If a
future version adds `Table.to_list()` directly, treat that as a
nice-to-have simplification, not a bug fix — the Arrow form keeps
working regardless.
