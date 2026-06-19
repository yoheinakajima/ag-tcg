# ActiveGraph — Pokémon TCG Strategy Canvas (Pass 18)

> **LOCAL ONLY.** Nothing in this pass is uploaded to Kaggle or pushed to GitHub.
> The internal deck league is **not** a Kaggle leaderboard and its win rates do
> **not** predict Kaggle results — opponents are our own decks piloted by the same
> generic core pilot. The meta sanity check is **surrogate-based and directional
> only**: replay-derived opponents are deck lists piloted by a generic surrogate,
> not real opponent policies. Card ids are validated against
> `data/cards/EN_Card_Data.csv` (gitignored, never committed). No invented ids.

## 1. Purpose

Pass 18 turns the loose collection of decks from Pass 17 into a **formal strategy
family registry** with explicit iteration tracking, and runs one **targeted
playbook iteration** end to end (Dragapult spread `v1`). The question this pass
answers is process-level: *can we register a family, form a hypothesis, build a
minimally-refined candidate, gate it, league it, sanity-check it against the
replay meta, and record an honest decision — without overbuilding and without
touching the immutable root agent?*

## 2. The pilot model (unchanged from Pass 17)

- **Generic core pilot.** One brain. Generic competence comes from
  mechanics/score evaluation in the base agent, not hand-tuned per-card logic.
- **Playbooks add roles, not rules.** A playbook tags each card and expresses
  light preferences (what to put active, what to search, what to discard). It
  never hard-codes a scripted line.
- **Runtime contexts** decide which decision seams the pilot refines. The
  Dragapult `v1` refinement only adds *role recognition* (`search_cards`,
  `draw_support`) at existing seams; it adds no new override and no aggro hook.
- **Broad Main stays delegated** to the base policy.

## 3. Strategy family registry

Five families are registered in `experiments/strategy_families.yaml` (source of
truth → `data/experiments/pass18_strategy_family_registry.{json,md}`):

| Family | Status (after Pass 18) | Current best | League |
|---|---|---|---|
| `water_kyogre_abomasnow` | active_reference | `league_water_core_reference` | ✅ benchmark |
| `dragapult_spread` | promising_research | `league_dragapult_spread_v1` | ✅ candidate |
| `raging_bolt_ogerpon` | backlog | `league_raging_bolt_ogerpon` | ✅ carried unchanged |
| `durant_deckout_carousel` | chaos_research_blocked | — | ⛔ excluded (chaos-research-only) |
| `future_high_ceiling_evolution` | backlog | — | not evaluated |

> Note on `current_best`: the columns above reflect the **post-decision** state
> (Part M promoted `v1`). The registry JSON was generated in Part B *before* the
> iteration existed, so its stored `current_best` for `dragapult_spread` still
> points at the parent — an intentional registration-time snapshot, not a contradiction.

## 4. The Pass-18 iteration: `dragapult_spread_v1`

- **Hypothesis.** The Dragapult Stage-2 spread/control shell is compatible with
  the generic pilot for setup/search/draw but under-uses its search and draw
  support. Light role tags should *hold or modestly improve* its internal result
  without modelling spread-damage placement.
- **Change.** `playbooks/pass18_dragapult_spread_v1.yaml` adds `search_cards` /
  `draw_support` role recognition only. Deck list is unchanged from the parent;
  no invented ids.
- **Fixtures.** `data/fixtures/pass18_dragapult_spread/` (5 targeted fixtures),
  all passing, on top of the shared `core_competency` set.

## 5. Eligibility gate (Part J)

The core-competency fixture `06_evolve_when_line_ready` is a **hard failure for
both `v1` and its parent** (it wants a Water-line card `723` that the Dragapult
playbook legitimately does not tag). Eligibility therefore uses a
**no-regression-vs-parent** rule on the core set plus an **absolute pass** on the
targeted set:

- core fixtures: `v1` 12/14 **==** parent 12/14 (no regression) ✅
- targeted fixtures: 5/5 ✅
- tarball + entrypoint validators ✅, live smoke clean ✅

→ `league_dragapult_spread_v1` is **league-eligible**.

## 6. Internal league (Part K)

Round-robin, 5 games/seat (seat-swapped), Durant excluded. Engine isolation via a
batched subprocess worker (memory isolation + real timeouts).

| # | deck | role | W-L-D | adj win rate |
|---|---|---|---|---|
| 1 | `league_dragapult_spread_v1` | pass18_candidate | 28-12-0 | 0.700 |
| 2 | `league_dragapult_spread` | parent_for_comparison | 27-13-0 | 0.675 |
| 3 | `league_water_core_reference` | stable_benchmark | 25-15-0 | 0.625 |
| 4 | `core_pilot_water_v2_runtime` | historical_reference | 19-21-0 | 0.475 |
| 5 | `league_raging_bolt_ogerpon` | carried_unchanged | 1-39-0 | 0.025 |

**Critical nuance:** `v1` ranks #1 on aggregate but **loses the direct
head-to-head vs its parent (0.3 for `v1`)**. Its aggregate edge comes from beating
the weaker field harder, not from beating the parent.

## 7. Meta sanity check (Part L)

Our decks vs the Pass-13 replay-derived subfamilies, each piloted by the generic
surrogate. Directional only.

- `league_dragapult_spread_v1` weighted meta score **0.747**, no collapse against
  any subfamily.
- `league_water_core_reference` weighted **0.580**.
- Sanity verdict: **passed** (no collapse < 10%, candidate does not trail Water).

## 8. Decisions (Part M)

- **Dragapult:** promote `v1` to **local research lead** — with the explicit
  caveat about the parent head-to-head loss. **Dry-run only; no upload.**
- **Water:** keep as the stable benchmark, unchanged.
- **Raging Bolt:** defer rescue. The league confirms the Part-D diagnosis — the
  0-for failure is **deck/structural**, not an energy-color or attack-first pilot
  gap (correct energy is attached and attacks are taken). Revisit only via
  deck-strength changes or supporter sequencing.
- **Durant:** chaos-research-only, excluded from the league (INVALID smoke).
- **Future high-ceiling evolution:** backlog, not evaluated.

## 9. Honest limits

The league is local only and not a Kaggle leaderboard; the meta check is
surrogate and directional. Neither equals a Kaggle result and neither is
sufficient to upload or submit. The Dragapult `v1` lead is an **internal research
lead**, not a competitive-strength or leaderboard claim.

## 10. Guardrails honored

No Kaggle upload/submit; no GitHub push; root `main.py`/`deck.csv` byte-identical
to v1; no invented card ids; tarballs are top-level `main.py` + `deck.csv` only;
Durant excluded from the league; all no-upload flags `false`.
