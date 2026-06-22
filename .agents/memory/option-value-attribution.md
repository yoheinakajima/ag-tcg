---
name: option-value attribution / confirmation methodology
description: How to honestly credit (or reject) a per-option / profile policy layer at confirmation time — control arm + Fisher increment, and what live-menu divergence does and does not prove.
---

# Crediting a policy "layer" requires a control arm AND a parent-edge decomposition

When a sprint pass produces a candidate whose extra layer (per-option value head, phase/role
profile, etc.) sits on top of a shared **family-only floor** scorer, a later confirmation pass
must clear TWO independent pre-registered arms before crediting the layer:

1. **ATTRIBUTION arm** — treatment vs its OWN family-only floor sibling (the control). If the
   treatment does not beat its floor (Wilson lower bound not > 0.50), the layer adds nothing,
   full stop — regardless of how it looks vs the parent.
2. **PRACTICAL arm** — treatment vs the real internal parent. A directional point (≥0.60) whose
   Wilson interval still spans 0.50 is **directional, not confirmed**.

Then **decompose** any parent-facing signal against the floor with a **Fisher-exact increment**
test on the two win counts (treatment-vs-parent vs floor-vs-parent). If that increment is not
significant, the parent edge is **inherited from the floor, not contributed by the layer**
(`parent_edge_attributable_to_option_value = false`).

**Why:** a treatment can post a "beats the parent" number while contributing nothing of its own
— the shared floor is doing all the work. Pass 46H's water "coherent escape"
(`cg_typed_water_option_value_v1`) looked promising on a 13.95% live top-1 menu divergence + a
tiny n=8 gameplay split; at N=43 in 46I it was a coin flip vs its own floor (22/43, Wilson
[0.368,0.654]) and its directional parent result (26/43=0.605) was statistically identical to
the floor's (25/43=0.581, Fisher increment p=1.0). Decision: `water_option_value_not_promising`.

**How to apply:**
- **Live top-1 menu divergence is necessary but NOT sufficient for a gameplay edge.** A layer
  that demonstrably moves the live pick can still be a gameplay coin flip vs its floor. Never
  let a menu-divergence number stand in for a head-to-head result.
- **Fisher p≈1.0 means "no detectable increment at this N", NOT formal equality/causality.**
  Word reports as "not detectably added over the floor", not "proven equal". (Architect LOW
  note, 46I.)
- Make the decision rule **let the attribution arm dominate**: attribution `no_edge` →
  `not_promising` even when the practical arm is directional. Order the rule so a directional
  practical result can never launder a failed attribution into "promising".
- Run noise self-mirror controls (treatment-vs-itself, parent-vs-itself) only when the practical
  arm is confirmed/directional; a clean control's Wilson interval contains 0.50.
- Confirmation tests should **re-derive** the decision from the pre-registered rule + observed
  labels rather than pinning the win counts (those move between honest re-runs).
