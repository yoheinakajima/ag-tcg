---
name: standing tournament engine v0 (Pass 36)
description: Operational conventions for the reusable ActiveGraph tournament engine and the background-shell quirk that shapes how it must be run.
---

# Standing ActiveGraph Tournament Engine v0

Reusable, event-first, resumable, bounded-tick self-play tournament living at
`src/ptcg_activegraph/tournament/` (config·pool·ledger·artifacts·scheduler·
projections·runner), driven by `scripts/tournament_daemon_tick.py`. Replaces the
deprecated per-pass one-off tournament scripts. Internal diagnostics only — NOT a
Kaggle leaderboard; performs NO upload/auto-submit and generates no candidates.

## Durable constraints (keep future passes consistent)
- **Run long work as repeated bounded synchronous ticks, never a long-lived loop
  or `nohup` background job.** In this environment a background/`nohup` process is
  killed when the launching tool call returns, and the bash tool caps at ~120s.
  The engine is built resumable precisely so interrupted/short runs are safe.
  **Why:** discovered when a backgrounded smoke run died with an empty log; two
  synchronous daemon ticks reproduced the full smoke instead.
  **How to apply:** size `--max-games` so a tick fits the shell budget (~11s per
  cabt game), and rely on resume across ticks rather than one big run.
- **Projections must stay rebuildable from the event ledger alone.** The candidate
  registry is reconstructed from `TournamentParticipantRegistered` full snapshots
  (`CandidatePool.from_events`), so every candidate must be registered once with a
  complete snapshot; results fold over `GameFinished`. Don't reintroduce a
  dependency on `candidate_pool.json` for rebuilding projections.
- **`run_tick` is single-run locked** via a non-blocking flock at
  `data/tournament/.tick.lock` (raises `TickInProgressError`). Keep concurrent
  invocations from racing to schedule duplicate game ids.
- zstd is unavailable in this env → game sidecars fall back to gzip; record the
  codec honestly (`artifacts.sidecar_codec()`), never claim zstd.
