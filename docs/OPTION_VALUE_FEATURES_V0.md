# Within-Family Per-Option Value Features (v0) — Pass 46H

This documents the owned, pure, never-raise within-family per-**option** value scorer in
`src/ptcg_activegraph/analysis/option_value_features.py` (schema
`pass46h_option_value_v1`). It is the candidate hot-path policy for the Pass-46H
local-only gameplay-measurement sprint.

## Why a new scorer

Pass 46G conditioned its linear score on **coarse, board-level** signals — a heuristic
*phase* label and a target-*area* role — and documented a TOP-1 *inertness*: within a
single legal menu those coarse signals rarely changed which option the policy picked, so
the calibrated 46G profiles behaved almost identically to the family-only floor in live
play. 46H asks a narrower, falsifiable question:

> Do **option-specific, strictly visible** features (the identity of the card an option
> plays, the in-play target it points at, its energy count, whether it ends the turn while
> productive plays remain) change the within-menu pick more than 46G's coarse signals did —
> and, if so, does that change track the cached Pass-46E Search oracle's preferences?

## What is observed (and what is NOT)

For each legal option the scorer derives, using **only** your own visible board and the
offered select menu:

| feature | source | honesty bound |
|---|---|---|
| `family` | option `type` code | coarse action family label only |
| `resolved_card_id` | option `area`/`index` → your `hand` (zone 2) / offered `select.deck` (zone 1); bare `index` → hand | a card's identity is read from YOUR visible hand or the OFFERED list; never from hidden hand/deck/prize |
| `target_card_id`, `target_area` | `inPlayArea` (4 = active, 5 = bench), `inPlayIndex` into your own board | only WHICH of your pokemon the option points at, never that the target is correct |
| `target_energy_count` | length of the target's visible energy list | a visible count, not a damage/lethal claim |
| `productive_alternatives` | whether a non-end-turn option remains | menu shape only |

The card identity is mapped to a **coarse role bucket** via an embedded per-deck role map
(`card_id → [tokens]`), built offline from the local `EN_Card_Data.csv` for **only** that
deck's ids. Tokens: `energy`, `basic`, `evo`, `item`, `supporter`, `tool`, `stadium`,
`search`, `draw`, `attacker`, `ex`.

> **Card-CSV caveat.** The shared `cards/role_tags.tag_roles` tagger mis-parses this CSV
> (it keys off the mostly-`n/a` `Category` column and the presence of an `HP` *key*, so it
> tags essentially every card `Basic Pokémon`). 46H instead reuses the audited
> `pilot_typed.compiler` classifier, which reads the correct
> `Stage (Pokémon)/Type (Energy and Trainer)` column with the energy → trainer-marker →
> `pok` ordering (so "Pokémon Tool" is correctly a Trainer). See
> `.agents/memory/card-data-csv-quirks.md`.

## The linear model

Two transparent layers:

```
family_score = bias + family_weight                    # identical schema to 46F/46G floor
option_value = Σ role_weight[token(resolved_card)]
             + target_area_weight + per_energy_weight × target_energy_count
             + Σ tgt_role_weight[token(target_card)]
             + end_with_alternatives_penalty            # only when ending with plays left
```

Combined two ways:

- **additive** — `score = family_score + option_value`
- **lexicographic** — `score = family_score × LEX_SCALE + option_value`, with
  `LEX_SCALE = 1e6` and `|option_value|` bounded well below it (asserted in validation), so
  the family layer **strictly** dominates and the option layer only ever breaks ties
  *within* a family.

With no `option_weights` (and/or an empty role map) `option_value ≡ 0`, so the model
reduces **exactly** to the family-only floor ordering. That is the control profile.

## The three profiles

| profile | mode | option layer | role |
|---|---|---|---|
| `family_only_floor_v1` | additive | inert | control == 46F/46G family floor |
| `option_value_v1` | additive | interpretable per-bucket priors | does the option layer change picks / track the oracle? |
| `conservative_option_value_v1` | lexicographic | same priors, tie-break only | a strictly safer variant that never overrides the family floor |

The per-bucket weights are **hand-set interpretable priors** (`OPTION_VALUE_PRIORS`),
derived from ordinary deck-building priors (develop your board: play basics / search /
draw; value attaching to an active attacker over an idle bench sitter; avoid passing while
productive plays remain). They are **not** fitted per card id — per-id fitting would
memorise the 46F label frames. Part E *measures* these priors against the oracle; it does
not tune per-card weights to it.

## Honesty ledger

The scorer refuses to assert: exact damage, lethal, missed-KO, Boss/gust, spread,
globally-best action, any card value / expected-value / win-probability, or any use of
hidden state. See `unsupported_scorer_claims()` for the stable contract enforced by tests.

## Purity / embedding

The region between `INLINE_OPTION_VALUE_V0_BEGIN` / `..._END` is pure-builtin (no
annotations, no imports, no `src` references) and is embedded **verbatim** into a candidate
`main.py`. A parity test re-extracts the region from each built tarball and asserts it is
byte-identical **and** behaviourally identical to this module. Import does no I/O; every
public function returns a safe value rather than raising.
