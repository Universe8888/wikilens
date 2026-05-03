---
title: Threshold-Based Choice
tags:
  - decision-making
  - cognitive-science
  - rationality
  - heuristics
  - optimization
date_created: 2024-03-15
date_modified: 2024-03-15
status: evergreen
---

# Threshold-Based Choice

Threshold-based choice is a decision strategy in which the selector defines a minimum acceptable level for each relevant criterion, then accepts the first encountered option that simultaneously clears every threshold — without scoring, ranking, or comparing alternatives against each other.

It is the structural opposite of *maximising*, in which the decision-maker tries to identify the option with the highest overall score across all criteria.

## Anatomy of the Strategy

```
For each candidate option (in the order they are encountered):
    If option meets ALL thresholds → accept and stop
    Else → reject and continue
If no option is found → lower thresholds OR extend search
```

The key design decisions are:

1. **What criteria to include** — only those genuinely required, not every desirable feature.
2. **Where to set each threshold** — this is the hard part; thresholds set too high trap the agent in endless search; too low yields poor outcomes.
3. **How to handle the case of no acceptable option** — a fallback rule is necessary for completeness.

## Contrast with Maximising

| Property | Threshold-Based | Maximising |
|---|---|---|
| Evaluation order | Sequential, stops early | All alternatives compared |
| Information needed | Enough to pass/fail thresholds | Full ranking of all options |
| Computation | Low | High |
| Sensitivity to option order | Yes | No |
| Regret risk | Moderate | Low (in theory) |
| Real-world feasibility | High | Low for large option sets |

The maximising ideal is often unachievable (see [[bounded-rationality]]). Threshold-based choice trades the theoretical guarantee of optimality for practical speed and completeness.

## When Threshold-Based Choice Outperforms Exhaustive Search

Empirical and theoretical work has identified conditions under which accepting the first-good-enough option produces superior outcomes compared to continuing to search:

- **High search costs**: When each evaluation is expensive in time, money, or foregone alternatives, cutting the search short saves more than it loses.
- **Option decay**: In markets where good options disappear quickly (rental housing, job offers with deadlines), optimising over a full set is impossible — the set changes while you deliberate.
- **Uncertain ranking**: When noise in the evaluation process means your quality estimates are unreliable, picking a clearly acceptable option avoids the false precision of a ranked list.
- **Well-calibrated thresholds**: When the decision-maker has prior experience that allows realistic threshold-setting, the strategy is nearly as likely to land on the best available option as exhaustive search — at far lower cost.

## Threshold Setting: The Critical Skill

The strategy's quality is almost entirely determined by the quality of the thresholds. Common ways to set them:

- **Aspiration adjustment**: Start with a desired level; if the search is failing, lower thresholds incrementally.
- **Reference-class base rates**: "What does a typical acceptable option in this category look like?" sets a natural anchor.
- **Non-negotiables first**: List only criteria that are genuinely disqualifying if absent; avoid inflating thresholds with preferences masquerading as requirements.

## Connections

- [[good-enough-decisions]] — real-world examples of the strategy in hiring, housing, and social selection
- [[bounded-rationality]] — the cognitive and informational limits that make threshold-based choice adaptive rather than merely lazy

## References

- Simon, H. A. (1955). A behavioral model of rational choice. *Quarterly Journal of Economics*, 69(1), 99–118.
- Gigerenzen, G., & Goldstein, D. G. (1996). Reasoning the fast and frugal way: Models of bounded rationality. *Psychological Review*, 103(4), 650–669.
- Schwartz, B. (2004). *The Paradox of Choice: Why More Is Less*. HarperCollins.
