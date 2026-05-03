---
title: "Interest on Interest"
tags:
  - finance
  - investing
  - time-value-of-money
  - exponential-growth
  - personal-finance
date: 2026-05-03
created: 2026-05-03
modified: 2026-05-03
status: evergreen
---

# Interest on Interest

When a portfolio earns a return, that return can be reinvested so that it, too, begins earning returns. The initial principal grows — but so does the base on which future returns are calculated. Each period, the growth applies to a larger number than the period before. Over long horizons this produces an exponential curve rather than a straight line.

## The Snowball Metaphor

A snowball rolling downhill gathers more surface area as it grows, which lets it pick up snow faster than a small ball ever could. The analogy maps cleanly onto long-term investing: a portfolio of $10,000 growing at 8% per year adds $800 in year one, but in year twenty it adds roughly $3,300 — on the same 8% rate. The *rate* is constant; the *base* is not.

## Why Starting Early Dominates Rate

Two investors both earn 7% annually. Investor A starts at age 22 and contributes for ten years, then stops. Investor B starts at age 32 and contributes for thirty years. At retirement (age 62), Investor A typically finishes ahead despite fewer total years of contributions, because the early years had longer to generate returns on returns.

The practical implication: **time in the market outweighs contribution size** for most ordinary investors.

## Doubling Time: The Rule of 72

A rough heuristic for how long it takes an investment to double:

```
Doubling years ≈ 72 / annual-interest-rate (%)
```

Examples:

| Rate | Approximate doubling time |
|------|--------------------------|
| 3%   | ~24 years                 |
| 6%   | ~12 years                 |
| 9%   | ~8 years                  |
| 12%  | ~6 years                  |

The Rule of 72 is an approximation; the exact formula is `ln(2) / ln(1 + r)`, but the shortcut is accurate enough for planning purposes within normal interest-rate ranges.

## Exponential vs. Linear Growth

Linear growth adds the same absolute amount each period. Exponential growth multiplies by the same factor each period. Visually, exponential growth looks flat for a long time and then bends sharply upward — which is why the later years of a long-term holding feel disproportionately productive.

The mathematical form: if $P$ is the principal, $r$ the rate, and $t$ the time in years, then the future value is

```
FV = P × (1 + r)^t
```

Contrast with simple interest (`FV = P × (1 + r × t)`), which grows in a straight line.

## Common Pitfalls

- **Interruptions reset the base.** Withdrawing gains prevents those gains from generating their own future gains.
- **Fees erode the base.** A 1% annual management fee sounds small but, applied each year to the growing total, removes a meaningful share of long-run value.
- **Inflation adjustments matter.** A nominal return of 8% with 3% inflation is a real return of roughly 5%. The snowball metaphor only works in real terms.

## See Also

- [[habit-accumulation]] — the same feedback loop (small gains generating larger future gains) applies outside of finance, in skill-building and behavior change
