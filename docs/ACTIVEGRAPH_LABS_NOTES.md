# ActiveGraph Strategy Lab — Operator Notes

The lab is a transparent "experiment factory" wrapped around the immutable v1
Kaggle control baseline (public score **349.8**). It enumerates strategy seams,
generates candidate variants in isolated run directories, evaluates them locally
against the control with the real `cabt` engine, records every step as an
ActiveGraph event, ranks the survivors, and queues (but never auto-submits)
Kaggle uploads.

## The loop

```
plan -> generate -> run (local cabt) -> rank -> report -> queue (dry-run)
   |        |            |                |        |          |
 IdeaGenerated  Branch/Variant   LocalEvaluation  Candidate  Submission
                Created          MatchBatch...    Ranked     Queued
                                 MetricsComputed
```

Every arrow emits immutable JSONL events to
`data/activegraph/lab_events.jsonl` (inspect with `make ag-summary`).

## Files you edit

| File | Purpose |
|------|---------|
| `experiments/experiment_plan.yaml` | **Control surface.** Priorities, local-eval budget, submission safety switches. Edit freely. |
| `experiments/strategy_seams.yaml` | Machine-readable seam taxonomy (5 families). |
| `docs/STRATEGY_SEAMS.md` | Human description of the seams + capability gates. |

The lab scripts **read** your priorities; they never rewrite them.

## Files the lab writes (safe to delete/regenerate)

- `experiments/runs/<ts>_<branch_id>/` — one isolated dir per candidate
  (`main.py`, `deck.csv`, `branch.yaml`, `metrics.json`, `submission.tar.gz` when queued).
- `data/activegraph/lab_events.jsonl` — the event stream.
- `data/experiments/latest_ranking.{json,md}` — the ranking.
- `data/submission_queue.json` — the (dry-run) queue plan.
- `data/site/*.html` + `style.css`, `data/reports/activegraph_strategy_report.md` — the report.

## Commands

```bash
make plan-experiments        # what is testable now, by priority
make generate-candidates LIMIT=8
make run-experiments GAMES=5 # local cabt eval vs control (needs cabt)
make rank-candidates
make report-site
make queue-submissions       # DRY-RUN; never uploads
make ag-summary              # event-stream summary
make lab-batch               # the whole loop end to end
```

## Candidate tracks

- **Policy candidates** = baseline `main.py` + an *append-only* override block
  inserted before the `if __name__` guard. It only reassigns scoring globals
  (`_OPTION_TYPE_SCORES`, `_ATTACK_ID_BONUS`, `_POSITIVE`, `_NEGATIVE`), which the
  runtime reads at call time. The result stays standard-library-only and
  self-contained — nothing the engine packages changes structurally.
- **Deck candidates** = baseline `main.py` + a mutated 60-card deck. Deltas are
  grounded in `data/cards/EN_Card_Data.csv`; **no card ids are invented**. Only
  basic energy may exceed 4 copies, so energy is the trim source and non-energy
  cards are bumped at most to 4. Every deck is re-validated and smoke-tested.

## Ranking (fully inspectable)

Hard rejects (never promotable): package-verify fail, smoke fail, any crash, any
timeout. Survivors get a soft score: `win_rate*1000 + attack_rate*120
- pass_rate*120 - fallbacks*5` (deck variants also `- entropy*10`), plus a
per-family diversity bonus so the top of the board isn't one seam family.

## Safety

See `docs/AUTOSUBMIT_SCHEDULE.md`. With the shipped defaults nothing is ever
uploaded — `auto_submit_enabled: false` and `require_manual_approval_for_submit:
true`. The root `main.py` / `deck.csv` (the v1 control) are treated as immutable
and are never modified by the lab.

## Local-eval gotchas

If a batch reports everyone drawing / `win_rate 0.0` / `decisions 0`, the cabt
games are not actually playing. See `.agents/memory/cabt-local-eval.md`: decks
must be passed via `configuration={"decks": [...]}`, the agent callable must
accept the extra positional args cabt passes, and `debug=False` hides agent
exceptions as 2-step draws (reproduce with `debug=True`).
