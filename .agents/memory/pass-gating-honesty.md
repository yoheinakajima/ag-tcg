---
name: pass gating + report honesty
description: Honesty rules for held-probe retention gating and evidence-derived report claims in the ActiveGraph PTCG passes.
---

# Held-probe retention must be a real gate conjunction
Any "keep the held dry-run probe" / queue-retention decision must compute keep =
all(gates) over an explicitly persisted gates object, and that object MUST include
the no-meta-collapse gate (held probe must not collapse anywhere in meta sanity),
not just "clean run" + "no new candidate displaces".

**Why:** a prior pass computed `held_no_collapse` but never ANDed it into `keep_held`,
so a future collapsing probe could still be retained/queued — a silent gating defect
that only passed because the current probe happened not to collapse.

**How to apply:** persist `held_probe_gates` (dict of named bools) and
`held_probe_retained = all(gates.values())` in the decision JSON; surface every gate
in the md; never let re-affirmation/queue happen without retention. Add a test asserting
`retained == all(gates.values())` and that a retained probe has no collapse.

# Report root-safety claims must be evidence-derived, never hardcoded
The 10-section report's "Root safety" section must derive "root main.py/deck.csv
unchanged" and "package verify" from a real byte comparison (filecmp vs the frozen
baseline at data/baselines/v1_kaggle_349_8), emitting yes/no/unverified — never a
constant "yes/PASS".

**Why:** hardcoded `yes/PASS` over-claims compliance and would lie if a root file ever
changed. Honesty requires the claim to track reality.

**How to apply:** compute via filecmp.cmp(shallow=False); package verify = PASS only if
both root files match, FAIL if either differs, UNVERIFIED if a side is missing. Add a
test that section-1 strings match the live comparison result.

# Report/doc numeric claims must be cross-checked against the source artifact
Every ratio / win-rate / Wilson-CI / p-value written into a report, NEXT_STEPS, or the
strategy canvas must come from (or be test-asserted equal to) the eval-panel JSON it
summarizes — never hand-transcribed.

**Why:** a hand-typed `spec_vs_generic_floor = 18/22 [0.612,0.927]` shipped into the
report + NEXT_STEPS while the panel JSON actually held 27/33 = 0.818 [0.656,0.914]; the
numbers were internally plausible but wrong, and only caught at architect review.
Hand-transcription silently drifts from the artifact.

**How to apply:** prefer rendering report numbers from the panel JSON programmatically;
when prose is hand-written, grep the doc for the stale value after any panel recompute,
and keep a test that re-derives headline metrics from the JSON. Also keep volatile
counts (e.g. "N Pass tests", "N LOCAL events") in lockstep — adding tests/events means
updating every doc that states the count.
