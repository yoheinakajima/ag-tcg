# Auto-Submit Schedule & Safety Policy

**Current status: auto-submit is DISABLED. Nothing is uploaded to Kaggle by the
lab.** This document describes how submission *would* be scheduled if/when an
operator deliberately enables it.

## The three locks (ALL must align to upload)

A submission can only be uploaded when **every** one of these is true:

1. `scripts/submit_queue.py` is invoked with `--i-understand-this-uploads`
   (explicit human acknowledgement on the command line), **and**
2. `settings.auto_submit_enabled: true` in `experiments/experiment_plan.yaml`, **and**
3. `settings.require_manual_approval_for_submit: false` in the same file.

With the shipped defaults (`auto_submit_enabled: false`,
`require_manual_approval_for_submit: true`), `submit_queue.py` prints exactly what
it *would* run and exits without uploading. `queue_submissions.py` is always
dry-run and only ever builds tarballs + writes the queue plan.

## Daily budget

- `settings.kaggle_daily_submission_limit` (default **3**) — the competition's
  daily cap. Configurable because competition limits change.
- `submission_queue.max_per_day` (default **3**) — how many of the top-ranked,
  promotable candidates the queue will stage per day. The effective cap is
  `min(max_per_day, kaggle_daily_submission_limit)`.

Only candidates that passed **every** hard gate (package verify, smoke, no
crashes, no timeouts) are eligible to be queued.

## Intended cadence (when enabled by an operator)

| When | Action | Command |
|------|--------|---------|
| Generate ideas | Plan + generate candidates | `make plan-experiments` / `make generate-candidates` |
| Evaluate | Local cabt batch vs control | `make run-experiments GAMES=20` |
| Select | Rank + report | `make rank-candidates` / `make report-site` |
| Stage | Build dry-run queue | `make queue-submissions` |
| Check budget | Read-only Kaggle status | `make fetch-kaggle-status` |
| Submit (gated) | Upload top `max_per_day` | `python scripts/submit_queue.py --i-understand-this-uploads` |
| Record result | Log public score as event | `python scripts/ag_event.py kaggle-score --name <branch> --score <n>` |

Recommended: run at most one batch + one ranking per day, submit no more than
`kaggle_daily_submission_limit` candidates, and always record the returned public
score with `ag_event.py kaggle-score` so the next ranking can learn from it.

## What is never automated

- No GitHub push.
- No Kaggle upload without the three locks above.
- No modification of the root `main.py` / `deck.csv` (the immutable v1 control).
- No fabricated scores: Kaggle results are only recorded from real, operator-
  confirmed values.
