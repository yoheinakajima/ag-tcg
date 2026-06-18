# Pass 8 Lessons (carried into Pass 9)

Five durable lessons from Pass 8 that shaped the Pass 9 architecture. These are
recorded as the rationale behind the `ArchitectureDecisionRecorded` event and the
move to declarative, deck-specific playbooks.

1. **A generic policy cannot encode line-coherence.** Effect-resolution choices
   (which card to fetch / discard / decline) are deck-specific: the "right" answer
   depends on the Kyogre/Abomasnow line, not on a generic heuristic. This is why
   Pass 9 compiles *deck-specific playbooks* rather than tuning one global policy.

2. **The hard fixture gate beats raw win rate as a promotion filter.** A candidate
   can sit at ~50% win rate while still making catastrophic line-breaking plays
   that the win rate averages out. The fixture gate catches those specific failures
   deterministically, so promotion is gated on *no hard failures*, not on win rate
   alone.

3. **Each safety guard is load-bearing — they are complementary, not redundant.**
   The Pass 9 ablations confirm this empirically: dropping any single guard
   reintroduces exactly one hard-fixture failure (drop the evolution/Mega-Signal
   guard → orphan-Mega fixture fails; drop the deckout guard → deckout fixture
   fails). `combo_full_safety_v3` (all five guards) is the minimal safe set.

4. **Durable, resumable evaluation is mandatory in this sandbox.** Long or
   backgrounded processes are killed, so evaluation must run as bounded foreground
   chunks that write per-game state to the ActiveGraph ledger and resume cleanly.
   Every Pass 9 run (80 + 70 + 120 games) survived mid-chunk kills with zero lost
   games because of this.

5. **Partial safety combinations regress; full safety holds.** Combining only some
   guards underperforms the full combination. The safe play is to keep all five
   guards together; this is the configuration the declarative v2 playbook encodes
   and the one the Track A confirmation validated at 80 games.
