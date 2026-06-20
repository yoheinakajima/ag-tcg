# StrategyProfile schema (Pass 35 typed-lite lane)

> LOCAL ONLY. No Kaggle upload/submit, no GitHub push. The registry lives at
> `experiments/strategy_profiles.yaml`. The builder
> `scripts/build_pass35_strategy_profiles.py` validates it against
> `src/ptcg_activegraph/pilot_typed/profiles.py` and re-checks every card id
> against `data/cards/EN_Card_Data.csv` (gitignored, never committed). No
> invented ids.

A **StrategyProfile** is the deck-specific input the typed board-aware tactics
consume. It does **not** alter the 60-card `deck.csv`. It declares which cards
play which role so the compiled candidate's typed layer can refine the
observable contexts and otherwise fall back to the proven base policy.

## Lane

`stdlib_typed_lite` — stdlib-only, embed-not-import. The compiled candidate is
exactly top-level `main.py` + `deck.csv`. The typed block runs the base policy
first and only refines a context when the board matches; on any mismatch or
error it bails to the base policy.

## Honesty contract

The typed lane observes board **state** only. It cannot honestly compute attack
damage, lethal, KO targeting, damage spread, Boss/gust target choice, or the
opponent's hand. Every executable profile lists these in
`unsupported_mechanics`. No profile claims a mechanic the runtime cannot
compute. The Raging Bolt profile additionally carries `refuted: true` and adds
**no** color-match / attack-damage rule (Pass 28 refuted that hypothesis).

## Fields

| field | type | meaning |
|---|---|---|
| `id` | str (required) | unique profile id (matches a deck idea id) |
| `executable` | bool | may a generic compiled candidate legally pilot it? `false` = special-pilot-only (excluded from build/tournament) |
| `special_pilot_required` | bool | win condition needs a special pilot the generic core does not implement |
| `lane` | str | always `stdlib_typed_lite` |
| `role` | str | portfolio role (reference_benchmark, candidate_for_confirmation, backlog_validate_later, refuted_deck_structural, special_pilot_only, ...) |
| `parent` | str\|null | parent profile id for parent/child confirmation |
| `implemented_contexts` | [int] | observable contexts the typed layer may refine — subset of `{0,1,2,7,8,38}`; empty for special-pilot-only |
| `unsupported_mechanics` | [str] | honest unsupported set; subset of `{attack_damage,lethal,ko_targeting,spread,boss,gust,opponent_hand}` |
| `energy_types` | [str] | attacker energy colors (Water, Lightning, Psychic, Fire, Grass, Fighting, Darkness, Metal) |
| `roles` | {role: [card_id]} | role → card ids; roles are `primary_attacker, setup_basic, energy_accel, draw_engine, key_item, search, tech, bench_sitter` |
| `priority` | [card_id] | global want order for setup/search (lower index = more wanted) |
| `deckout_guard` | {min_deck:int, max_draw:int\|null} | never draw ourselves below `min_deck`; cap forced draw at `max_draw` |
| `discard_keep` | [card_id] | never discard if avoidable |
| `discard_prefer` | [card_id] | discard first when forced (usually excess basic energy) |
| `card_ids` | [card_id] | distinct ids the profile references (all validated in the CSV) |
| `deck_plan` | str | human-facing plan (not executed directly) |
| `risks` | [str] | known risks / honesty caveats |
| `refuted` | bool | structural refutation marker (Raging Bolt); no fake fix allowed |

## Runtime contexts the typed layer refines

| ctx | meaning |
|---|---|
| 0 | emergency bench when bench empty + energy attach-target choice |
| 1 | setup active (place starting active Basic) |
| 2 | setup bench (place multiple bench Basics) |
| 7 | search-to-hand (Ultra Ball / Poffin style) |
| 8 | discard (keep attackers / key items; dump excess energy) |
| 38 | draw count (deckout guard) |

All other contexts fall through to the proven base policy unchanged.

## Basic energy ids

`1={G}Grass 2={R}Fire 3={W}Water 4={L}Lightning 5={P}Psychic 6={F}Fighting
7={D}Darkness 8={M}Metal`.

## Validation

`scripts/build_pass35_strategy_profiles.py`:

1. loads `experiments/strategy_profiles.yaml`;
2. runs `profiles.validate_profile(...)` on each (errors fail the build, warnings
   are surfaced);
3. confirms every `card_ids` / role / priority / discard id exists in
   `EN_Card_Data.csv` (no invented ids);
4. confirms executable profiles only claim contexts in `{0,1,2,7,8,38}` and
   only list known unsupported mechanics;
5. confirms special-pilot-only profiles are `executable: false` with empty
   `implemented_contexts`;
6. renders `data/experiments/pass35_strategy_profiles.{json,md}`.
