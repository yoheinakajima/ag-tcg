---
name: Replay post-mortem pitfalls (cabt lab)
description: Non-obvious traps when post-morteming Kaggle replays — Grok summaries, Mega-evolution bench detection, and the live-score-registry key mismatch that nulls active_control.
---

# Replay post-mortem pitfalls

Learned doing replay post-mortems for `pokemon-tcg-ai-battle`. None are obvious from code.

## Trust replay board state, NOT the Grok natural-language summary
Grok's per-replay summaries are reliably correct on coarse facts (win/loss result, turn
number within ±1, opponent archetype) but can be **wrong on the loss *mechanism***. In one
batch Grok labeled all three losses "empty-board / no-Pokémon" yet the replay final
observations showed the loser had an active + bench present (lost to a multi-prize ex KO) or
**decked out with a healthy bench**. Always reclassify the loss from `rewards` +
`observation.current.players[loser]` board state, not from the prose.
**Why:** acting on Grok's mechanism claim would have "fixed" a failure mode that wasn't
recurring. **How to apply:** in any Grok-claim verifier, treat result/turn/archetype as
checkable hints but derive loss_type strictly from replay state.

## Mega Abomasnow ex (723) on the bench is usually legitimate evolution, not a bug
723 is an evolution payoff played on top of a benched Snover (722). A naive "is 723 ever on
the bench?" check yields a **false positive** for illegal from-hand benching. Correct test:
723 is benched-from-hand only if it appears on the bench in a game where 722 was **never
benched first**. **How to apply:** track snover_seen before flagging 723; reuse for both the
hook-effectiveness and no-Pokémon post-mortem scripts so they agree.

## live_score_registry.json active_control uses camelCase keys (fileName/publicScore)
The meta-pool regenerator read `ac.get("filename")` / `ac.get("public_score")`, but the
registry's `active_control` object uses **`fileName`** and **`publicScore`** (no `status`
field). The key mismatch silently degraded `experiments/meta_pool.yaml.controls.active_control`
to `unknown/null` even though the registry knew the real control. **Why:** downstream passes
read meta_pool for the control and would be misled. **How to apply:** when wiring the live
registry into meta-pool, accept both key spellings and synthesize `status:"complete"` when a
score is present.

## Option-level action-class resolver: "end" is ONLY raw option type==14
When resolving cabt legal-option records to action classes, tag `end` **strictly** on
`type == 14`. A tempting fallback like `(index is None and area is None) -> end` is WRONG: it
swallows ctx38 draw-count options (type 0) and ctx41 yes/no options (type 1/2), which also
carry no index/area, inflating the `end` count and corrupting every downstream class
distribution. **Why:** those contexts have no card and no zone, so they look like "end" but
are not. **How to apply:** route by context after the type==14 check — ctx38→draw_count,
ctx41→unknown(binary), ctx7→search_to_hand, ctx8→discard, else classify from card type_line.

## "Engine-forced" means no legal alternative, not just min==max
A decision is only engine-FORCED (agent had no real choice) when
`min_count>0 AND min_count==max_count AND num_options <= min_count`. Using `min==max` alone
massively overstates forced-ness — a "pick exactly 1" with 5 options is a free choice, not
forced. This matters in inert-hook diagnosis: the looser test reported 56/141 ctx7 windows as
forced when the correct count was 0. **Why:** overstating forced-ness fabricates a
"no-alternative" excuse that hides genuinely steerable decisions. **How to apply:** always
include the option-count clause; prefer deriving from the mined ledger's `num_options`.
