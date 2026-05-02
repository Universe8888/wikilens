"""P6 eval harness — Answer Generator quality against gold answer sketches.

Four-axis LLM-judge evaluation + automated attribution check:

1. **Faithfulness** (1-5): every cited sentence is actually supported by the
   chunk it cites.  Threshold >= 4 per draft.
2. **Coverage** (1-5): draft addresses the gold sketch's key claims.
   Threshold >= 4 per draft.
3. **Attribution quality** (1-5): citations land on the strongest available
   evidence.  Threshold >= 4 per draft.
4. **Stub structure** (1-5): frontmatter complete, sections in order, no prose
   outside expected sections.  Threshold >= 4 per draft.

Pass = draft scores >= threshold on ALL four axes.
Headline metric: **pass rate** = drafts_passing_all_4 / drafts_attempted.

Also reports:
- **Attribution rate** (automated, no LLM): cited_sentences / total_sentences
  in "What the vault says".  Target >= 0.90.
- **Skip rate**: gaps with external-research or skipped drafts.

Borderline decisions (any axis scores exactly 3) are written to
docs/p6-judge-notes.md for human review (matches P5's borderline-decision
pattern).

Usage:
    # dry-run (MockDrafter + no judge calls):
    python scripts/eval_p6.py --judge none

    # full eval with OpenAI:
    python scripts/eval_p6.py --judge openai

    # full eval with Claude:
    python scripts/eval_p6.py --judge claude

    # cap drafts for smoke run:
    python scripts/eval_p6.py --judge openai --sample 3

Outputs:
    - Metrics table + per-draft axis scores to stdout.
    - Timestamped section appended to BENCHMARK.md.
    - Borderline judge decisions appended to docs/p6-judge-notes.md.

Exit code: 0 if pass_rate >= 0.80 and attr_rate >= 0.90 (or --judge none), else 1.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRUTH_DEFAULT = REPO_ROOT / "fixtures" / "eval" / "p5_ground_truth.json"
SKETCHES_DEFAULT = REPO_ROOT / "fixtures" / "eval" / "p6_answer_sketches.json"
VAULT_DEFAULT = REPO_ROOT / "fixtures" / "gaps_vault"
DB_DEFAULT = REPO_ROOT / ".wikilens_p5_eval" / "db"
BENCHMARK_DEFAULT = REPO_ROOT / "BENCHMARK.md"
JUDGE_NOTES_DEFAULT = REPO_ROOT / "docs" / "p6-judge-notes.md"

PASS_RATE_THRESHOLD = 0.80
ATTR_RATE_THRESHOLD = 0.90
AXIS_THRESHOLD = 4
BORDERLINE_SCORE = 3


# ─── Judge prompt ─────────────────────────────────────────────────────────────

_JUDGE_SYSTEM_PROMPT = """\
You are an evaluator assessing the quality of a generated knowledge-base note stub.

You will be given:
1. A GAP QUESTION the stub attempts to answer.
2. The stub's BODY MARKDOWN (four sections: What the vault says, Evidence gaps,
   Related notes, Citations).
3. SUPPORTING CHUNKS that were retrieved from the vault and given to the drafter.
4. GOLD KEY CLAIMS: 3-5 claims a competent stub should cover.

Score the stub on FOUR axes, each 1-5:

FAITHFULNESS (1-5):
  5 = every cited sentence in "What the vault says" is fully supported by the
      chunk it cites; no invented facts.
  4 = one minor unsupported nuance; all core claims are supported.
  3 = some sentences make claims the cited chunk does not support.
  2 = multiple sentences contradict or exceed the cited chunks.
  1 = majority of cited sentences are not supported by their citations.

COVERAGE (1-5):
  A claim is covered if it appears in EITHER "What the vault says" (synthesized
  from chunks) OR "Evidence gaps" (explicitly listed as needing research).
  A stub that correctly identifies a claim as missing from the vault and lists
  it in Evidence gaps is COVERING that claim — documenting what's needed IS the
  answer-skeleton work.
  5 = all gold key claims appear in What the vault says OR Evidence gaps.
  4 = most key claims covered; one minor claim absent from both sections.
  3 = several key claims absent from both sections.
  2 = most key claims absent from both sections.
  1 = stub addresses neither What the vault says nor Evidence gaps meaningfully.

