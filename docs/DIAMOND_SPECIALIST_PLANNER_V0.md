# Diamond cg_typed Specialist Turn Planner v0 (Pass 46J)

LOCAL-ONLY gameplay design (production keeps soaking — no redeploy). This is the design
contract for **one serious, owned, deck-specific TURN PLANNER** for the internal parent
deck `diamond_toolbox_diancie` — **not** another flat per-option / per-family scorer like
the Pass-46H generic diamond candidates.

The machine-checked, reproducible version of everything below is emitted by
`scripts/build_pass46j_diamond_planner_blueprint.py` into
`data/experiments/pass46j_diamond_planner_blueprint.{json,md}` and is derived from (and
cross-validated against) the Part-B deck audit
`data/experiments/pass46j_diamond_source_audit.{json,md}`. If the two disagree, the JSON
artifact is authoritative.

## Why a planner, not a scorer

The 46H diamond candidates score each option in isolation (a linear model over a coarse
action family plus a few visible option features). That gives locally-reasonable picks but
no cross-decision coherence: the attach-energy choice, the search choice, the discard
choice, and the attack choice are decided independently and may pull in different
directions.

The specialist instead computes **one DiamondTurnPlan per decision** from a visible-only
**DiamondBoardView**, then applies a **per-context policy** that ranks *only the legal
option indices* in line with that plan. Because the plan is shared across contexts, the
agent's attach / search / discard / attack choices on a given turn cohere around a single
intent (e.g. "fuel and attack with the main attacker", or "this is setup, build the
bench engine and draw"). That shared-plan coherence — not a bigger feature vector — is the
hypothesis under test in this pass.

## The deck (verified in Part B — no invented ids)

Mono-Psychic, 60 cards, 15 unique ids, every id resolved against
`data/cards/EN_Card_Data.csv`.

- **Main attacker:** `766 Mega Diancie ex` ×4 (HP270, ex) — `[Ability] Diamond Coat`
  (takes 30 less damage) + `Garland Ray` (discard up to 2 energy from itself, a scaling
  attack). The deck's namesake and only 4-of Pokémon.
- **Backup / tech attackers:** `525 Meloetta ex` ×2 (turn-1 attack enabler ability),
  `751 Xerneas` ×2 (Geo Gate bench-fill + Bright Horns), `331 XerneasEX` ×1 (anti-ex
  Rising Horns), `765 Meloetta` ×1 (healer + Magical Shot), `767 Mimikyu` ×2 (Call for
  Family bench-fill), `186 Gimmighoul` ×2 (energy search), `434 Team Rocket's Mimikyu` ×1
  (copy-attack tech), `183 Smoochum` ×2 (energy acceleration).
- **Engine:** `1086 Buddy-Buddy Poffin` ×4 / `767` / `751` bench-fill, `1121 Ultra Ball`
  ×4 + `1231 Dawn` ×2 (Pokémon → hand), `1224 Cheren` ×4 (draw 3), `1182 Boss's Orders`
  ×2 (opponent switch). `5 Basic {P} Energy` ×27.

All role labels are coarse deck-composition descriptors and inferences (copy count / HP /
ex / attack presence / printed effect text). They are **not** card-value, tempo, strength,
or "best card" claims.

## DiamondBoardView (visible only)

A never-raising, normalized view of the acting seat's board built from
`turn_primitives.board_snapshot_from_frame` + `visible_counts_by_zone`. It carries: `turn`,
`acting_seat`, inferred `went_first`, an inferred coarse `phase`
(`setup | develop | attack | end`), self per-zone **counts** (hand / deck / prize / discard
/ bench + `active_present`), opponent **counts only** (prize_remaining, bench_count,
active_present), `my_active_id` + `my_active_role`, `my_bench_ids`,
`my_active_energy_count`, and — only when actually visible in the frame — `opp_active_id` /
`opp_active_is_ex` (which drive the anti-ex tech). **No hidden zones are ever read** (no
opponent hand contents, no deck order, no prize contents). When the frame is unparseable,
`checkable=False` and the agent uses the raw-obs legal fallback.

## DiamondTurnPlan

Computed once per decision: `phase`, `desired_active_role`, `attacker_target`,
`backup_target`, `energy_target`, `setup_bench`, `search_targets`, `safe_discard`,
`retreat_switch_goal`, `attack_now` (a heuristic gate, **not** a lethal/KO signal),
`draw_deckout_safety` (from visible `deck_count` only), and `fallback_reason` (why the plan
is degraded / honest-unknown). See the blueprint JSON for the exact field semantics and the
inferred attacker/energy/search/discard priority rules.

## The 11 per-context policies (each maps to a real cabt option code)

Every context maps to a **real** cabt option-type code (`OPTION_TYPE_CLASS`, parity-tested
against `action_resolver` and the 46H candidate) and, where one exists, a real typed
`pilot_typed.decisions.decide` kind — no invented contexts. **Dispatch is by the raw option
`type` code / resolved action_class, never by `turn_primitives` family-name strings** (whose
vocabulary differs: `attach` / `ability` / `main_play` / `evolve` / `unknown`); the blueprint
JSON carries an explicit `dispatch_grounding` bridge so the two vocabularies never silently
diverge.

1. **choose_active** (codes 3,7 / `setup_active` + `emergency_backup_bench`) — pick the
   Pokémon to make Active toward `desired_active_role`. For initial setup, prefer a durable
   opener and keep the main attacker benched to grow unless it is the only legal active; for
   a forced promote after a KO, prefer an already-fueled in-play attacker (by VISIBLE
   attached-energy count) else a durable body.
2. **setup_bench** (codes 7,10 / `setup_bench_multi`) — bench the engine that advances the
   plan (energy-accel, bench-fill bodies, a main-attacker copy, a backup); respect
   `bench_pick_count`.
3. **attach_energy** (code 8 / `attach_energy`) — attach to `energy_target` (the planned
   in-play attacker), read from the option's own in-play target over *your* board.
4. **play_from_hand_engine** (code 7) — sequence draw / search / disruption trainers and
   Pokémon plays toward `search_targets` and consistency.
5. **play_in_play** (code 10) — all Pokémon are Basic, so treat as place-to-bench advancing
   setup.
6. **use_ability** (code 9) — mild "advance the board over passing, below attacking"
   preference; ability effects are not decoded from the schema.
7. **move_energy** (code 6) — prefer moving toward `energy_target`, else neutral.
8. **search_to_hand** (code 3 from deck / `search_to_hand`) — the specialist core:
   pick from the **offered** card list toward `search_targets` given board gaps.
9. **discard** (code 3 from discard / `discard`) — pick `safe_discard`: shed surplus
   energy / duplicate trainers / irrelevant tech; never the last main attacker or the
   energy needed to attack.
10. **draw_count** (codes 0–2 / `draw_count`) — choose the refill that respects
    `draw_deckout_safety`.
11. **attack** (code 13 — typed `attack` kind is **unsupported** for damage/lethal/ko/
    spread/gust) — an `attack_now` **gate only**: prefer attacking over passing when the
    plan wants a clock; among multiple attacks keep offered order (damage/effect are not in
    the option schema).

A non-named **default handler** covers `effect_choice`, `end_turn` (codes 12/14),
unknown-source `select_card`, and any unmappable option with an honest neutral, always-legal
fallback.

## Honesty boundaries (hard)

The planner asserts **none** of: `exact_damage`, `lethal`, `ko`, `missed_ko`,
`boss_gust_target`, `spread`, `best_action`, `best_attack`, `card_value`, `tempo_value`,
opponent hand contents, opponent/own deck order, prize contents, or any Kaggle
score/strength. This mirrors the typed layer's unsupported kinds (`attack`, `ko_target`,
`lethal`, `spread`, `boss`, `gust`).

