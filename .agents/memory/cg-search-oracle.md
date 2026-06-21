---
name: cg Search outcome oracle
description: Honesty + correctness rules for the cg Search one-step oracle/planner and calibrating it against replay traces.
---

# cg Search outcome oracle + one-step planner

A never-raise, subprocess-isolated wrapper over the native cg Search API
(`search_begin`/`search_step`/`search_end`/`search_release`) that predicts a
frame's one-step post-state and ranks legal one-step actions, calibrated against
replay traces.

## cg must stay in the subprocess
- The core module imports cg NOWHERE at module top; cg / `libcg.so` is imported
  ONLY inside the subprocess worker, behind a bounded wall-clock.
  **Why:** the native lib can hang uninterruptibly in-process (in-thread SIGALRM
  can't reliably kill a native call); a child process can be wall-clock killed.
  **How to apply:** any new cg call goes through the worker, never a direct import
  in importable code.

## Hidden-state honesty (never over-claim)
- Hidden zones (opponent deck/hand/prize, your prize, sometimes your deck) are
  filled by COUNT ONLY with placeholder basic-Pokémon ids — label every result
  `assumption_based_hidden_state`. Never read or claim opponent hand CONTENTS.
- Permanently unsupported, asserted in tests, never claimed: exact_damage,
  lethal, missed_ko, boss_gust, spread, best_action. Ranking output is only
  `one_step_score_rank under assumption`, not a best/optimal action.

## Calibration causality = ACTIVE seat on BOTH sides
- A replay step holds one object per seat; the INACTIVE seat carries a STALE
  observation/action from its last turn. The source action frame AND the
  next-frame ground-truth `current` must BOTH come from the seat with
  `status == "ACTIVE"`. If no ACTIVE seat exposes a next `current`, SKIP the frame
  — never fall back to a non-ACTIVE (stale) current.
  **Why:** mixing in INACTIVE rows silently breaks causal alignment and poisons
  every downstream metric (and thus the gated decision); the corruption is
  invisible because the stale rows look structurally valid. It was found only by
  auditing which seat each calibrated frame came from.
  **How to apply:** any trace-frame selector for this engine must filter
  `status == ACTIVE`; keep the regression test that fails if an INACTIVE frame is
  admitted, and assert the ground-truth picker has no stale fallback.
- Residual mismatch is `turn`-dominated at setup / turn-ending KO transitions plus
  hand/deck COUNT drift from drawing the fabricated deck — genuine hidden-state
  limits, expected, not a bug.

## Runtime shape
- Per native search step is sub-millisecond-ish (batch path imports cg once per
  chunk). But per-eval/per-rank WALL is dominated by subprocess spawn + cg import,
  so live per-move use is diagnostic-grade, not turn-loop-latency-grade.
