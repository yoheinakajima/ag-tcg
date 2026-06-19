#!/usr/bin/env python3
"""Rebuild ``experiments/meta_pool.yaml`` from the replay-derived archetypes and
the live Kaggle score registry (Pass 11B).

Pipeline::

    data/meta_replays/archetypes.yaml        (Part D — replay-derived archetypes)
    data/kaggle_uploads/live_score_registry.json (Part B — dynamic active control)
    data/meta_replays/replay_analysis.json   (Part E — opponent frequencies)
        -> experiments/meta_pool.yaml
        -> data/meta_replays/meta_pool_summary.md

This replaces the older Pass-10/10B blocked-coverage map: metal_ex_zacian_ramp and
water_kyogre_abomasnow_maxbelt now have real, extracted surrogate decks (their
replays were acquired), so they are CONFIRMED, not blocked. The active control is
re-derived DYNAMICALLY from the live score registry, never hardcoded.

Hard rules: never invent a card id (evidence ids pass straight through from the
registry), never modify root files, never upload.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

ARCHETYPES_YAML = REPO / "data" / "meta_replays" / "archetypes.yaml"
LIVE_REGISTRY = REPO / "data" / "kaggle_uploads" / "live_score_registry.json"
REPLAY_ANALYSIS = REPO / "data" / "meta_replays" / "replay_analysis.json"
OUT_POOL = REPO / "experiments" / "meta_pool.yaml"
OUT_SUMMARY = REPO / "data" / "meta_replays" / "meta_pool_summary.md"

# Historical live scores preserved by identity for the Pass 10 report cross-check.
REFERENCE_V1_SCORE = 363.0
REFERENCE_V2_SCORE = 355.2
HISTORICAL_COMBO_SCORE = 294.0


def _load_yaml(path: Path) -> dict:
    if not path.exists() or yaml is None:
        return {}
    obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    return obj if isinstance(obj, dict) else {}


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _surrogate_deck_for(archetype: dict) -> str | None:
    """Pick a representative extracted surrogate deck from a player index.

    ``player_indices`` look like ``"<episode>:p<seat>"``; the matching extracted
    deck is ``data/meta_replays/decks/<episode>_p<seat>_deck.csv``.
    """
    for pi in archetype.get("player_indices", []):
        if ":" in pi:
            ep, seat = pi.split(":p", 1)
            cand = REPO / "data" / "meta_replays" / "decks" / f"{ep}_p{seat}_deck.csv"
            if cand.exists():
                return str(cand.relative_to(REPO))
    return None


def _opponent_frequencies(analysis: dict) -> dict[str, int]:
    return dict(analysis.get("opponent_archetype_counts") or {})


def build_meta_pool(archetypes_obj: dict, registry: dict,
                    analysis: dict) -> dict:
    ac = registry.get("active_control") or {}
    freqs = _opponent_frequencies(analysis)

    pool_archetypes: list[dict] = []
    opponent_weights: dict[str, float] = {}
    confirmed_external: list[str] = []
    provisional: list[str] = []
    available: list[str] = []
    blocked: list[str] = []

    for a in archetypes_obj.get("archetypes", []):
        key = a["archetype_id"]
        is_ours = bool(a.get("is_ours"))
        confidence = a.get("confidence", "unknown")
        surrogate = _surrogate_deck_for(a)
        episodes = a.get("replay_episode_ids", [])

        if surrogate:
            available.append(key)
        else:
            blocked.append(key)

        if not is_ours:
            if confidence == "confirmed":
                confirmed_external.append(key)
            elif confidence == "provisional":
                provisional.append(key)
            # Opponent weight by observed frequency (real encounters only).
            opponent_weights[key] = float(freqs.get(key, 0))

        pool_archetypes.append({
            "key": key,
            "status": ("confirmed_from_replay" if confidence == "confirmed"
                       else confidence),
            "confidence": confidence,
            "is_ours": is_ours,
            "surrogate_deck": surrogate,
            "replay_episode": episodes[0] if episodes else None,
            "replay_episodes": episodes,
            "evidence_card_ids": a.get("evidence_card_ids", []),
            "weight": None if is_ours else float(freqs.get(key, 0)),
        })

    # Normalize opponent weights over observed frequency.
    total = sum(opponent_weights.values()) or 0.0
    if total > 0:
        eval_weights = {k: round(v / total, 4) for k, v in opponent_weights.items()
                        if v > 0}
    else:
        eval_weights = {}
    # Push normalized weights back into the archetype rows.
    for row in pool_archetypes:
        if row["key"] in eval_weights:
            row["weight"] = eval_weights[row["key"]]

    # Weight that lands on confirmed-confidence opponents (vs provisional bucket).
    weight_confirmed = sum(w for k, w in eval_weights.items()
                           if k in confirmed_external)
    weight_provisional = sum(w for k, w in eval_weights.items()
                             if k in provisional)

    # Coverage status: usable when >= 2 distinct opponent archetypes have a real
    # surrogate deck (regardless of confidence); partial with exactly one;
    # incomplete with none.
    opp_with_surrogate = [k for k in (confirmed_external + provisional)
                          if k in available]
    if len(set(opp_with_surrogate)) >= 2:
        coverage_status = "usable"
    elif len(set(opp_with_surrogate)) == 1:
        coverage_status = "partial"
    else:
        coverage_status = "incomplete"

    pool = {
        "schema": "activegraph.meta.pool/v2",
        "pass": "11b",
        "generated_by": "scripts/update_meta_pool_from_replays.py",
        "sources": {
            "archetypes": str(ARCHETYPES_YAML.relative_to(REPO)),
            "live_scores": str(LIVE_REGISTRY.relative_to(REPO)),
            "replay_analysis": str(REPLAY_ANALYSIS.relative_to(REPO)),
        },
        "controls": {
            "active_control": {
                "candidate_id": (_ac_file := ac.get("fileName") or ac.get("filename") or "").replace(".tar.gz", "")
                or "unknown",
                "submission_file": _ac_file or None,
                "live_public_score": ac.get("publicScore", ac.get("public_score")),
                "status": ac.get("status", "complete" if (ac.get("publicScore") or ac.get("public_score")) is not None else None),
                "selection_rule":
                    "highest publicScore among complete non-error submissions",
                "note": (
                    "Dynamic active control from the live score registry. "
                    "Promoted from Pass-10 live_rejected@294 after live scores "
                    "shifted; see historical_combo."
                ),
            },
            "reference_v1": {
                "candidate_id": "v1",
                "submission_file": "submission.tar.gz",
                "live_public_score": REFERENCE_V1_SCORE,
                "status": "complete",
            },
            "reference_v2": {
                "candidate_id": "deck_energy_trim_light",
                "live_public_score": REFERENCE_V2_SCORE,
                "status": "complete",
            },
            "historical_combo": {
                "candidate_id": "combo_full_safety_v3_fixed_historical",
                "live_public_score": HISTORICAL_COMBO_SCORE,
                "status": "complete",
                "decision": "live_rejected",
                "superseded_by": "active_control",
                "note": "Pass-10-era score, superseded in Pass 11B.",
            },
        },
        "archetypes": pool_archetypes,
        "evaluation_weights": eval_weights,
        "coverage": {
            "coverage_status": coverage_status,
            "confirmed_archetypes": sorted(set(confirmed_external)),
            "provisional_archetypes": sorted(set(provisional)),
            "blocked_archetypes": sorted(set(blocked)),
            "available_archetypes": sorted(set(available)),
            "weight_confirmed": round(weight_confirmed, 4),
            "weight_provisional": round(weight_provisional, 4),
            "weight_missing": 0.0 if not blocked else None,
            "eval_complete": False,
            "games_runnable_locally": True,
            "conclusion": _conclusion(coverage_status, confirmed_external,
                                      provisional, weight_provisional),
        },
    }
    return pool


def _conclusion(status: str, confirmed: list[str], provisional: list[str],
                weight_provisional: float) -> str:
    return (
        f"Meta coverage is {status.upper()}: "
        f"{len(set(confirmed))} opponent archetype(s) are CONFIRMED from real "
        f"extracted replays ({', '.join(sorted(set(confirmed))) or 'none'}), and "
        f"{len(set(provisional))} provisional bucket(s) "
        f"({', '.join(sorted(set(provisional))) or 'none'}) hold real surrogate "
        f"decks but lack a precise named signature ({weight_provisional:.0%} of "
        f"opponent weight). Local cabt self-play is runnable, so candidates can be "
        f"evaluated against these surrogates — but the provisional bucket means the "
        f"eval is not a fully named meta and no candidate is auto-promotable."
    )


def to_summary_md(pool: dict) -> str:
    cov = pool["coverage"]
    ac = pool["controls"]["active_control"]
    lines = ["# Meta pool summary (Pass 11B)", ""]
    lines.append(f"- coverage status: **{cov['coverage_status']}**")
    lines.append(f"- active control (live): **{ac['candidate_id']}** "
                 f"@ {ac['live_public_score']} ({ac['status']})")
    lines.append(f"- confirmed opponent archetypes: "
                 f"{', '.join(cov['confirmed_archetypes']) or 'none'}")
    lines.append(f"- provisional archetypes: "
                 f"{', '.join(cov['provisional_archetypes']) or 'none'}")
    lines.append(f"- blocked archetypes: "
                 f"{', '.join(cov['blocked_archetypes']) or 'none'}")
    lines.append("")
    lines.append("## Evaluation weights (opponent frequency)")
    for k, v in pool["evaluation_weights"].items():
        lines.append(f"- {k}: {v}")
    if not pool["evaluation_weights"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Archetypes")
    lines.append("| key | confidence | ours | surrogate deck | weight |")
    lines.append("|---|---|---|---|---|")
    for a in pool["archetypes"]:
        lines.append(
            f"| {a['key']} | {a['confidence']} | "
            f"{'yes' if a['is_ours'] else 'no'} | "
            f"`{a['surrogate_deck'] or '-'}` | {a['weight']} |"
        )
    lines.append("")
    lines.append("## Conclusion")
    lines.append(cov["conclusion"])
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    archetypes_obj = _load_yaml(ARCHETYPES_YAML)
    registry = _load_json(LIVE_REGISTRY)
    analysis = _load_json(REPLAY_ANALYSIS)
    if not archetypes_obj:
        print("no archetypes.yaml found; run extract_meta_archetypes.py first")
        return 1

    pool = build_meta_pool(archetypes_obj, registry, analysis)

    header = (
        "# Meta pool — Pass 11B (replay-derived, auto-generated)\n"
        "#\n"
        "# Regenerate with: python scripts/update_meta_pool_from_replays.py\n"
        "# Active control is DYNAMIC (live score registry); archetype confidence\n"
        "# and surrogate decks come from real extracted replays. No card id is\n"
        "# invented. metal_ex_zacian_ramp and water_kyogre_abomasnow_maxbelt are\n"
        "# now CONFIRMED (their replays were acquired in Pass 11B).\n\n"
    )
    if yaml is not None:
        body = yaml.safe_dump(pool, sort_keys=False, allow_unicode=True)
    else:  # pragma: no cover
        body = json.dumps(pool, indent=2)
    OUT_POOL.write_text(header + body, encoding="utf-8")
    OUT_SUMMARY.write_text(to_summary_md(pool), encoding="utf-8")

    cov = pool["coverage"]
    print(f"meta pool updated: coverage={cov['coverage_status']}")
    print(f"  confirmed: {cov['confirmed_archetypes']}")
    print(f"  provisional: {cov['provisional_archetypes']}")
    print(f"  active control: {pool['controls']['active_control']['candidate_id']} "
          f"@ {pool['controls']['active_control']['live_public_score']}")
    print(f"  -> {OUT_POOL.relative_to(REPO)}")
    print(f"  -> {OUT_SUMMARY.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
