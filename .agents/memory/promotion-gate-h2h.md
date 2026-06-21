---
name: promotion gate H2H + ledger forbidden-event scoping
description: Why the internal promotion gate demands direct head-to-head superiority (not aggregate), and why the standing TournamentLedger refuses Kaggle/promotion events while the generic EventStore still emits them.
---

# Promotion gate: direct H2H superiority, not aggregate out-farming

The internal Promotion Gate (`src/ptcg_activegraph/tournament/promotion.py`) must
gate on **direct head-to-head superiority**, never on an aggregate record alone:

- ACTIVATE (probation→active) requires the *aggregate* Wilson lower bound AND the
  *direct parent-H2H* Wilson lower bound to clear `parent_baseline + activate_wilson_margin`.
- PROMOTE_FAMILY_CHAMPION requires the aggregate margin vs the incumbent's baseline AND a
  *direct champion-H2H* of at least `champion_min_h2h_games` decisive games whose Wilson
  lower bound clears `parent_baseline + champion_margin`. No champion / zero H2H games
  blocks safely (baseline_exists False, h2h_enough False) — it must never crash or pass.

**Why:** a review caught a hole where a candidate could be activated/crowned by
out-farming weak opponents in the aggregate while *losing* head-to-head to its parent or
the incumbent champion. Aggregate-only superiority is not evidence it beats the thing it
must replace. Never weaken these back to aggregate-only to force a promotion.

**How to apply:** when touching the gate, keep the AND of aggregate + direct-H2H bounds.
Negative tests must stay: high-aggregate-but-loses-parent-H2H → stay_probation;
aggregate-margin-passes-but-loses-champion-H2H → insufficient_evidence.

# Two separate EventStores — forbidden-event scoping

`TournamentLedger` (standing tournament, `data/tournament/events.jsonl`) is a SEPARATE
EventStore from the generic `EventStore()` default (`data/matches/events.jsonl`) used by
`experiments/queue.py` and `experiments/ranker.py`.

- `TournamentLedger._FORBIDDEN` refuses `SubmissionQueued`, `SubmissionUploaded`,
  `KaggleScoreUpdated`, and `CandidatePromoted` at emit time; the only lifecycle event it
  allows is `CandidateStatusChanged`.
- The generic EventStore legitimately emits `SubmissionQueued` / `CandidatePromoted` for
  the real Kaggle submission/ranking flow.

**Why:** refusing those types on the tournament ledger does NOT break the Kaggle
producers (different store/path). Conversely, never extend the forbidden set onto the
generic EventStore — that would break ranker/queue.

**How to apply:** before assuming a forbidden-event change breaks something, confirm which
EventStore (which path) the producer writes to.