## Attribution (separable from the 46H generic scorers)

A parent edge is only meaningful if it is caused by the **planner design**, not by a
relabeled generic scorer. So: the candidate reuses **no** 46H linear weights and ships its
own plan-driven ordering; evaluation runs it against the parent **and** against the 46H
generic diamond scorers (`option_value`, `family_only_floor`); non-inertness is traced
**by context and option family** and must be plan-field-driven (not cosmetic), with zero
illegal indices and zero exceptions; and three ablations — **no shared plan**, **no Diamond
roles**, **attack gate disabled** — must each measurably change behavior, otherwise that
design element is inert and cannot be claimed as the source of any edge. "Promising" requires
a parent H2H edge that is confirmed / strongly-directional on clean seats **and** separation
from the generic scorers (Fisher increment) **and** clean safety / validation / non-inertness
/ no leakage. No Kaggle strength is ever claimed.

## Runtime contract

`agent(obs_dict) -> list[int]` of legal option indices (or the 60 deck card ids on the
deck-submission step). Pure / read-only: **no** Object Storage, EventStore, Kaggle, cg
runtime mutation, file IO, or online Search in the hot path. **Never raises** — any parse
failure degrades to the raw-obs legal fallback. The deck is the parent's deck,
byte-identical; reference agents are benchmark-only and never a source/parent/candidate.
