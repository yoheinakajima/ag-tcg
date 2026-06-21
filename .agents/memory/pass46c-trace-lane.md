---
name: pass46c frame-persisting trace lane
description: how the local read-only decision-frame trace lane runs cabt games and why its safety gate must run fresh every invocation
---

# Frame-persisting diagnostic trace lane (local, read-only)

A bounded reusable LOCAL lane that RUNS cabt games and persists the FULL `env.steps`
decision frames so future passes can compare turn-planning behavior vs references.

- **make("cabt") works locally** even though the env is not a kaggle built-in and
  `cabt` package is null: it self-registers at import, and one game is ~0.5s. The
  existing `_run_game` keeps only `len(env.steps)` — to persist frames you need your
  own worker that dumps the whole `env.steps`.
- `env.steps` IS the `FMT_KAGGLE_REPLAY` shape (list of `[seat0,seat1]`, each with
  `.observation.{current,select,logs,step}`), so the turn_planning extractor decodes a
  `{"id","steps":env.steps,...}` gzip wrapper directly — **no extractor extension needed**.
  Store a `steps_sha256` over the steps payload for round-trip integrity.
- **Native wedges are non-deterministic**: a matchup that runs in 0.5s solo can hang the
  open_spiel C engine on another run. Each game MUST run in `subprocess.run(timeout=...)`
  (in-proc SIGALRM can't interrupt native C) with a short timeout + one retry.
- **Bash tool caps at 120s** but the full panel can exceed it → make the runner
  **resumable + budgeted**: skip already-OK traces, stop at a per-invocation wall-clock
  budget, rebuild the manifest from persisted traces. Call it repeatedly until complete.

## Safety gate must be fresh every run (architect-caught)
**Rule:** the Part-A stop-gate's DYNAMIC prod-state checks (refs absent from pool +
worklist, no forbidden events in prod ledger, deployment target, auto_submit falsy) must
re-run on EVERY invocation. Do NOT short-circuit them by reusing a cached
`*_safety_preflight.json` just because root `main.py`/`deck.csv` hashes still match.
**Why:** prod state can drift after a cached preflight; a resumed run that reuses the old
gate makes the readiness decision stale/dishonest. The prod load is one read-only fetch
per invocation (not per game), so freshness is cheap. Static root-immutability hashes are
the only thing safe to treat as cacheable, and even they must not bypass the dynamic checks.
