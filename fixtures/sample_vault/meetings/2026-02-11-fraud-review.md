---
title: Fraud Review — Phone Verification
date: 2026-02-11
tags: [meeting, project-orchid, fraud]
attendees: [alice, bob, carlos, dana]
---

# Phone Verification — Fraud Review

## Carlos's Data

- Removed phone verification on a test cohort in Q3 2025 for two weeks.
- Fraudulent signup rate went from 0.8% to 3.1% — nearly 4× increase.
- Phone verification accounts for an estimated $340k/year in prevented
  fraud loss.
- Drop-off at phone verification is ~7% — low compared to the
  verification-step drop-off we're trying to fix.

## Discussion

Given the numbers, Bob agreed to keep phone verification in the flow.
The conversation then shifted to whether we could collapse the phone
step with another step to reduce perceived friction.

Alice proposed: combine phone verification with the welcome/greeting
screen. User sees "Let's get started — here's the code we just
texted you" instead of a dedicated verification step.

## Decisions

1. Phone verification stays. Carlos gets a gold star for pulling the
   numbers fast.
2. We will prototype Alice's combined phone+welcome screen by
   2026-02-25.
3. Bob to schedule security review for the combined screen — need to
   make sure we don't accidentally leak signals useful for enumeration
   attacks.

## Action Items

- [ ] Alice: mockup for combined screen by 2026-02-25.
- [ ] Bob: book security review slot.
- [ ] Carlos: document the Q3 2025 experiment so we don't lose the
      learning.
