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
