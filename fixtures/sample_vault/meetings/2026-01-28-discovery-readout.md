---
title: Project Orchid Discovery Readout
date: 2026-01-28
tags: [meeting, project-orchid, research]
attendees: [alice, bob, carlos, dana]
---

# Project Orchid — Discovery Readout

## What Alice Found

Interviewed 8 users across three segments. Key patterns:

- Six of eight got stuck on the address verification screen. They typed
  their address, got a "we can't verify this" error, and half gave up.
- The "business details" section asks for EIN and state of
  incorporation. Users didn't understand why we needed these for a
  personal account.
- Nobody read the consent text. Five out of eight clicked through in
  under 3 seconds.

## Decisions

1. Kill the EIN field for personal accounts. Add it back as an optional
   field deeper in the flow for business accounts.
2. Replace the hard-fail address verification with a soft-warn and
   allow-through. Track the "unverified" rate and revisit in 60 days.
3. Consent copy goes to a plain-language rewrite with legal. Bullets,
   not paragraphs.

## Contradiction Flag

Bob thinks we should also kill the phone verification step. Carlos
thinks phone verification is what keeps fraud low and disagrees
strongly. Decision deferred to next meeting; Carlos will pull the
fraud numbers.

## Action Items

- [ ] Alice: ship mock of simplified address flow by 2026-02-04.
- [ ] Bob: estimate of work to remove EIN field.
- [ ] Carlos: fraud metrics deck for the phone verification debate.
- [ ] Dana: experiment plan for the soft-warn on address verification.
