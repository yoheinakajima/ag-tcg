---
name: chaos telemetry observability (Pass 8 correction)
description: What the cabt harness actually exposes about the opponent vs what stays hidden; why chaos seams are partially_observable, not fully blocked.
---

# Chaos telemetry observability

Earlier passes wrongly concluded the opponent side was entirely hidden. Pass 8
corrected this: the opponent's PUBLIC board state IS observable from our seat —
hand SIZE/count, deck count, bench size, visible card ids, status flags, discard
pile, and the game log. What stays hidden is only (a) opponent HAND CONTENTS and
(b) own-side CAUSAL ATTRIBUTION — specifically `own_attack_damage_dealt` /
`own_attack_enabled` are not recorded as metrics.

This creates a third tier between available and blocked:
- **partially_observable**: every required opponent signal is a public count/status
  AND no required own-side metric is missing (e.g. mill: opponent deck/hand counts
  are public, so deckout pressure is measurable directly).
- **blocked**: a required signal is hidden (opponent hand contents) OR a required
  own-side metric is missing (the damage-attribution seams: froslass hand-avalanche,
  bench-bloat — they need per-attack damage we don't record).

**Why:** the chaos stream's scaling hypotheses (damage ∝ opponent hand/bench size)
can't be *proven* without per-attack damage attribution, even though the opponent
count driving them is fully visible. So chaos stays a research stream, not promotable.

**How to apply:** in `scripts/build_chaos_readiness.py` keep `min_metric` text honest —
say the opponent count IS observable and name the missing own-side metric; don't claim
"opponent X is hidden" when only hand contents / causal share is unavailable. The
contract surfaces this as `telemetry_conclusion_corrected_in_pass=8` with
`opponent_side_observable` per seam. Tests assert the tier split, not the prose.
