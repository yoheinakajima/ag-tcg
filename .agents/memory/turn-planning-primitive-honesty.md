---
name: turn-planning primitive honesty + trace-shape limits
description: What the Kaggle-replay decision-frame traces can/cannot honestly support for turn-planning primitives, and which docs are the living pass-logs.
---

# Turn-planning primitives over replay decision frames

**Trace-shape honesty constraints (discovered by inspecting the replay traces, not the code):**
- **Setup is a hand-select with NO destination.** In these replay traces the setup phase is
  encoded as `select_card` (type 3, area 2 = hand); there is **no** active-vs-bench
  destination in the option schema. So any setup primitive can honestly report only the
  *phase* (and self-active presence) — it must NOT claim which placement is active vs bench.
  Destination labelling needs a richer cg-typed observation (backlog).
- **Attach DOES carry a destination.** Attach-energy options (type 8) carry `inPlayArea`
  (4 = active, 5 = bench), so attach-destination labelling IS honest and resolvable.
- **Selected action is not recoverable** from these traces (see passes 46B/46C): primitives
  describe options *presented*, never the action *chosen*. Rates/comparisons must say so.
- **attackId alone never backs a damage/lethal claim.** Keep exact-damage / lethal /
  missed-KO / Boss-gust / spread / best-action in a stable `unsupported_claims()` guard so
  tests can assert the guarantees never silently shrink.

**Why:** future candidate-generation work will reach for these primitives; overclaiming a
setup destination or a chosen action would fabricate signal the traces don't contain.

**How to apply:** build turn-planning primitives as pure / never-raise over the pure
`action_resolver` + `turn_planning` decoders only (no storage/eventstore/prod/reference
imports). Accept a Kaggle seat object, raw observation, bare select, **and** a
`DecisionFrame` — and for a `DecisionFrame` read `n_options`/`option_families` directly
(it has no raw options) rather than coercing to an empty select (silent-zero bug).

**Living pass-logs:** append pass addenda to `docs/NEXT_STEPS.md` AND
`docs/PTCG_STRATEGY_CANVAS.md` (both are pass-logs; passes 43–46c had skipped them).
`docs/REPORT_SITE_ACTIVEGRAPH_SOURCE.md` is a generator description, NOT a pass-log — do
not put pass entries there.
