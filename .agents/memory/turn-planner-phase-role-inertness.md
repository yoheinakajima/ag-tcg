---
name: turn-planner phase/role layer offline inertness
description: why an additive cross-family phase/role layer on top of family weights is structurally near-inert for cg PTCG turn selection
---

An additive turn-scorer of the form
`score = family_weight + phase_adj[phase][family] + role_adj[role] + penalties`
layered on top of a family-weight floor is **structurally near-inert** for cg PTCG
turn selection: with moderate phase/role adjustments it changes essentially **zero
top-1 picks** versus the family-only floor.

**Why:** real cg `select` menus are largely **family-homogeneous** or pair
**non-competing** families. In practice `attack` and `attach_energy` NEVER co-occur in
the same menu (attacking is its own menu after development). So a cross-family phase
boost (e.g. attack_ready → +attack) has no competing higher-weight family present to
flip, and within-family `role` reweighting (targets_active vs targets_bench) rarely
displaces the option the oracle already ranks first. Phase detection itself works fine
(phases vary across frames) — the menus just don't expose the cross-family choices the
layer was designed to arbitrate.

**How to apply:** when designing a turn-planner scorer meant to *improve over* a plain
family-weighted baseline, an additive phase×family / role layer is the wrong lever —
budget it as a likely negative result. To actually differentiate, use **within-family
per-option value features** (which specific attach/search/play is better), not
phase×family cross terms. Always MEASURE differentiation as `argmax_diff` (top-1 pick
changes) vs the family-only reference on real trace menus before spending gameplay
compute; a near-zero argmax_diff means the layer collapses to the baseline and the
expensive parent-H2H tournament should be gated to the *distinct* policies only.

**Live-frame confirmation (not just the offline label set):** re-measured on the
parents' OWN recorded ACTIVE decision frames (real game observations, ~38–43 multi-
option frames/family), the same collapse holds: the `role` profile is **byte-identical
to the family-only floor at top-1 (0.0% diff)** in BOTH families measured; the `phase`
profile moves the top-1 pick on only ~5% (water 4.7%, below a 5% floor) to ~8% (diamond
7.9%, barely clears it). So only ONE phase representative per family ever clears the
floor, and the family-only floor and the `role` profile are the same live policy. The
strong signal that DOES exist is non-inertness **vs the parent** (34–63% of frames the
turn-planner picks a different option-set than the parent's native logic, 5–6 distinct
families, zero fallback/illegal/raise) — but that is a **family-weighted TRANSFER**
property of swapping in the scorer, NOT evidence the phase/role layer itself helps.
Report any parent edge accordingly; do not claim a phase/role success.
