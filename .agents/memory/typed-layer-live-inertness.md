---
name: typed strategy layer is mostly inert in live cabt play
description: The PASS35 typed board-aware override rarely changes the base policy's choice during real games, even though fixtures prove it can.
---

# The typed override fires on constructed fixtures but rarely in live games

The PASS35 typed-lite layer refines the base policy ONLY at a few observable
contexts (Main/setup/bench/search/discard/draw-count) and ONLY when specific
trigger conditions hold (e.g. an attach with >=2 DISTINCT resolvable targets, a
multi-option setup/bench choice, a real discard/draw-count choice). In real cabt
games most of those decisions are degenerate — a single legal option, or the
base policy already picks the same option the typed layer would — so the override
returns the base choice unchanged.

**Consequence for honesty:** report two separate measurements — "non-inert by
construction (fixtures)" vs "live per-decision firing rate (replay)". Across a
diverse opponent panel the layer IS non-inert in live play but the firing rate is
very low (Pass-35: ~34 changes / ~3666 live decisions ≈ 0.9%; a handful per child;
one child showed zero in a small sample). A single mirror game can show 0 changes
and mislead you into calling it fully inert — use >=2 distinct opponents and both
seats before concluding. Do NOT claim the typed layer improves play just because
fixtures pass — measure live deltas AND parent-vs-child head-to-head, and expect
no-regression rather than a strength gain.

**Why:** the value is safety (every observed change was legal and confined to the
profile's declared contexts — 0 misfires, 0 unsafe across thousands of decisions),
plus occasional refinement, NOT a measured strength gain.

# Calibrate parent-vs-child H2H against a NULL self-mirror control

A seat-swapped child(typed)-vs-parent(untyped) H2H at the budget-feasible game count
(~20 games/pair) is NOT trustworthy on its own. Run a null A/B control: the SAME
agent on both sides — `parent_mirror` (parent vs parent) AND `child_mirror` (child vs
child) — through the identical harness. In theory both must be ~0.5, but at 20 games
the cabt self-mirror win-rate ranges ~0.25–0.73 (noise floor ≈ ±0.25), and the
child_mirror (exact-symmetry, should be 0.5) lands ~0.45–0.70, exposing a small
systematic first/"A"-labelled-side bias plus large per-deck variance.

**How to apply:** only credit a raw improves/worse verdict if the child's Wilson CI
clears BOTH self-mirror CIs (no overlap) and is on the right side of 0.5; otherwise
downgrade to inconclusive (no superiority/regression claim). In Pass-35 this turned
3 raw "improves" (raging_bolt 0.95, gardevoir 0.90, venusaur 0.79) and 1 raw "worse"
(water_core 0.20) into ALL inconclusive/no_regression — every swing was inside the
noise floor (e.g. venusaur parent_mirror itself was 0.73). A ~1%-firing layer cannot
arithmetically produce a 0.9 aggregate (firing-0 games are mirrors ≈0.5), which is
the independent tell that such results are noise, not strength.

**Why:** under H0 (typed layer inert) child==parent behaviourally, so the correct
null distribution IS the parent_mirror; a single 20-game H2H deviation of the same
magnitude as the mirror's own deviation is not evidence of effect.

# Prefer Fisher-exact (H2H vs pooled self-mirror) over CI-non-overlap at small n

The "child CI must clear BOTH mirror CIs" rule above is the right instinct but is
TOO STRICT at budget-feasible sizes — Wilson CIs on ~10–20 decisive games are so
wide they almost never separate, so a genuine effect reads as inconclusive. Better
test: compare the H2H win/loss counts against the self-mirror win/loss counts with
a **Fisher exact test** (one per mirror + a pooled-mirror pool), and require the
mirror controls themselves to be clean (both mirror CIs straddle 0.50). In Pass-41
a 10–0 child-vs-parent result (Wilson [0.7225, 1.0]) had mirror controls at 0.60
and 0.50 (both straddling 0.5) and pooled-mirror Fisher **p=0.0085** → corroborated
as a real behavioral difference, where the strict CI-non-overlap rule alone would
have been needlessly indecisive.

**How to apply:** (1) confirm parent_mirror AND child_mirror CIs both straddle 0.50
(harness unbiased); (2) Fisher-exact the H2H counts vs the pooled mirror counts;
(3) only then credit "child differs from parent" — and even then scope the claim to
parent/internal-anchor comparisons, NEVER to public-reference strength (Pass-41's
parent-beating child was still far below every public reference).

**Why:** at n≈10–20 the variance of a Wilson CI dwarfs the effect; an exact count
test against the empirical null has far more power while staying honest about small
samples.

# A "finer-feature escapes coarse inertness" claim needs a COHERENT live∩gameplay escape

When testing whether a finer policy layer (e.g. per-OPTION visible features) escapes a
coarser layer's documented TOP-1-INERTNESS, measure TWO independent legs against the
same family-only floor control and require BOTH: (1) LIVE-menu distinctness — top-1
pick divergence from the floor on real replay menus above a floor (e.g. ≥5%); (2)
GAMEPLAY distinctness — beats-or-loses-to the floor at 95% (Wilson CI does NOT span
0.5). Partition candidates into coherent (live AND gameplay), live-only (live, not
gameplay), and gameplay-variance (gameplay, not live) — disjoint buckets.

**Why:** a gameplay split over a LIVE-INERT menu is almost certainly variance, not the
feature firing (the layer barely changed any pick, yet "won" — that is noise); and
live-distinctness with no gameplay or parent separation is interpretability, not
strength. Only the coherent bucket is a defensible "escape," and even then it is a
WITHIN-FAMILY-FLOOR escape, NEVER a parent edge — a parent edge requires its own
Wilson-lower>0.5 H2H, which can be absent even when all candidates incl. the floor tie
the parent.

**How to apply:** "promising" = at least one coherent escape; gate the decision on it,
but report the no-parent-edge / tiny-offline-coverage (hand-set priors, not fit) /
likely-variance caveats explicitly. Lock these in tests: assert the three buckets are
a disjoint partition whose (coherent ∪ gameplay-variance) equals the gameplay-distinct
set, assert parent_edge_established is a biconditional of the eval edge list, and
assert the report literally states the no-parent-edge and variance caveats.
