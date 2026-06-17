"""Strategy report generator.

Generates ``data/reports/strategy_report_draft.md`` from the event log when
data exists, otherwise a scaffold with TODOs. The section list maps to the
competition's Strategy Category. See ``docs/STRATEGY_REPORT_PLAN.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ..graph.events import Event
from . import markdown_templates as T
from .metrics import compute_metrics

DEFAULT_REPORT_PATH = Path("data/reports/strategy_report_draft.md")


def generate_strategy_report(
    events: Iterable[Event] | None = None,
    out_path: str | Path = DEFAULT_REPORT_PATH,
) -> Path:
    """Write the strategy report and return its path."""
    events = list(events or [])
    metrics = compute_metrics(events) if events else None

    parts: list[str] = [T.REPORT_TITLE, ""]
    parts.append(
        "_Auto-generated draft. Regenerate with "
        "`python scripts/generate_report.py`._\n"
    )

    # 1. Executive summary
    parts.append(T.h2("Executive summary"))
    if metrics and metrics["total_matches"]:
        parts.append(
            T.kv_table(
                [
                    ("Matches recorded", metrics["total_matches"]),
                    ("Win rate", metrics["win_rate"]),
                    ("Fallback rate", metrics["fallback_rate"]),
                    ("Total failures tagged", metrics["failures"]["total_failures"]),
                ]
            )
        )
    else:
        parts.append(
            T.todo(
                "No match events yet. Run local self-play (see "
                "docs/LOCAL_SIMULATION.md) to populate metrics."
            )
        )

    # 2. Agent architecture
    parts.append(T.h2("Agent architecture"))
    parts.append(
        "Two systems: a compact, deterministic Kaggle runtime agent "
        "(`main.py` / `agent.py`, standard-library only) and the ActiveGraph "
        "lab that records, classifies, validates and promotes improvements. "
        "The runtime cascade is: parse observation -> optional cabt search "
        "(off by default) -> heuristic ranking -> guaranteed-legal fallback -> "
        "validate. See docs/RUNTIME_AGENT.md and docs/ARCHITECTURE.md.\n"
    )

    # 3. Deck concept
    parts.append(T.h2("Deck concept"))
    if metrics and metrics["deck_performance"]:
        parts.append("Per-deck performance:\n")
        for deck, rec in metrics["deck_performance"].items():
            parts.append(f"- `{deck}`: {rec}\n")
    else:
        parts.append(
            T.todo(
                "Ingest the official card CSV, pick an initial archetype, and "
                "record per-deck win rates here. See docs/CARD_AND_DECK_GRAPH.md."
            )
        )

    # 4. ActiveGraph loop
    parts.append(T.h2("ActiveGraph event-sourced development loop"))
    parts.append(
        "Every match, observation, legal frontier, chosen/candidate action, "
        "belief, search result, failure, patch, validation run, deck version, "
        "policy version and promotion decision is an append-only event in "
        "`data/matches/events.jsonl`. Projections fold these into match/deck/"
        "policy/failure summaries. See docs/ACTIVEGRAPH.md.\n"
    )

    # 5. Regimes taxonomy
    parts.append(T.h2("Regimes taxonomy"))
    parts.append(
        "Failures are classified into regimes (STABILITY, DECK_CONSTRUCTION, "
        "SEQUENCING, PRIZE_RACE, BELIEF_HIDDEN_INFORMATION, META_LEADERBOARD, "
        "UNKNOWN). Each regime constrains the allowed patch seams, the "
        "validation protocol, and the promotion rule. See docs/REGIMES.md.\n"
    )
    if metrics and metrics["failures"]["regimes"]:
        parts.append(f"Observed regimes: {metrics['failures']['regimes']}\n")

    # 6. Stability methodology
    parts.append(T.h2("Stability methodology"))
    parts.append(
        "The runtime agent never crashes outward: every policy defers to a "
        "guaranteed-legal fallback, outputs are clamped to maxCount/minCount "
        "and validated for range/uniqueness. Stability regressions block "
        "promotion regardless of win-rate gains.\n"
    )

    # 7. Heuristic policy
    parts.append(T.h2("Heuristic policy"))
    parts.append(
        "v1 ranks legal options by keyword/field signals (knockout, prize, "
        "attack, evolve, attach energy, draw, search, ...) with cautious "
        "penalties for end/pass/discard, tie-broken by lower option index. "
        "Crude but stable; weights are a tunable patch seam.\n"
    )

    # 8. Belief/search roadmap
    parts.append(T.h2("Belief/search roadmap"))
    parts.append(
        "BeliefState extracts known own/opponent visible state and counts; a "
        "WorldSampler will draw plausible hidden states (opponent hand/deck/"
        "prizes) to feed `cabt.search_begin` for shallow lookahead. Search is "
        "off by default until validated within the time budget.\n"
    )

    # 9. Local evaluation results
    parts.append(T.h2("Local evaluation results"))
    if metrics and metrics["total_matches"]:
        parts.append(
            T.kv_table(
                [
                    ("Wins", metrics["wins"]),
                    ("Losses", metrics["losses"]),
                    ("Draws", metrics["draws"]),
                    ("Total actions", metrics["total_actions"]),
                ]
            )
        )
    else:
        parts.append(T.todo("Populate by running tournaments once cabt is installed."))

    # 10. Failure analysis
    parts.append(T.h2("Failure analysis"))
    if metrics and metrics["failures"]["tags"]:
        parts.append(f"Failure tag counts: {metrics['failures']['tags']}\n")
    else:
        parts.append(T.todo("No failures tagged yet; classifier runs over match traces."))

    # 11. Promoted/rejected changes
    parts.append(T.h2("Promoted/rejected changes"))
    parts.append(
        T.todo(
            "Record PatchPlan outcomes (PolicyPromoted/DeckPromoted vs rejected) "
            "as they accumulate."
        )
    )

    # 12. Known limitations
    parts.append(T.h2("Known limitations"))
    parts.append(
        "- cabt/kaggle-environments may not be installed locally; simulation "
        "paths are guarded skeletons until then.\n"
        "- Card/deck metadata depends on the official CSV being present.\n"
        "- Belief sampler and search policy are scaffolded, not yet wired into "
        "live decisions.\n"
    )

    # 13. Next experiments
    parts.append(T.h2("Next experiments"))
    parts.append(
        "1. Install cabt + kaggle-environments.\n"
        "2. Ingest official card CSV and tag roles.\n"
        "3. Choose an initial archetype deck.\n"
        "4. Baseline random vs fallback vs heuristic.\n"
        "5. Wire belief-sampled shallow search.\n"
        "6. Run deck tournaments and promote the best.\n"
    )

    content = "\n".join(parts) + "\n"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    return out_path
