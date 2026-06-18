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

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

REPO = Path(__file__).resolve().parents[1]
REGISTRY_JSON = REPO / "data" / "meta_replays" / "replay_registry.json"
ARCHETYPES_YAML = REPO / "data" / "meta_replays" / "archetypes.yaml"
ARCHETYPES_MD = REPO / "data" / "meta_replays" / "archetypes.md"

# Confidence ordering: a single confirmed seat outranks any number of provisionals.
_CONFIDENCE_RANK = {"confirmed": 2, "provisional": 1, "unknown": 0}

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


def build_replay_archetypes(registry: dict) -> dict:
    """Aggregate the registry's per-seat classifications into archetype rows.

    Each archetype row carries: ``archetype_id``, ``confidence`` (best across
    contributing seats), ``evidence_card_ids`` / ``evidence_card_names`` (union),
    ``replay_episode_ids``, ``player_indices`` (``"<episode>:p<seat>"``),
    ``deck_fingerprints`` and ``notes``. Card ids are only ever the union of ids
    that the classifier already saw in real extracted decks — none are invented.
    """
    rows: dict[str, dict] = {}
    for rec in registry.get("records", []):
        ep = rec.get("episode_id")
        for seat in rec.get("seats", []):
            arch = seat.get("archetype")
            if not arch:
                continue
            aid = arch.get("archetype_id", "unknown")
            row = rows.setdefault(aid, {
                "archetype_id": aid,
                "confidence": "unknown",
                "evidence_card_ids": set(),
                "evidence_card_names": set(),
                "replay_episode_ids": set(),
                "player_indices": set(),
                "deck_fingerprints": set(),
                "is_ours": bool(seat.get("is_ours")),
                "notes": set(),
            })
            if _CONFIDENCE_RANK.get(arch.get("confidence"), 0) > \
                    _CONFIDENCE_RANK.get(row["confidence"], 0):
                row["confidence"] = arch.get("confidence", "unknown")
            row["evidence_card_ids"].update(arch.get("evidence_card_ids", []))
            row["evidence_card_names"].update(arch.get("evidence_card_names", []))
            if ep is not None:
                row["replay_episode_ids"].add(ep)
            row["player_indices"].add(f"{ep}:p{seat.get('seat')}")
            fpr = seat.get("fingerprint") or {}
            if fpr.get("multiset_deck_sha256"):
                row["deck_fingerprints"].add(fpr["multiset_deck_sha256"])
            row["is_ours"] = row["is_ours"] or bool(seat.get("is_ours"))
            for n in arch.get("notes", []):
                row["notes"].add(n)

    archetypes = []
    for aid in sorted(rows):
        r = rows[aid]
        archetypes.append({
            "archetype_id": aid,
            "confidence": r["confidence"],
            "is_ours": r["is_ours"],
            "evidence_card_ids": sorted(r["evidence_card_ids"]),
            "evidence_card_names": sorted(r["evidence_card_names"]),
            "replay_episode_ids": sorted(r["replay_episode_ids"], key=str),
            "player_indices": sorted(r["player_indices"]),
            "deck_fingerprints": sorted(r["deck_fingerprints"]),
            "notes": sorted(r["notes"]),
        })

    confirmed = [a["archetype_id"] for a in archetypes
                 if a["confidence"] == "confirmed" and not a["is_ours"]]
    provisional = [a["archetype_id"] for a in archetypes
                   if a["confidence"] == "provisional"]
    return {
        "schema": "activegraph.meta_replays.archetypes/v1",
        "pass": "11b",
        "hard_rules": [
            "never invent card ids; evidence ids come only from extracted decks",
            "confidence is confirmed/provisional/unknown; unknown carries no claim",
        ],
        "source_registry": str(REGISTRY_JSON.relative_to(REPO)),
        "n_archetypes": len(archetypes),
        "confirmed_opponent_archetypes": sorted(set(confirmed)),
        "provisional_archetypes": sorted(set(provisional)),
        "archetypes": archetypes,
    }


def _write_replay_archetypes_md(obj: dict, out_path: Path) -> None:
    lines = ["# Replay-derived archetypes (Pass 11B)", ""]
    lines.append(f"- archetypes found: **{obj['n_archetypes']}**")
    lines.append(f"- confirmed opponent archetypes: "
                 f"{', '.join(obj['confirmed_opponent_archetypes']) or 'none'}")
    lines.append(f"- provisional archetypes: "
                 f"{', '.join(obj['provisional_archetypes']) or 'none'}")
    lines.append(f"- source: `{obj['source_registry']}`")
    lines.append("")
    lines.append("| archetype | confidence | ours | episodes | evidence ids |")
    lines.append("|---|---|---|---|---|")
    for a in obj["archetypes"]:
        lines.append(
            f"| {a['archetype_id']} | {a['confidence']} | "
            f"{'yes' if a['is_ours'] else 'no'} | "
            f"{', '.join(str(e) for e in a['replay_episode_ids']) or '-'} | "
            f"{', '.join(str(c) for c in a['evidence_card_ids']) or '-'} |"
        )
    lines.append("")
    for a in obj["archetypes"]:
        lines.append(f"## {a['archetype_id']} ({a['confidence']})")
        names = ", ".join(a["evidence_card_names"]) or "—"
        lines.append(f"- evidence cards: {names}")
        lines.append(f"- seats: {', '.join(a['player_indices'])}")
        for n in a["notes"]:
            lines.append(f"- note: {n}")
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def write_replay_archetypes(registry_path: Path = REGISTRY_JSON) -> dict:
    """Build + persist ``archetypes.{yaml,md}`` from the replay registry."""
    if not registry_path.exists():
        return {}
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    obj = build_replay_archetypes(registry)
    if yaml is not None:
        ARCHETYPES_YAML.write_text(
            yaml.safe_dump(obj, sort_keys=False, allow_unicode=True),
            encoding="utf-8")
    else:  # pragma: no cover - yaml always present in this repo
        ARCHETYPES_YAML.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    _write_replay_archetypes_md(obj, ARCHETYPES_MD)
    return obj


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

    # Pass 11B: replay-derived archetypes aggregated from the registry.
    replay_obj = write_replay_archetypes()

    print(json.dumps({
        "n_replays": summary["n_replays"],
        "n_archetypes_extracted": summary["n_archetypes_extracted"],
        "replay_archetypes": replay_obj.get("n_archetypes", 0) if replay_obj else 0,
        "confirmed_opponent_archetypes":
            replay_obj.get("confirmed_opponent_archetypes", []) if replay_obj else [],
        "out": [
            str(out_dir / "meta_archetypes.json"),
            str(out_dir / "top_policy_patterns.md"),
            str(out_dir / "top_deck_skeletons.md"),
            str(ARCHETYPES_YAML.relative_to(REPO)) if replay_obj else None,
            str(ARCHETYPES_MD.relative_to(REPO)) if replay_obj else None,
        ],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
