---
name: ActiveGraph lab script operations
description: Operational gotchas when running the experiments lab scripts (generate/run/rank/queue/report).
---

# Running the lab scripts

- **Always run lab scripts from the repo root**, not from `scripts/`. Output paths
  in the experiments package (e.g. `data/experiments/...`, `data/reports/...`,
  `data/site/...`) are **cwd-relative `Path(...)` constants**, while `_bootstrap`
  only fixes the import path (adds `src/` to `sys.path`). Running from `scripts/`
  still imports fine but silently writes a stray `scripts/data/` tree, so ranking/
  report artifacts land in the wrong place.
  **How to apply:** `python scripts/rank_candidates.py ...` from repo root, never
  `cd scripts && python rank_candidates.py`.

- **`run_experiment_batch.py` can hang after all per-candidate `metrics.json` are
  written** (the post-eval step appears to stall in this environment). The metrics
  are complete and valid at that point, so it is safe to kill the process and run
  `rank_candidates.py --stage <stage>` separately to finish.
  **Why:** avoids waiting indefinitely on a stuck batch when the actual game
  evaluation already finished.

- A full 6-candidate × 10-game seat-swap batch exceeds the 2-minute tool limit;
  run it as a backgrounded process and poll, or kill once metrics exist.