ATTRIBUTION_QUALITY (1-5):
  5 = every citation points to the strongest available evidence in the chunk set.
  4 = citations are appropriate; one could be improved.
  3 = citations present but some point at loosely-related chunks.
  2 = several citations are clearly pointing at the wrong evidence.
  1 = citations are noise or fabricated.

STUB_STRUCTURE (1-5):
  5 = frontmatter present, all four sections in order, no prose outside sections.
  4 = one minor formatting issue (e.g., extra blank line, slightly wrong header).
  3 = section missing or out of order, but content is mostly there.
  2 = multiple structural problems.
  1 = stub is malformed.

Respond with ONLY valid JSON in this exact shape (no markdown fences):
{
  "faithfulness": <1-5>,
  "coverage": <1-5>,
  "attribution_quality": <1-5>,
  "stub_structure": <1-5>,
  "rationale": "<one sentence per axis, pipe-separated: faith|cov|attr|struct>"
}
"""

_JUDGE_USER_TEMPLATE = """\
GAP QUESTION: {gap_question}

GOLD KEY CLAIMS:
{key_claims}

SUPPORTING CHUNKS ({n_chunks} chunks):
{passages}

STUB BODY:
{body}
"""


@dataclass
class JudgeScore:
    gap_id: str
    faithfulness: int
    coverage: int
    attribution_quality: int
    stub_structure: int
    rationale: str

    @property
    def passes(self) -> bool:
        return (
            self.faithfulness >= AXIS_THRESHOLD
            and self.coverage >= AXIS_THRESHOLD
            and self.attribution_quality >= AXIS_THRESHOLD
            and self.stub_structure >= AXIS_THRESHOLD
        )

    @property
    def is_borderline(self) -> bool:
        """Any axis scores exactly BORDERLINE_SCORE."""
        return BORDERLINE_SCORE in (
            self.faithfulness,
            self.coverage,
            self.attribution_quality,
            self.stub_structure,
        )


def _git_rev() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT, stderr=subprocess.DEVNULL, text=True,
        ).strip() or "unknown"
    except Exception:
        return "unknown"


def _format_passages(chunks: list) -> str:
    parts = []
    for chunk in chunks:
        snippet = chunk.text.strip().replace("\n", " ")
        if len(snippet) > 400:
            snippet = snippet[:400] + "..."
        parts.append(f"[{chunk.chunk_id}] ({chunk.source_rel})\n{snippet}")
    return "\n\n".join(parts)


def _format_key_claims(claims: list[str]) -> str:
    return "\n".join(f"- {c}" for c in claims)


def _parse_judge_response(raw: str) -> tuple[int, int, int, int, str]:
    """Parse judge JSON → (faithfulness, coverage, attribution_quality, structure, rationale)."""
    raw = raw.strip()
    # Strip markdown fences if the model disobeyed.
    if raw.startswith("```"):
        raw = "\n".join(
            line for line in raw.splitlines()
            if not line.startswith("```")
        )
    doc = json.loads(raw)
    return (
        int(doc["faithfulness"]),
        int(doc["coverage"]),
        int(doc["attribution_quality"]),
        int(doc["stub_structure"]),
        str(doc.get("rationale", "")),
    )


# ─── Judge backends ──────────────────────────────────────────────────────────


class MockJudge:
    name = "mock"

    def score(self, gap_id: str, gap_question: str, key_claims: list[str],
              passages_text: str, body: str) -> JudgeScore:
        return JudgeScore(
            gap_id=gap_id,
            faithfulness=4,
            coverage=4,
            attribution_quality=4,
            stub_structure=4,
            rationale="mock|mock|mock|mock",
        )


class OpenAIJudge:
    name = "openai"

    def __init__(self, model: str = "gpt-4o"):
        import os

        from wikilens._env import load_dotenv_if_present
        load_dotenv_if_present()
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise OSError("OPENAI_API_KEY not set")
        try:
            import openai as _openai
        except ImportError as e:
            raise ImportError("pip install -e '.[judge]'") from e
        self._client = _openai.OpenAI(api_key=api_key)
        self._model = model
        self.calls = 0
        self.abstentions = 0

    def score(self, gap_id: str, gap_question: str, key_claims: list[str],
              passages_text: str, body: str) -> JudgeScore:
        self.calls += 1
        user_msg = _JUDGE_USER_TEMPLATE.format(
            gap_question=gap_question,
            key_claims=_format_key_claims(key_claims),
            n_chunks=passages_text.count("\n\n") + 1 if passages_text else 0,
            passages=passages_text,
            body=body,
        )
        for attempt in range(3):
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    max_tokens=256,
                    messages=[
                        {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                )
                raw = resp.choices[0].message.content.strip()
                f, c, a, s, r = _parse_judge_response(raw)
                return JudgeScore(gap_id=gap_id, faithfulness=f, coverage=c,
                                  attribution_quality=a, stub_structure=s, rationale=r)
            except Exception as e:
                if attempt == 2:
                    self.abstentions += 1
                    return JudgeScore(gap_id=gap_id, faithfulness=1, coverage=1,
                                     attribution_quality=1, stub_structure=1,
                                     rationale=f"judge error: {e}|—|—|—")
        raise AssertionError("unreachable")


class ClaudeJudge:
    name = "claude"

    def __init__(self, model: str = "claude-sonnet-4-6"):
        import os

        from wikilens._env import load_dotenv_if_present
        load_dotenv_if_present()
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise OSError("ANTHROPIC_API_KEY not set")
        try:
            import anthropic as _anthropic
        except ImportError as e:
            raise ImportError("pip install -e '.[judge]'") from e
        self._client = _anthropic.Anthropic(api_key=api_key)
        self._model = model
        self.calls = 0
        self.abstentions = 0

    def score(self, gap_id: str, gap_question: str, key_claims: list[str],
              passages_text: str, body: str) -> JudgeScore:
        self.calls += 1
        user_msg = _JUDGE_USER_TEMPLATE.format(
            gap_question=gap_question,
            key_claims=_format_key_claims(key_claims),
            n_chunks=passages_text.count("\n\n") + 1 if passages_text else 0,
            passages=passages_text,
            body=body,
        )
        for attempt in range(3):
            try:
                resp = self._client.messages.create(
                    model=self._model,
                    max_tokens=256,
                    system=_JUDGE_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_msg}],
                )
                raw = resp.content[0].text.strip()
                f, c, a, s, r = _parse_judge_response(raw)
                return JudgeScore(gap_id=gap_id, faithfulness=f, coverage=c,
                                  attribution_quality=a, stub_structure=s, rationale=r)
            except Exception as e:
                if attempt == 2:
                    self.abstentions += 1
                    return JudgeScore(gap_id=gap_id, faithfulness=1, coverage=1,
                                     attribution_quality=1, stub_structure=1,
                                     rationale=f"judge error: {e}|—|—|—")
        raise AssertionError("unreachable")


# ─── Output formatters ───────────────────────────────────────────────────────


def format_metrics_table(
    scores: list[JudgeScore],
    attr_rates: list[float],
    n_skipped: int,
    n_total: int,
) -> str:
    if not scores:
        return "No drafts judged."
    n = len(scores)
    n_pass = sum(1 for s in scores if s.passes)
    pass_rate = n_pass / n
    mean_faith = sum(s.faithfulness for s in scores) / n
    mean_cov = sum(s.coverage for s in scores) / n
    mean_attr_q = sum(s.attribution_quality for s in scores) / n
    mean_struct = sum(s.stub_structure for s in scores) / n
    mean_attr_rate = sum(attr_rates) / len(attr_rates) if attr_rates else 0.0
    skip_rate = n_skipped / n_total if n_total else 0.0

    lines = [
        f"Pass rate (all 4 axes >= {AXIS_THRESHOLD}): {n_pass}/{n} = {pass_rate:.2f}",
        f"Skip / external-research rate: {n_skipped}/{n_total} = {skip_rate:.2f}",
        f"Attribution rate (automated): {mean_attr_rate:.2f}  (target >= {ATTR_RATE_THRESHOLD})",
        "",
        "| gap_id | faith | cov | attr_q | struct | pass |",
        "|--------|-------|-----|--------|--------|------|",
    ]
    for s in scores:
        p = "✓" if s.passes else "✗"
        lines.append(
            f"| {s.gap_id:<35} | {s.faithfulness} | {s.coverage} "
            f"| {s.attribution_quality} | {s.stub_structure} | {p} |"
        )
    lines += [
        "",
        f"| **mean** | {mean_faith:.1f} | {mean_cov:.1f} "
        f"| {mean_attr_q:.1f} | {mean_struct:.1f} | — |",
    ]
    return "\n".join(lines)


def write_benchmark_md(
    table: str,
    vault: Path,
    n_gaps: int,
    n_judged: int,
    n_skipped: int,
    drafter_name: str,
    judge_name: str,
    elapsed_s: float,
    path: Path,
) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    section = (
        f"\n## {timestamp} — P6 eval ({_git_rev()})\n\n"
        f"- Vault: `{vault.as_posix()}` ({n_gaps} gaps evaluated).\n"
        f"- Drafter: `{drafter_name}`. Judge: `{judge_name}`.\n"
        f"- Judged: {n_judged}. Skipped: {n_skipped}.\n"
        f"- Wall clock: {elapsed_s:.1f}s.\n\n"
        f"{table}\n"
    )
    header_entry = (
        "- **Answer generator** (`fixtures/gaps_vault/` + "
        "`fixtures/eval/p6_answer_sketches.json`):\n"
        "  ```\n"
        "  wikilens ingest fixtures/gaps_vault --db .wikilens_p5_eval/db\n"
        "  python scripts/eval_p6.py --judge openai\n"
        "  ```\n"
    )
    if path.exists():
        prior = path.read_text(encoding="utf-8")
        anchor = "Each harness **appends**"
        if anchor in prior and "eval_p6.py" not in prior:
            prior = prior.replace(anchor, header_entry + "\n" + anchor, 1)
        marker = "\n## "
        idx = prior.find(marker)
        preamble = prior[:idx] if idx >= 0 else prior
        body = prior[idx:] if idx >= 0 else ""
        path.write_text(preamble + section + body, encoding="utf-8")
    else:
        path.write_text(section, encoding="utf-8")


def write_judge_notes(
    borderline: list[tuple[JudgeScore, str]],
    path: Path,
    run_ts: str,
    git_rev: str,
) -> None:
    """Append borderline judge decisions to docs/p6-judge-notes.md."""
    if not borderline:
        return
    lines = [f"\n## {run_ts} ({git_rev}) — {len(borderline)} borderline decision(s)\n"]
    for score, gap_question in borderline:
        lines.append(f"### gap_id: `{score.gap_id}`")
        lines.append(f"- **Question:** {gap_question}")
        lines.append(f"- **Scores:** faithfulness={score.faithfulness} "
                     f"coverage={score.coverage} "
                     f"attribution_quality={score.attribution_quality} "
                     f"stub_structure={score.stub_structure}")
        lines.append(f"- **Rationale:** {score.rationale}")
        lines.append("")
    content = "\n".join(lines)
    if path.exists():
        path.write_text(path.read_text(encoding="utf-8") + content, encoding="utf-8")
    else:
        header = (
            "# P6 Judge Borderline Decisions\n\n"
            "Decisions where any axis scored 3 (borderline zone). "
            "Reviewed after each eval run to assess rubric quality.\n"
        )
        path.write_text(header + content, encoding="utf-8")


# ─── Main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--truth", type=Path, default=TRUTH_DEFAULT,
                   help="Path to p5_ground_truth.json (canonical 10-gap eval set)")
    p.add_argument("--sketches", type=Path, default=SKETCHES_DEFAULT,
                   help="Path to p6_answer_sketches.json")
    p.add_argument("--vault", type=Path, default=VAULT_DEFAULT)
    p.add_argument("--db", type=Path, default=DB_DEFAULT)
    p.add_argument(
        "--judge", choices=["none", "openai", "claude"], default="openai",
        help="Drafter + judge backend. 'none' uses mocks (no API calls).",
    )
    p.add_argument("--model", default=None,
                   help="Model for both drafter and judge (default: gpt-4o for openai, "
                        "claude-sonnet-4-6 for claude).")
    p.add_argument("--top-k", dest="top_k", type=int, default=8)
    p.add_argument("--retrieval-mode", dest="retrieval_mode",
                   choices=["dense", "bm25", "hybrid", "rerank"], default="rerank")
    p.add_argument("--min-supporting", dest="min_supporting", type=int, default=2)
    p.add_argument("--sample", type=int, default=None,
                   help="Cap total drafts (smoke mode).")
    p.add_argument("--benchmark", type=Path, default=BENCHMARK_DEFAULT)
    p.add_argument("--judge-notes", type=Path, default=JUDGE_NOTES_DEFAULT)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    import contextlib
    with contextlib.suppress(AttributeError, OSError):
        sys.stdout.reconfigure(encoding="utf-8")

    # ── Load sketches ──────────────────────────────────────────────────────
    sketches_path = args.sketches.resolve()
    if not sketches_path.exists():
        print(f"ERROR: sketches not found: {sketches_path}", file=sys.stderr)
        return 2
    sketch_doc = json.loads(sketches_path.read_text(encoding="utf-8"))
    sketch_map: dict[str, dict] = {s["gap_id"]: s for s in sketch_doc["sketches"]}
    print(f"[sketches] {len(sketch_map)} gold sketches loaded")

    # ── Ingest + store ─────────────────────────────────────────────────────
    from wikilens.embed import BGEEmbedder
    from wikilens.pipeline import ingest_vault
    from wikilens.store import LanceDBStore

    print(f"[ingest] {args.vault}")
    embedder = BGEEmbedder()
    ingest_vault(vault_root=args.vault, db_path=str(args.db), embedder=embedder)
    store = LanceDBStore(db_path=str(args.db), dim=embedder.dim)

    # Reranker for rerank mode.
    reranker = None
    if args.retrieval_mode == "rerank":
        from wikilens.rerank import BGEReranker
        reranker = BGEReranker()

    # ── Drafter ────────────────────────────────────────────────────────────
    from wikilens.drafter import Drafter

    if args.judge == "none":
        from wikilens.drafter import MockDrafter
        drafter: Drafter = MockDrafter()
        drafter_model = "mock"
    elif args.judge == "openai":
        from wikilens.drafter import DEFAULT_OPENAI_MODEL, OpenAIDrafter
        model = args.model or DEFAULT_OPENAI_MODEL
        try:
            drafter = OpenAIDrafter(model=model)
        except (OSError, ImportError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
        drafter_model = model
    else:
        from wikilens.drafter import DEFAULT_CLAUDE_MODEL, ClaudeDrafter
        model = args.model or DEFAULT_CLAUDE_MODEL
        try:
            drafter = ClaudeDrafter(model=model)
        except (OSError, ImportError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
        drafter_model = model

    # ── Judge ──────────────────────────────────────────────────────────────
    if args.judge == "none":
        judge = MockJudge()
    elif args.judge == "openai":
        judge_model = args.model or "gpt-4o"
        try:
            judge = OpenAIJudge(model=judge_model)
        except (OSError, ImportError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
    else:
        judge_model = args.model or "claude-sonnet-4-6"
        try:
            judge = ClaudeJudge(model=judge_model)
        except (OSError, ImportError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2

    # ── Build GapInput list from p5_ground_truth.json ────────────────────
    # Use the canonical 10 gold gaps directly instead of the 16-finding
    # p6_input_gaps.json, which was generated by a fresh gap run and uses
    # different suggested_note_title values.  The gold gaps have stable
    # gap_ids that match p6_answer_sketches.json 1:1.
    from wikilens.answer import GapInput, draft_answers

    truth_path = args.truth.resolve()
    if not truth_path.exists():
        print(f"ERROR: ground truth not found: {truth_path}", file=sys.stderr)
        return 2
    truth_doc = json.loads(truth_path.read_text(encoding="utf-8"))
    eval_gaps: list[GapInput] = []
    for g in truth_doc["gaps"]:
        eval_gaps.append(GapInput(
            cluster_id=0,
            cluster_size=0,
            gap_question=g["gold_question"],
            suggested_note_title=g["gap_id"],
            rationale=g.get("notes", ""),
            # Drop p5 supporting_chunk_ids — those were generated under the
            # old 16-char ID scheme.  Retrieval alone produces correct results
            # with the current 32-char SHA-256 IDs.
            supporting_chunk_ids=(),
        ))
    print(f"[truth] {len(eval_gaps)} gold gaps loaded from {truth_path.name}")

    def _find_sketch(gap: GapInput) -> dict | None:
        return sketch_map.get(gap.suggested_note_title)

    if args.sample:
        eval_gaps = eval_gaps[: args.sample]

    print(
        f"[draft] {len(eval_gaps)} gaps → drafter: {drafter.name}, "
        f"retrieval: {args.retrieval_mode}, top_k: {args.top_k}, "
        f"min_supporting: {args.min_supporting}"
    )

    t0 = time.perf_counter()
    drafts = draft_answers(
        eval_gaps,
        store=store,
        embedder=embedder,
        drafter=drafter,
        top_k=args.top_k,
        mode=args.retrieval_mode,
        reranker=reranker,
        min_supporting=args.min_supporting,
        sample=None,  # already sliced above
        drafter_model=drafter_model,
    )
    t_draft = time.perf_counter() - t0
    print(f"  {len(drafts)} drafts in {t_draft:.1f}s")

    # ── Judge each draft ──────────────────────────────────────────────────
    print(f"[judge] scoring {len(drafts)} drafts (judge: {judge.name}) …")
    t_judge_start = time.perf_counter()

    scores: list[JudgeScore] = []
    attr_rates: list[float] = []
    borderline: list[tuple[JudgeScore, str]] = []
    n_skipped = 0

    for draft in drafts:
        sketch = _find_sketch(draft.gap)
        if sketch is None:
            # No gold sketch for this gap — skip judging but count it.
            n_skipped += 1
            if args.verbose:
                print(f"  skip (no sketch): {draft.gap.gap_question[:60]!r}")
            continue

        # Attribution rate is always computed (automated).
        attr_rates.append(draft.attribution.attribution_rate)

        if draft.evidence_strength == "external-research" or draft.skipped:
            n_skipped += 1
            if args.verbose:
                print(f"  skip ({draft.evidence_strength}): "
                      f"{draft.gap.gap_question[:60]!r}")
            continue

        # Reconstruct full stub body for the judge (body_markdown only has
        # the four sections; frontmatter is separate but we don't need it here).
        passages_text = _format_passages(list(draft.supporting_chunks))
        score = judge.score(
            gap_id=sketch["gap_id"],
            gap_question=sketch["gold_question"],
            key_claims=sketch["key_claims"],
            passages_text=passages_text,
            body=draft.body_markdown,
        )
        scores.append(score)

        if score.is_borderline:
            borderline.append((score, sketch["gold_question"]))

        if args.verbose:
            p_str = "PASS" if score.passes else "FAIL"
            print(
                f"  [{p_str}] {sketch['gap_id']}: "
                f"faith={score.faithfulness} cov={score.coverage} "
                f"attr={score.attribution_quality} struct={score.stub_structure}"
            )

    t_judge = time.perf_counter() - t_judge_start
    elapsed_total = t_draft + t_judge
    print(f"[timing] draft {t_draft:.1f}s  judge {t_judge:.1f}s  "
          f"total {elapsed_total:.1f}s")

    # ── Metrics ───────────────────────────────────────────────────────────
    table = format_metrics_table(scores, attr_rates, n_skipped, len(drafts))
    print()
    print(table)

    n_judged = len(scores)
    n_pass = sum(1 for s in scores if s.passes)
    pass_rate = n_pass / n_judged if n_judged else 1.0
    mean_attr = sum(attr_rates) / len(attr_rates) if attr_rates else 1.0

    if hasattr(judge, "abstentions") and judge.abstentions:
        print(f"Judge abstentions: {judge.abstentions}")

    passed = args.judge == "none" or (
        pass_rate >= PASS_RATE_THRESHOLD and mean_attr >= ATTR_RATE_THRESHOLD
    )
    status = "PASS" if passed else "FAIL"
    print(
        f"\n[{status}] pass_rate={pass_rate:.2f} (>={PASS_RATE_THRESHOLD})  "
        f"attr_rate={mean_attr:.2f} (>={ATTR_RATE_THRESHOLD})"
    )

    # ── Borderline log ────────────────────────────────────────────────────
    if borderline:
        run_ts = time.strftime("%Y-%m-%d %H:%M:%S")
        write_judge_notes(borderline, args.judge_notes, run_ts, _git_rev())
        print(f"wrote {len(borderline)} borderline decisions → {args.judge_notes}")

    # ── BENCHMARK.md ──────────────────────────────────────────────────────
    write_benchmark_md(
        table=table,
        vault=args.vault,
        n_gaps=len(eval_gaps),
        n_judged=n_judged,
        n_skipped=n_skipped,
        drafter_name=drafter.name,
        judge_name=judge.name,
        elapsed_s=elapsed_total,
        path=args.benchmark,
    )
    print(f"wrote {args.benchmark}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
