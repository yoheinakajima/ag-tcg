---
name: lifecycle auto-quarantine evidence
description: Honesty rule for the tournament candidate-lifecycle classifier — auto-applied demotions require COMPLETE hard-failure evidence; draws are non-decisive but NOT failures.
---

# Auto-quarantine must require complete hard-failure evidence

Quarantine is the ONLY auto-applied (no human opt-in) status demotion in the
candidate lifecycle manager. Its "all invalid" branch must require
`invalid == games`, NOT merely `decisive == 0 and invalid >= floor`.

**Why:** a draw is non-decisive (`decisive == wins + losses`) but a draw is NOT a
hard failure. The naive `decisive == 0 and invalid >= 3` test would auto-quarantine
a deck with e.g. 3 invalid + 4 draws (invalid_rate 0.43) even though it never
actually hard-failed every game. Auto-demotions on incomplete evidence are a safety
violation — the deck looks bad only because draws were miscounted as "no signal."

**How to apply:** any auto-applied lifecycle action (this branch, or future ones)
must key off complete/total evidence (`invalid == games`, or an explicit rate gate
like `invalid_rate >= 0.5 over >= N games`), never off `decisive == 0` alone. Decks
with mixed draws fall through to the rate branch or to retain/soft-probation
(human-gated), never to auto-quarantine. Same spirit as report-honesty: don't let a
non-failure outcome masquerade as a failure.
