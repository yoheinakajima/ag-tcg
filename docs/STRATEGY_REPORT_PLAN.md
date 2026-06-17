# Strategy Report Plan

The competition has a Strategy Category: explaining *how* the agent was built and
improved. This project is designed to produce that report **from evidence** in
the event log rather than from memory.

Generator: `src/ptcg_activegraph/reporting/report_generator.py` →
`data/reports/strategy_report_draft.md` (run `python scripts/generate_report.py`).

## How this maps to the Strategy Category

The narrative we can defend with data:

* A **two-system architecture** that keeps the competing agent simple while a
  rich lab drives improvement.
* An **event-sourced** development loop where every decision is recorded and
  attributable.
* A **regime taxonomy** that constrains and validates each change, guarding
  against overfitting and instability.

## Report outline

The generator emits these sections (scaffold with TODOs until data exists):

1. Executive summary
2. Agent architecture
3. Deck concept
4. ActiveGraph event-sourced development loop
5. Regimes taxonomy
6. Stability methodology
7. Heuristic policy
8. Belief/search roadmap
9. Local evaluation results
10. Failure analysis
11. Promoted/rejected changes
12. Known limitations
13. Next experiments

## Evidence to collect

| Section | Evidence (event types / projections) |
| --- | --- |
| Local evaluation | `GameEnded` results via `MatchSummaryProjection` |
| Deck concept | `DeckPerformanceProjection` win rates per `deck_version` |
| Failure analysis | `FailureTagged` via `FailureSummaryProjection` |
| Regimes | `RegimeSelected` counts |
| Promoted/rejected | `PatchPlanCreated`, `PolicyPromoted`, `DeckPromoted` |
| Stability | `ActionFallbackUsed` rate, zero `exception` tags |

## Metrics to show

* Win rate (overall and per deck/policy version).
* Fallback rate (lower is better; stability proxy).
* Failure-tag distribution and trend across policy versions.
* Validation pass/fail per patch plan, with thresholds.
* Time-per-decision distribution (once search is enabled).

## Workflow

```bash
make selfplay GAMES=200      # populate events (needs cabt)
make tournament              # deck/policy comparisons
make report                  # regenerate the draft from the log
```

As experiments accumulate, the draft fills in automatically; hand-edit the prose
sections (architecture, methodology) for the final submission.
