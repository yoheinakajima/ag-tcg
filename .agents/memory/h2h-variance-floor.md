---
name: H2H variance floor
description: When a head-to-head win-rate "regression" is actually within the noise floor and not reproducible.
---

A deterministic, mechanistic difference between two policies (e.g. one extra scoring
branch that fires in a narrow context) can be **real and provable at the decision level**
yet have an **effect size below the variance floor** of a short match series. At ~20
games/side the head-to-head win rate can flip sign between independent samples (observed:
a child-vs-parent rate of 0.35 in one sampler vs 0.588 in another), and every aggregate
95% CI can overlap.

**Why:** match outcomes are high-variance; a tiny per-decision bias does not move the
win rate beyond sampling noise at small N. A single short H2H series is not evidence of a
durable regression.

**How to apply:** before declaring a candidate worse (or a refinement better) on a
head-to-head, (1) check the CI overlap, (2) reproduce the H2H on a second
sampler/seed-set, and (3) if it flips or stays within noise, label the outcome
`needs_more_h2h` and keep the incumbent as current_best rather than promoting. Only a
large fixed-seed series (≥200 games/side, one worker) can resolve a sub-variance effect.
Distinguish "mechanistically real" (decision-replay diff) from "outcome-significant"
(stable win-rate gap) — they are not the same.
