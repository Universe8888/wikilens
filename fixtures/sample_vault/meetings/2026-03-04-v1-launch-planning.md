---
title: Project Orchid v1 Launch Planning
date: 2026-03-04
tags: [meeting, project-orchid, launch]
attendees: [alice, bob, carlos, dana, emma]
---

# Project Orchid v1 — Launch Planning

## Status Check

- Screens reduced from 12 to 6 (target was ≤5; we're close).
- New address flow: soft-warn in place, flag tracking unverified rate.
- EIN field removed for personal accounts.
- Phone verification merged into welcome screen. Security review
  cleared on 2026-02-28.
- Consent copy approved by legal 2026-03-01.

## Outstanding Risk

The address soft-warn may increase support load — users who enter bad
addresses now get through and only discover the problem when their
first shipment fails. Emma (support lead) wants a two-week support
hiring ramp before launch.

## Decisions

1. Launch date pushed from April 1 to April 15 to accommodate support
   staffing.
2. Rollout in 10% cohorts over three weeks. Kill switch runs in
   feature flag if drop-off regresses or support volume spikes.
3. Success metrics locked: primary = drop-off ≤ 30% (from 42%),
   secondary = support ticket rate within 10% of baseline.

## Action Items

- [ ] Emma: hire two support specialists by 2026-04-08.
- [ ] Dana: verify kill-switch dashboards are wired.
- [ ] Alice: write the post-launch learning plan (what we measure,
      when we decide go/no-go on v2).
- [ ] Bob: final code freeze 2026-04-10.
