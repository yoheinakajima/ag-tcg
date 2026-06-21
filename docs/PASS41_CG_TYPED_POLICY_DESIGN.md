# PASS 41 — cg_typed Policy Design: `cg_typed_mono_lightning_miraidon_policy_v1`

> **Local benchmark-lane feasibility spike — NOT a Kaggle score, leaderboard, or
> strength claim.** This document specifies an **original** typed policy for an
> **owned** candidate. No reference-agent code is read or copied. Bundling the
> `cg/` SDK from `data/reference_agents/_sdk/cg` is permitted and expected for the
> cg_typed lane.

## 1. Target & provenance

- **Target family (Part C):** `mono_lightning_miraidon_easy` — gen-0 portfolio
  anchor, stdlib runtime, selected on weak/tied benchmark evidence (every
  schedulable candidate's decisive-win-rate Wilson CI overlapped the default).
- **Planned candidate id:** `cg_typed_mono_lightning_miraidon_policy_v1`
  (`runtime = cg_typed`, `owned_candidate = true`, `public_reference = false`,
  mutation parent = the internal anchor only).
- **Deck:** the parent's `deck.csv`, **unchanged** — a Miraidon ex mono-Lightning
  toolbox.

### Deck identity (resolved via `cg.api.all_card_data`)

| card | n | role |
|---|---|---|
| Miraidon ex (957, basic ex, 220 HP) | 4 | primary attacker + {L} energy engine; Hadron Spark 120 `[L,L,C]` (bonus vs opponent ex), Slashing Claw 40 `[L]` |
| Thundurus (514, basic, 120 HP) | 2 | secondary attacker / energy fetch; Charge (search a Basic {L}), Disaster Volt 110 `[L,C,C]` |
| Pawmi→Pawmo→Pawmot (809/810/811) | 3/1/3 | stage-2 finisher Voltaic Fist 130 `[L,L]` (via Rare Candy) |
| Basic {L} Energy (4) | 26 | fuel |
| Buddy-Buddy Poffin (1086) | 4 | search basics to bench |
| Ultra Ball (1121) | 4 | discard 2 → search any Pokémon |
| Cheren (1224) | 4 | draw 3 |
| Rare Candy (1079) | 3 | Pawmi → Pawmot |
| Boss's Orders (1182) | 2 | gust a benched opponent into active |
| Dawn (1231) | 2 | supporter utility |
| Levincia (1254) | 2 | stadium |

Every Pokémon shares **Fighting (EnergyType 6) weakness**; our attack type is
**Lightning (EnergyType 4)**.

## 2. Why this is original (not a port)

The **parent** policy is a schema-agnostic scorer: it lower-cases the raw `obs`
dict to text, applies keyword weights, adds a small numeric `option["type"]`
score, and picks the top legal index (plus Pass-8 effect-resolution overrides on
raw dict fields). **It never touches the `cg` SDK.**

This design instead **decodes the observation into the typed `cg.api`
dataclasses** and makes structured decisions on `SelectContext`, `OptionType`,
`EnergyType`, and concrete board state (prizes, HP, attached energies, deck
count). The reasoning below — prize math, attacker-readiness, weakness-aware
lethal detection, Boss's-Orders target planning, deck-out safety — is specific to
this Miraidon deck and is **not** present in the parent. The only shared code is
(a) the deck-return plumbing and (b) the never-raise / always-legal fallback
contract, both of which are this project's own conventions, not reference logic.

## 3. SDK surface used

- `cg.api.to_observation_class(obs_dict) -> Observation` (typed decode).
- `cg.api.all_card_data()` / `cg.api.all_attack()` — built **once at import** into
  `{cardId: CardData}` / `{attackId: Attack}` lookup maps (card types, HP,
  weakness, attack costs/damage/bonus text).
- Enums: `SelectContext`, `SelectType`, `OptionType`, `EnergyType`, `AreaType`,
  `CardType`.
- State reads: `select(context,type,minCount,maxCount,option,deck)`,
  `current(turn, yourIndex, players[2])`, `PlayerState(active, bench, benchMax,
  deckCount, discard, prize, handCount, hand)`, `Pokemon(id, hp, maxHp, energies,
  energyCards, tools)`, `Option(type, area, index, playerIndex, attackId, …)`.

**No `search_begin` / MCTS in v0** — a fast deterministic typed heuristic, well
inside the per-step time budget (one cached static-DB build at import, then
O(options) per step).

## 4. Decision helpers

- **Prize math** — `my_prizes_left = count(my prize)`, `opp_prizes_left =
  count(opp prize)`. A KO taking our last needed prize is top priority; KOing an
  opponent **ex** (2 prizes; mega-ex 3) is weighted up.
- **Lethal detection** — `effective_damage(attack, defender) = base ×2 if
  defender.weakness == attacker EnergyType, + attack bonus (e.g. Hadron Spark vs
  ex)`; `can_ko = effective_damage ≥ defender.hp`.
- **Board counts** — in-play Lightning attackers, total attached {L}, developing
  bench attackers, empty bench slots (`benchMax − len(bench)`).
- **Attacker readiness** — for each in-play Pokémon × attack, compare attached
  `energies` (COLORLESS satisfiable by any) to the attack cost →
  `can_attack_now` / `energy_short_by`. Attaching favors the attacker with the
  smallest `energy_short_by` that becomes lethal/strongest.
- **Target planning** — if active can KO → attack; else if Boss's Orders gusts a
  KOable / high-value benched target into active and we can KO → gust then
  attack; weakness-aware (opponent weak to Lightning ⇒ double).
- **Draw / deck safety** — never take a draw/search that would start our next
  turn with `deckCount == 0` (loss reason 2); throttle optional draw/search when
  the deck is thin; gate Ultra Ball's 2-card discard on a thin hand/deck.

## 5. Per-`SelectContext` policy

- **MAIN (0)** — rank legal options: **ATTACK(13)** by effective prize progress
  (lethal first, then max damage, Hadron-Spark-vs-ex bonus) → **ABILITY(10)**
  Miraidon energy acceleration when it readies a Lightning attacker (deck-safety
  gated) → **ATTACH(8)** {L} to the attacker with the smallest `energy_short_by`
  to its best attack (an active that can then attack first, else key bench
  attacker) → **PLAY(7)** develop via Poffin / Ultra Ball / Cheren / Rare Candy
  (deck-safety + orphan-evolution guard) → **EVOLVE(9)** advance the Pawmot line
  when it improves output → **RETREAT(12)** only to promote a ready attacker,
  weighing retreat cost → **END(14)** only when no positive-value action remains.
- **SETUP_ACTIVE / TO_ACTIVE / SWITCH** — promote the highest-readiness Lightning
  attacker; prefer Miraidon ex active as the engine absent a better lethal line.
- **SETUP_BENCH / TO_BENCH / TO_FIELD** — bench all useful basics up to
  `benchMax`, prioritizing the energy engine and future attackers.
- **TO_HAND (7, search)** — needed attacker (Miraidon ex if none in play) >
  Basic {L} when energy-short > evolution piece **only** if its base / Rare Candy
  is present (avoid orphan evolution) > best draw; deck-safety gated.
- **DISCARD (8) / DISCARD_\*** — discard surplus energy and duplicate supporters;
  **protect** in-play attackers, setup basics, and the minimum energy for the
  next attack.
- **DAMAGE_COUNTER (13/14) / DAMAGE (15)** — place damage to convert a target
  into a KO when possible, else onto the highest-value opponent Pokémon.
- **HEAL (17) / REMOVE_DAMAGE_COUNTER (16)** — heal the most valuable / most
  threatened attacker.
- **ENERGY contexts (30–33)** — keep {L} on the lead attacker; discard/return
  colorless-satisfiable surplus first.
- **COUNT contexts (38–40)** — draw the maximum **safe** count; place the maximum
  beneficial damage counters.
- **YES_NO** — `IS_FIRST(41)` → **yes** (aggressive acceleration deck wants
  tempo); `MULLIGAN(42)` → yes only with no Basic in hand; `ACTIVATE(43)` /
  `FIRST_EFFECT(44)` → activate when it advances the plan and is deck-safe;
  `COIN_HEAD(46)` → heads when favorable.
- **SPECIAL_CONDITION (47–48)** — affect/recover the condition most impactful to
  our active attacker.

## 6. Safety contract

- **Never raise** — every branch is wrapped; any exception or unexpected shape
  degrades to the legal-index fallback.
- **Always legal** — output re-validated to unique, in-range indices honoring
  `minCount` / `maxCount` (project `_validate_action` contract).
- **Deck-return step** — `select is None` at step 0 → return the 60 deck card ids
  from `deck.csv` via the robust multi-path loader.
- **Non-inertness goal** — typed branches must change a **measurable fraction** of
  decisions vs the parent on live states while producing **zero** illegal
  actions. The value here is correctness/safety of the typed lane, **not** a
  strength claim.

## 7. Validator alignment

Built to satisfy the **cg_typed lane validator**
(`docs/CG_TYPED_LANE_VALIDATOR.md`): bundles `cg/`, decodes via `cg.api`, must be
**ACCEPTED** by the cg_typed validator and **REJECTED** by the stdlib validator
(which forbids the `cg` import). The stdlib validator is left unchanged.

## 8. Hard guardrails (unchanged from the pass spec)

No Kaggle upload/submit; no GitHub push; no root `main.py`/`deck.csv` mutation; no
tarball mutation/deletion; references never become candidate/parent/queue/promote
and never count toward the active cap; no copying reference-agent code (cg/ SDK
bundling allowed); every emitted event `no_upload=true`; the candidate is
registered **local-only**.

## 9. Outcome (Parts E–N)

The candidate `cg_typed_mono_lightning_miraidon_policy_v1` was built, validated,
smoke-tested, and evaluated. Honest results:

- **This candidate is ours** — owned typed lineage, `mutation_parent=internal`,
  `main.py` SHA matches none of the references; the **public references are
  benchmark-only** opponents and stayed absent from the candidate pool.
- **Validation:** cg_typed lane ACCEPTS; both stdlib validators (byte-unchanged)
  REJECT. **Smoke:** 9/9 clean. **Parent/child:** 10–0 (Wilson [0.7225, 1.0]),
  above the self-mirror noise floor (pooled Fisher p=0.0085). **Anchors:** above
  `water_control` + `internal_leader`, **below** `dragapult_reference`.
  **Public-reference eval:** 1/20 decisive (WR 0.05) — **below** the references.
- **Non-inertness:** 152/246 decisions changed (61.8%), **0 illegal**, 0 uncaught
  exceptions.
- **Decision: `promising_local_only`** — the local benchmark signal is
  **directional only**, this is **NOT a Kaggle score or strength claim**, and
  **no submission/upload/promotion was made**. `republish_required=false`.
- **Next step depends on the eval outcome:** finish the remaining calibration
  games and deepen the parent/child + noise sample before any further typed work;
  no public-reference parity claims at this sample.

Full write-up: `data/reports/pass41_reference_calibrated_cg_candidate_report.md`.
