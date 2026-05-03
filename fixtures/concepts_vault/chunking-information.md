---
title: Chunking Information
tags:
  - psychology
  - memory
  - expertise
  - learning
date: 2026-05-03
updated: 2026-05-03
status: evergreen
---

# Chunking Information

Chunking is the process of binding several individual pieces of information into a single, meaningful unit that can be stored and retrieved as one thing rather than many. It is one of the most important mechanisms by which skilled performance overcomes the strict capacity limits described in [[working-memory-limits]].

## The Classic Demonstration: Chess Masters

The canonical study of chunking comes from de Groot (1946) and Chase & Simon (1973). When expert chess players and novices were shown a mid-game board position for five seconds and then asked to reconstruct it from memory:

- **Masters** recalled the positions of ~25 pieces with high accuracy.
- **Novices** recalled only 4–6 pieces.

The striking finding was that when the pieces were placed *randomly* — not in any configuration that could arise from real play — the masters' advantage disappeared entirely. They recalled no better than novices.

This ruled out superior raw memory capacity as an explanation. What masters had was a large library of **perceptual chunks** — recognizable patterns (an open file, a fianchettoed bishop, a castled king formation) that could each be encoded as a single unit. A position containing 25 pieces might contain only 5–7 recognizable patterns, well within the working memory limit.

## What a Chunk Is

A chunk is any collection of elements that have been unitized through learning or experience:

- A word is a chunk of letters.
- A phone number written as `(415) 555-2671` is three chunks of digits.
- A musical phrase is a chunk of notes for a trained musician.
- A design pattern (e.g., "observer pattern") is a chunk of interacting classes for a software engineer.

The key property is that retrieving the chunk from long-term memory costs approximately the same as retrieving a single atomic item — the internal complexity is hidden inside.

## Expert vs. Novice Differences

Chunking is the central mechanism underlying most observable expert–novice differences in memory and performance:

| Dimension | Novice | Expert |
|---|---|---|
| Working memory load | High — each element is separate | Low — patterns compress elements |
| Error pattern | Loses track of individual items | Loses track of whole patterns (rarer) |
| Recall structure | Recalls items in arbitrary order | Recalls items in structured clusters |
| Acquisition cost | Must encode each element | Can encode at the chunk level |

Ericsson and Kintsch (1995) extended this to **long-term working memory**: experts develop retrieval structures that allow relevant long-term memory content to be rapidly made available, effectively enlarging their functional workspace without violating the basic capacity ceiling.

## Building Chunks Through Practice

Chunks are not inherited; they are built through deliberate exposure to recurring patterns. Implications:

1. **Repeated, varied practice** on similar structural patterns (not rote repetition of the same problem) accelerates chunk formation.
2. **Interleaved practice** exposes learners to patterns across contexts, promoting recognition of deep structure over surface features.
3. **Worked examples** let novices observe expert chunking before they must construct solutions independently — this is one reason worked examples are particularly effective early in instruction.

See [[mental-effort-and-task-complexity]] for how reducing extraneous demands gives novices the mental capacity needed to begin forming chunks.

## Chunking in Everyday Design

The principle extends well beyond formal education:

- **Phone numbers** are formatted with spaces or dashes to encourage three-chunk encoding.
- **Code style guides** recommend short functions because a well-named function becomes a single chunk in the reader's mental model.
- **Navigation menus** group related items into labeled sections so users chunk categories, not individual links.
- **Musical notation** groups notes into measures — each measure becomes a perceptual unit for a trained player.

## Related Concepts

- [[working-memory-limits]] — the capacity constraint that chunking effectively circumvents
- [[mental-effort-and-task-complexity]] — how task design either supports or obstructs chunk formation in learners

## References

- Miller, G. A. (1956). The magical number seven, plus or minus two. *Psychological Review, 63*(2), 81–97.
- Chase, W. G., & Simon, H. A. (1973). Perception in chess. *Cognitive Psychology, 4*(1), 55–81.
- de Groot, A. D. (1946/1965). *Thought and Choice in Chess*. Mouton.
- Ericsson, K. A., & Kintsch, W. (1995). Long-term working memory. *Psychological Review, 102*(2), 211–245.
