---
name: Water pilot ctx7 search-pivot ordering
description: The bench-empty anti-disruption pivot masks the prize-liability pivot in choose_to_hand; how to test/ground ctx7 levers
---

In the core_pilot Water decision policy, the ctx7 `search_to_hand` handler evaluates
flag-gated pivots in a fixed order. The bench-empty **anti-disruption** search pivot is
checked FIRST: whenever the bench is empty it fetches a backup benchable Basic and
returns immediately. Only if it does NOT fire is the later **prize-liability** search
pivot reached.

**Consequence:** on a board with an empty bench, the prize-liability pivot can never
be the lever that fires even when its own predicate (mega-exposed AND no 1-prize
attacker in play AND a primary attacker is searchable) is satisfied — the result may be
the right card but via the anti-disruption rationale, so a test asserting the
prize-liability path will fail.

**Why:** both pivots can select the same backup Basic, but they are distinct levers
with distinct rationales and fire-conditions; the earlier one short-circuits.

**How to apply:** to exercise, ground, or fixture the prize-liability ctx7 pivot (or
any pivot added AFTER anti-disruption), use a **non-empty bench** that still lacks a
1-prize attacker (e.g. active + bench both the 2-prize Mega payoff). More generally,
when adding a new ctx7 lever, decide its ordering deliberately and remember earlier
pivots can mask it on collapsing boards.
