---
name: diamond planner reference gap is a grounding gap, not a policy gap
description: Why the typed diamond planner's role-keyed refinements are ~90% inert in live cabt play, why narrow visible-only structural reweights are ALSO inert, and the honest design constraint that follows.
---

# Diamond planner: the reference gap is a card-id grounding gap

Tracing the typed diamond specialist planner vs the public benchmark references (both seats)
shows its policy refinements barely change live decisions, for two compounding reasons.

## 1. Role-keyed refinements are ~90% inert live (the grounding gap)
- `resolve_play_card` works (~80% of chosen action options map to a live card id), BUT the
  owned role map (a small fixed id table) matches only ~10% of those live ids. The cabt
  **select-window card-id namespace ≠ the offline role-map / deck-build namespace**; only a
  few high trainer ids coincidentally align. So search/bench/discard/attach **role bonuses
  almost never fire live** — the planner collapses to its family-base table ordering.
- Attack/end-turn gating is already correct live (first attack lands early; no turns end with an
  attack available but unused). Raising attack priority or demoting pass/end-turn further is inert.

## 2. Narrow namespace-independent STRUCTURAL reweights are ALSO inert
After pivoting away from role-keyed levers to "structural" levers that read only board zone +
visible attached-energy count (a stronger attach-to-active preference, a harsher
already-energized penalty, a most-energized promote tilt), the v1-vs-v0 changed-decision rate
on real frames was **0%** (whole panel, both seats + parent; 0 illegal).
- **Why:** the attach active-vs-bench crossover is governed by the base/penalty ratio. Raising
  base AND penalty together moves the crossover only fractionally (e.g. 5/2≈2.5 → 14/5≈2.8), so
  both policies pick the same option across integer visible-energy counts. The active-preference
  already DOMINATES in the parent policy, so amplifying it cannot flip the argmax. The only
  live-firing surface (attach zone) is already set to the strategically correct "concentrate on
  the active attacker"; any structural lever that WOULD flip picks (redirect energy after N
  visible energy) encodes an implicit attack-cost/lethal assumption and would likely degrade.

**Net:** matches the prior "typed-layer live inertness ~1%" lesson. The reference gap is a
**card-id grounding gap**, not a policy-layer gap, and it is NOT closable by a thin visible-only
policy layer (role-keyed OR structural).

**How to apply:** make live argmax non-inertness a PRE-REGISTERED blocking gate (re-score real
frames with both planners; require a meaningful changed-decision rate in a relevant context
before running any eval panel). If inert, stop with a clean negative (`*_not_promising`) — do not
run panels. Extending the role-id table from observed play or reference outcomes is
**invented-id territory (forbidden)**; the real fix is a separate, independently-audited
grounding pass keyed to an authoritative owned card database, or a different archetype — never
another thin policy pass. Keep the pre-registered baseline frozen; report fresh panels (large
small-n variance, e.g. a 1/60 planner going 5W/5L) as variance/context only, never re-baseline.
