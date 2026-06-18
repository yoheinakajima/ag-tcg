---
name: meta_pool.yaml evolves per pass; pass tests track its state
description: Why each Pass rewrites experiments/meta_pool.yaml and updates the prior pass's state-assertion tests
---
`experiments/meta_pool.yaml` is THE single evolving meta pool, rewritten every pass
(Pass 10 -> 10B -> 11B). Each pass's test file encodes the meta state *as of that pass*.

**Rule:** When a later pass legitimately changes meta reality, the prior pass's
state-assertion tests that now contradict reality MUST be updated to the new reality.
Distinguish two test classes and treat them differently:
- INVARIANTS (keep, never weaken): root main.py/deck.csv unchanged vs v1 baseline;
  no invented card ids anywhere; live_score_registry dynamic rule (highest complete
  non-error publicScore = active_control); weighted_meta_score math; tarball validator
  mandatory; `_pass10_control_scores` resolves v1/v2 by *identity* not role.
- STATE ASSERTIONS (update when superseded): which archetypes are blocked/confirmed;
  who the active_control is; evaluation_weights key set; controls.rejected identity.

**Why:** Pass 11B confirmed metal_ex_zacian_ramp (tellurium replay 80503804) and
water_kyogre_abomasnow_maxbelt (TYMU replay 80504288), and live scores shifted so
combo_full_safety_v3_fixed went from live_rejected@294 to live leader@376.6. You
cannot keep "metal blocked" and "metal confirmed" both true; the old assertions are
genuinely superseded, not broken.

**How to apply:** `_pass10_control_scores(pool)` keys off candidate_id substrings
("v1"->v1, "deck_energy_trim_light"->v2, "combo" or decision==live_rejected->rejected)
and the LAST matching controls entry wins (dict insertion order). To keep the Pass 10
report's historical rejected=294 while combo is now active@376.6, the Pass 10 *report
section* is historical; reflect the live leader in the Pass 11B section instead.
