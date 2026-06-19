---
name: Board-wide discard refutes per-Pokémon color mismatch
description: Why a naive per-Pokémon energy color-match check can falsely flag a deck as misplaying.
---

When diagnosing whether a pilot "attaches the wrong color energy," a per-Pokémon
attach-vs-Pokémon-type check is NOT a valid error signal for attacks that consume
energy from across the **whole board**.

**Why:** Raging Bolt ex's Bellowing-Thunder attack discards Fighting + Lightning from
the entire board (including energy on benched Ogerpon), so F/L attached to a benched
Pokémon still feeds the attack's cost. A naive "this energy doesn't match this
Pokémon's type" check would flag it as a misplay when it is actually correct. The
trace proved `attach_off_deck_plan = 0` and `attack_available_not_taken = 0`, so both
the color-match and attack-pressure hypotheses were REFUTED; the Raging Bolt loss is
structural (deck skeleton / bad matchup), not a pilot color error.

**How to apply:**
- Prove causality from the action trace; do not assume color-matching from win rate or
  per-Pokémon type alone.
- For board-wide-cost attacks, judge energy correctness against the deck plan / attack
  cost source, not the host Pokémon's own type.
