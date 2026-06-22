# Diamond cg_typed SPECIALIST TURN PLANNER v1 (local-only)

`cg_typed_diamond_specialist_planner_v1` is a narrow upgrade of the Pass-46J v0 planner for
the internal parent deck `diamond_toolbox_diancie`. It is **local-only** (production keeps
soaking; nothing is redeployed) and judged against a single **pre-registered** pooled
reference-improvement test (frozen 46K baseline: v0 = W1/L59 decisive). References are
**benchmark-only** and never act as a source, parent, candidate, or decision gate (except that
one reference test).

## Why v1 is a *structural* diff, not the originally-frozen thesis

The plan originally froze a v1 around attack-now/end-turn gating plus role-keyed
search/bench/discard refinements. The Pass-46L Part-B reference-loss **trace audit** and the
option-**resolution probe** falsified that thesis with visible-only evidence, and an architect
re-consult directed the pivot recorded here:

1. **Attack gating is already correct live.** Across the v0-vs-reference trace panel (both
   seats), v0's first attack lands early (mean ≈ turn 3), it never fails to attack, there are
   **no** frames where an attack option is available-but-not-taken, and it **never** ends a
   turn while a productive option is present. Raising attack priority or demoting pass/end-turn
   would change nothing.
2. **Role-keyed refinements are ~inert in live play.** `resolve_play_card` maps ≈80% of chosen
   action options to a live card id, but only ≈10% land in the owned role-id table: the live
   cabt select-window id namespace differs from the offline role-map namespace, so the
   search/bench/discard/attach **role** bonuses essentially never fire live and the planner
   collapses to its family-base table. This is a card-id **grounding** gap, not a policy gap.
   Extending the role table from observed play to force the bonuses to fire would be
   **inventing card ids** — forbidden. The honest remedy is a separate, independently-audited
   grounding pass, not another thin policy layer.
3. **Small-n variance is large.** The same v0 went 5W/5L in a fresh 10-game reference panel vs
   ≈1/60 pooled in 46K. The frozen baseline stays frozen for pre-registration integrity; fresh
   panels are reported as variance/context only.

## The v1 diff (narrow, namespace-independent)

Every v1 lever keys **only** on board zone (active vs bench) and the **visible attached-energy
count** — never roles, card ids, damage, cost, lethal, KO, gust, or spread.

- **`attach_active_preference`** — prefer attaching energy to the visible **active** attacker
  (`+5 → +14` for an active target). The only live-observable attach signal is the target's
  board zone.
- **`attach_anti_overload`** — penalize attaching onto an already-loaded target harder
  (`−2 → −5` per attached-energy count) so energy spreads toward a less-energized eligible
  attacker when one is offered.
- **`choose_active_energy_tilt`** — when promoting a new active, lead with the most-energized
  Pokémon you can see (`+5 → +8` per attached-energy count). Expected near-inert (promotion
  windows are rare/forced); included for honest coherence, not for impact.
- **Unchanged on purpose:** the attack / end-turn policy, the attackId tie-break, the
  role-keyed search/bench/discard tables, and the deckout draw guard are kept **byte-for-byte**
  from v0. The first two are already correct live; the role tables would require invented ids
  to change; the deckout guard already implements the conservative behavior.

The primary live lever is therefore the **attach reweight**. Because v0 already attaches mostly
to the active, the realistic expectation is that v1 is **near-inert live** and the pass returns
a clean negative (`diamond_v1_internal_only_no_reference_gain` or `diamond_v1_not_promising`).
That is a successful pass: it produces honest negative evidence plus the grounding-gap
recommendation. A blocking non-inertness gate (≥5% changed live decisions in relevant contexts)
must pass before any reference panel is run.

## Honesty boundary (hard)

No exact damage, lethal, KO, missed-KO, Boss/gust target, spread, best-action/best-attack,
card/tempo value, opponent hidden-hand contents, deck order, prize contents, Kaggle
score/strength, reference parity/superiority, or invented card ids. The numeric `attackId`
tie-break is an arbitrary stable label, not a damage/strength ranking. Energy adequacy is the
visible attached-energy **count** only, never a computed attack cost or damage threshold.

## Constraints

Pure / never-raise; typed + raw-obs fallback; no online Search; no file I/O on the hot path;
self-contained INLINE region (`INLINE_DIAMOND_SPECIALIST_V1_BEGIN/END`) embedded verbatim into
the candidate `main.py` (no `src` import); deck `deck.csv` byte-identical from the diamond
parent; role-id table identical to v0 (no new ids).
