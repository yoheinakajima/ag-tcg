---
name: Eval validator pre-filter + anchor pattern
description: How focused-eval + recommendation must treat a live Kaggle submission that fails the entrypoint validator — keep it as a directional anchor, never a promotion target.
---

# Validator pre-filter + active-control anchor + fail-closed gate

When a focused eval compares newly-built candidates against the current live
Kaggle submission (the "active control"), the eval must FIRST run every artifact
through the entrypoint-invariant validator and record a `validation` block
(per-artifact `entrypoint_pass`) into both the smoke and eval JSON outputs.

**The split that matters:**
- Validator-PASSING candidates are the only promotion-eligible set.
- The active control may FAIL the validator yet still be a *real, live-scoring*
  Kaggle submission. Keep it in the eval ONLY as a flagged directional anchor
  (`role: active_control_anchor`, `entrypoint_pass: false`, with a note that it
  is NEVER a promotion target). Pilots are ranked *against* it for signal.

**Recommendation gate precedence** (run_pass15_recommendation `build_metrics`):
anchor(`n/a`) → `fail_validator` → `fail_validity`(focused crash/timeout/skip) →
`fail_smoke_validity`(per-candidate live-smoke crash/timeout/skip) →
`insufficient_games`(<20) → `pass`(beats anchor) → `fail_no_edge`. Only
`promotion_gate == "pass"` may ever be queued, and the queue never uploads.

**Fail-closed rule:** the validator check is `validator is not True` — an outright
FAIL *and* an unverifiable result (missing tarball/validator → `None`) both block
promotion. Never let "unknown validator status" fall through to promotable.

**Why:** the live submission's deck-safety wrapper is inert (see
kaggle-entrypoint-ordering.md) so it fails the new validator, but it still plays
valid in-harness and scores live — dropping it would remove the only meaningful
directional baseline, while promoting anything that merely beats it (or that we
couldn't validate) would risk shipping an entrypoint-broken artifact.

**How to apply:** reuse this pre-filter + anchor + fail-closed-gate shape for
every future pass eval/recommendation script; do not invent a per-pass variant.
