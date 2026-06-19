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
