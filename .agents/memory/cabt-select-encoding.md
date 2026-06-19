---
name: cabt select.context + option encoding
description: How cabt replay/runtime select options encode actions; how to detect a "bench a basic" sub-action.
---
# cabt select.context + option encoding (reverse-engineered from replays)

Each decision is a `observation.select` dict. Options live under key `option`
(aliases `options`/`choices`). `select.context` integers seen in real episodes:

- **0** = Main action phase (by far the most frequent select). mn=mx=1.
- 1 = choose active at setup (mn=mx=1)
- 2 = choose bench at setup (multi)
- 7 = search-to-hand (mn=0,mx=1)
- 8 = discard (multi)
- 38 = choose-a-number (e.g. draw count)
- others (3,19,30,41) = effect-specific sub-selects.

Option `type` integers (within ctx 0 Main):
- **7** = play a card from hand BY HAND INDEX. Keys: `{index,type}` (no `area`).
  The played card = own `hand[option["index"]]`. Covers BOTH trainers and
  basic-Pokémon-to-bench plays. A "bench a benchable Basic" sub-action is a
  type-7 option whose `hand[index]` card has role `primary_basic_attacker` or
  `setup_basic`.
- **8** = attach energy from hand to a target. Keys: `{area=2,index,inPlayArea,inPlayIndex,type}`.
- **13** = attack. Keys: `{attackId,type}`. (Highest base score.)
- **14**/**12** = end-turn / pass (no args).
- 9/10 = other in-play / play actions (resolve via area to in-play or hand).

**Why:** detecting a bench-play sub-action at runtime (ctx0) requires reading
`option.type==7` then `hand[index]` and checking the card's role — `resolve_option_card`
in state.py only handles `area` 1/2 and returns None for type-7 (no area field).
**How to apply:** Mega Abomasnow ex (723) is only OFFERED as a play when a Snover
is in play to evolve onto — it is never a bench play, confirming it is NOT a
benchable basic. Benchable basics in the water deck = Kyogre 721, Snover 722.
