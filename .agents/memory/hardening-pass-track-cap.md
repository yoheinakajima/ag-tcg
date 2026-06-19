---
name: Hardening-pass variant-track cap
description: How the "AT MOST N hardening variant tracks" cap is counted in ActiveGraph portfolio passes, and the A/B multi-variant pitfall.
---

# Variant-track cap counting

The ActiveGraph portfolio-hardening passes (e.g. Pass 30) cap the plan at "AT MOST
N hardening variant tracks" (N=5). The cap counts **distinct list entries** in
`pass30_hardening_plan.json["tracks"]`, NOT distinct `track` label strings.

**Pitfall:** a single track that builds two sibling variants (e.g. Raging Bolt
structural A and B) is naturally written as two list entries both labelled
"Track 3 …". That silently makes 6 entries against a max of 5 and fails compliance,
even though the human-readable track numbering only goes 1–5.

**Fix / convention:** keep one track entry per track number; carry sibling builds
inside a `variants` sub-list on that single entry (each with its own
candidate/hypothesis/expected_improvement/risk). The track stays one entry, the
≤2-NEW-build sub-rule (all Raging Bolt) is still satisfied, and `new_builds_total`
counts the candidates, not the tracks.

**Why:** the architect review treats `len(tracks) > max_variants` as a BLOCKING
constraint breach; the report's Section 3 line ("variants planned: N tracks (max M)")
is generated straight from `len(plan["tracks"])`, so a miscount is also visible in
the final 10-section report.

**How to apply:** when building/regenerating the hardening plan, add a test that
asserts `len(plan["tracks"]) <= plan["max_variants"]` and that new builds are
≤2 and Raging-Bolt-only. Regenerate the report/events after editing the plan
builder so the artifacts stay in lockstep.
