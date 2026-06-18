#!/usr/bin/env python3
"""Extract meta archetypes from the replay corpus and write the meta reports.

Reads every replay in ``data/meta_replays/`` (via
``analyze_meta_replay.analyze_replay``), assigns each to the closest documented
strategy track (see ``docs/META_ENGINE_STRATEGIES.md``), and writes:

* ``data/meta/meta_archetypes.json``
* ``data/meta/top_policy_patterns.md``
* ``data/meta/top_deck_skeletons.md``

Honest about coverage: with no replays present this writes an explicit
*scaffolding-only* report listing the four preserved strategy tracks and zero
extracted archetypes. **Card ids are never invented** — track assignment uses
roles/coverage only, and unknown ids stay unknown.

Usage:
    python scripts/extract_meta_archetypes.py
    python scripts/extract_meta_archetypes.py --replays-dir data/meta_replays --out-dir data/meta
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401
from analyze_meta_replay import analyze_replay

# Preserved strategy tracks (labels + policy seam). Card NAMES come from
# docs/META_ENGINE_STRATEGIES.md; no numeric ids are asserted here.
STRATEGY_TRACKS = [
    {
        "id": "psychic_setup_control",
        "name": "Alakazam/Dunsparce Psychic setup-control",
        "policy_seam": "missing-piece planner",
        "signals": "low energy, high tutor density, Abra/Kadabra/Alakazam line, Dunsparce draw engine",
    },
    {
        "id": "lightning_ramp",
        "name": "Bellibolt/Kilowattrel Lightning ramp",
        "policy_seam": "ramp plan and exact tutor target selection",
        "signals": "electric ramp engine, Tadbulb/Bellibolt, Wattrel/Kilowattrel acceleration",
    },
    {
        "id": "generic_engine",
        "name": "Generic engine-deck pattern",
        "policy_seam": "plan-state tracker + discard-protection for plan pieces",
        "signals": "lower energy, high search/redundancy, plan-state tracking, bench-width setup",
    },
    {
        "id": "chaos_engine_disruption",
        "name": "Chaos as engine-supported disruption",
        "policy_seam": "payoff condition tied to an observable opponent signal",
        "signals": "Froslass handCount / Durant deckCount / bench-bloat / status — visible signals only",
    },
]


def _iter_replays(replays_dir: str | Path):
    d = Path(replays_dir)
    if not d.is_dir():
        return
    for path in sorted(d.glob("*.json")):
        if path.name.startswith("_"):
            continue
        yield path


def _classify(analysis: dict) -> dict:
    """Assign a strategy track when evidence allows; else 'unclassified'.

    With only scaffolding (no role/card data) every replay is 'unclassified'
    with low confidence — we never guess a track from a thin sample.
    """
    if not analysis.get("ok"):
        return {"track": "unclassified", "confidence": "none",
                "reason": "replay unreadable"}
    sk = analysis["deck_skeleton"]
    roles = sk.get("role_counts") or {}
    if not roles or sk.get("coverage") != "full":
        return {"track": "unclassified", "confidence": "low",
                "reason": "insufficient role/card metadata to assign a track"}
    # Real assignment logic is a future-work hook once replays carry roles/names.
    return {"track": "unclassified", "confidence": "low",
            "reason": "track matcher is a future-work hook; awaiting named-card replays"}


def extract_archetypes(replays_dir: str | Path = "data/meta_replays") -> dict:
    analyses = [analyze_replay(p) for p in _iter_replays(replays_dir)]
    classified = []
    for a in analyses:
        cls = _classify(a)
        classified.append({
            "replay": a.get("replay"),
            "coverage": a.get("coverage"),
            "track": cls["track"],
            "confidence": cls["confidence"],
            "reason": cls["reason"],
            "deck_skeleton": a.get("deck_skeleton"),
            "early_policy": a.get("early_policy"),
        })
    return {
        "replays_dir": str(replays_dir),
        "n_replays": len(analyses),
        "n_archetypes_extracted": 0,  # scaffolding: nothing classified into a track yet
        "strategy_tracks": STRATEGY_TRACKS,
        "classified": classified,
        "coverage": "empty" if not analyses else "partial",
        "uncertainty_notes": [
            "No replays present — archetypes not yet extracted (scaffolding only)."
            if not analyses else
            "Replays present but track matcher is a future-work hook; assignments are 'unclassified'.",
            "Card ids are never invented; unknown ids stay unknown.",
            "Four strategy tracks are preserved as the labelling vocabulary.",
        ],
    }


def _write_policy_md(summary: dict, out_path: Path) -> None:
    lines = ["# Top Policy Patterns (meta engine backlog)", ""]
    lines.append(f"Replays analyzed: **{summary['n_replays']}** "
                 f"(coverage: {summary['coverage']}).")
    lines.append("")
    lines.append("Preserved policy seams per strategy track:")
    lines.append("")
    for t in summary["strategy_tracks"]:
        lines.append(f"- **{t['name']}** — policy seam: _{t['policy_seam']}_")
        lines.append(f"  - signals: {t['signals']}")
    lines.append("")
    if summary["n_replays"]:
        lines.append("## Per-replay early-policy fingerprints")
        lines.append("")
        for c in summary["classified"]:
            ep = c.get("early_policy") or {}
            lines.append(f"- `{c['replay']}` — track={c['track']} "
                         f"(confidence {c['confidence']}); coverage={ep.get('coverage','?')}")
            for n in ep.get("notes", []):
                lines.append(f"  - {n}")
    else:
        lines.append("_No replays present; early-game policy patterns will be filled "
                     "once real top-player replays are added._")
    lines.append("")
    lines.append("## Uncertainty")
    lines.append("")
    for n in summary["uncertainty_notes"]:
        lines.append(f"- {n}")
    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def _write_skeletons_md(summary: dict, out_path: Path) -> None:
    lines = ["# Top Deck Skeletons (meta engine backlog)", ""]
    lines.append(f"Replays analyzed: **{summary['n_replays']}** "
                 f"(coverage: {summary['coverage']}).")
    lines.append("")
    if summary["n_replays"]:
        for c in summary["classified"]:
            sk = c.get("deck_skeleton") or {}
            lines.append(f"## `{c['replay']}`")
            lines.append(f"- track: {c['track']} (confidence {c['confidence']})")
            lines.append(f"- coverage: {sk.get('coverage','?')}")
            lines.append(f"- cards: {sk.get('card_count')} | energy: {sk.get('energy_count')} | "
                         f"pokemon: {sk.get('pokemon_count')} | trainer: {sk.get('trainer_count')}")
            lines.append(f"- unknown-id cards: {sk.get('unknown_id_cards', 0)}")
            for n in sk.get("notes", []):
                lines.append(f"  - {n}")
            lines.append("")
    else:
        lines.append("_No replays present; deck skeletons will be extracted once real "
                     "top-player replays are added. No card IDs are invented._")
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--replays-dir", default="data/meta_replays")
    parser.add_argument("--out-dir", default="data/meta")
    args = parser.parse_args()

    summary = extract_archetypes(args.replays_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "meta_archetypes.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")
    _write_policy_md(summary, out_dir / "top_policy_patterns.md")
    _write_skeletons_md(summary, out_dir / "top_deck_skeletons.md")

    print(json.dumps({
        "n_replays": summary["n_replays"],
        "n_archetypes_extracted": summary["n_archetypes_extracted"],
        "out": [
            str(out_dir / "meta_archetypes.json"),
            str(out_dir / "top_policy_patterns.md"),
            str(out_dir / "top_deck_skeletons.md"),
        ],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
