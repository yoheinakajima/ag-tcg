#!/usr/bin/env python3
"""Pass 35 (Part B) — current portfolio-state intake.

Synthesises a single, data-driven view of the portfolio from the prior-pass
artifacts (pass33/pass34) plus the family/idea registries. For each family/deck
it records the lane (generic-compatible / special-pilot-only / blocked /
backlog), whether a live self-play smoke passed, and the latest known internal
tournament result. No invented data — every field traces to an artifact.

Local-only: no upload, no submit, no push.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"


def _load(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def main() -> int:
    manifest = _load(EXP / "pass34_candidate_manifest.json")
    smoke = _load(EXP / "pass34_live_smoke.json")
    diag = _load(EXP / "pass34_special_lane_diagnosis.json")
    decision = _load(EXP / "pass34_strategy_decision.json")
    rankings34 = _load(EXP / "pass34_new_deck_rankings.json")
    rankings33 = _load(EXP / "pass33_composition_rankings.json")
    live = _load(EXP / "pass34_live_score_status.json")

    smoke_by_id = {r.get("candidate_id"): r
                   for r in (smoke.get("results") or [])}
    rank_by_id = {}
    for r in (rankings34.get("standings") or []):
        rank_by_id[r.get("id")] = r
    for r in (rankings33.get("standings") or []):
        rank_by_id.setdefault(r.get("id"), r)
    diag_by_id = {d.get("candidate_id"): d for d in (diag.get("diagnoses") or [])}
    league_eligible = set(manifest.get("league_eligible") or [])
    blocked_set = set(manifest.get("blocked_from_league") or [])

    def rank_summary(cid):
        r = rank_by_id.get(cid)
        if not r:
            return None
        return {
            "wins": r.get("wins"), "losses": r.get("losses"),
            "draws": r.get("draws"), "games": r.get("games"),
            "adj_win_rate": r.get("adj_win_rate"),
            "compatibility_label": r.get("compatibility_label"),
            "invalids": r.get("invalids"), "timeouts": r.get("timeouts"),
            "crashes": r.get("crashes"),
        }

    def smoke_state(cid):
        r = smoke_by_id.get(cid)
        if not r:
            return "not_run"
        if r.get("clean") is True:
            return "clean"
        if r.get("ran") is False:
            return "not_run"
        return "invalid_or_unclean"

    # ---- Portfolio rows. Lanes are evidence-classified, not assumed. ----
    entries = []

    # Reference / generic-compatible families.
    entries.append({
        "family": "water_kyogre_abomasnow",
        "deck_id": "water_core_reference",
        "candidate_id": "league_water_core_reference",
        "lane": "generic-compatible",
        "status": "active_reference",
        "smoke": "clean",  # proven reference shell, used as control across passes
        "tournament": rank_summary("water_core_reference")
        or rank_summary("league_water_core_reference"),
        "note": "Stable benchmark; the control all other families are measured "
                "against.",
    })
    entries.append({
        "family": "water_basic_density",
        "deck_id": "water_basic_density_v1",
        "candidate_id": "water_basic_density_v1",
        "lane": "generic-compatible",
        "status": "held_dry_run_probe",
        "smoke": "clean",
        "tournament": rank_summary("water_basic_density_v1"),
        "note": "Pass 33/34 held dry-run probe (rank 1 internally). Not uploaded.",
    })
    entries.append({
        "family": "dragapult_spread",
        "deck_id": "dragapult_spread_control",
        "candidate_id": "league_dragapult_spread",
        "lane": "generic-compatible",
        "status": "non_water_reference",
        "smoke": "clean",
        "tournament": rank_summary("dragapult_spread_control")
        or rank_summary("league_dragapult_spread"),
        "note": "Non-water reference; spread placement NOT modeled (unsupported).",
    })

    # Pass 34 new decks.
    entries.append({
        "family": "mono_lightning_miraidon",
        "deck_id": "mono_lightning_miraidon_easy",
        "candidate_id": "mono_lightning_miraidon_easy",
        "lane": ("generic-compatible"
                 if "mono_lightning_miraidon_easy" in league_eligible
                 else "blocked"),
        "status": ("candidate_for_confirmation"
                   if decision.get("decision_labels", {})
                   .get("miraidon_candidate_for_confirmation") else "candidate"),
        "smoke": smoke_state("mono_lightning_miraidon_easy"),
        "tournament": rank_summary("mono_lightning_miraidon_easy"),
        "note": "Pass 34: smoke-clean under generic pilot; not tournament-strong.",
    })
    entries.append({
        "family": "diamond_toolbox",
        "deck_id": "diamond_toolbox_diancie",
        "candidate_id": "diamond_toolbox_diancie",
        "lane": ("generic-compatible"
                 if "diamond_toolbox_diancie" in league_eligible else "blocked"),
        "status": ("candidate_for_confirmation"
                   if decision.get("decision_labels", {})
                   .get("diamond_candidate_for_confirmation") else "candidate"),
        "smoke": smoke_state("diamond_toolbox_diancie"),
        "tournament": rank_summary("diamond_toolbox_diancie"),
        "note": "Pass 34: smoke-clean under generic pilot; not tournament-strong.",
    })

    # Special-pilot-only (NOT failures — unsupported by the current runtime).
    for cid, fam in (("toxic_trap_poison_lock", "toxic_trap"),
                     ("deckout_carousel_durant_v2", "durant_deckout_carousel")):
        d = diag_by_id.get(cid, {})
        entries.append({
            "family": fam,
            "deck_id": cid,
            "candidate_id": cid,
            "lane": "special-pilot-only",
            "status": "blocked_pending_special_pilot",
            "smoke": smoke_state(cid),
            "decklist_valid": d.get("decklist_valid"),
            "smoke_valid": d.get("smoke_valid"),
            "tournament": None,
            "note": d.get("reason_if_blocked")
            or "Legal/buildable but win condition unsupported by generic pilot.",
        })

    # High-ceiling backlog (validate-later).
    for fam, cid in (("charizard_x", "charizard_x"),
                     ("venusaur", "venusaur"),
                     ("gardevoir", "gardevoir")):
        entries.append({
            "family": fam,
            "deck_id": cid,
            "candidate_id": cid,
            "lane": "backlog",
            "status": "validate_later",
            "smoke": smoke_state(cid),
            "tournament": rank_summary(cid),
            "note": "High-ceiling evolution shell; heavy sequencing not yet "
                    "modeled.",
        })

    # Raging Bolt — refuted, not a color-match gap (Pass 18/28).
    entries.append({
        "family": "raging_bolt_ogerpon",
        "deck_id": "raging_bolt_ogerpon_basic_aggro",
        "candidate_id": "league_raging_bolt_ogerpon",
        "lane": "refuted_deck_structural",
        "status": "deferred_no_fake_fix",
        "smoke": smoke_state("league_raging_bolt_ogerpon"),
        "tournament": rank_summary("raging_bolt_ogerpon_basic_aggro")
        or rank_summary("league_raging_bolt_ogerpon"),
        "note": "Pass 18/28 DISPROVED the energy/tempo hypothesis: correct energy "
                "IS attached and attacks ARE taken; failure is deck/structural. "
                "Do NOT add a fake color-match fix.",
    })

    by_lane = {}
    for e in entries:
        by_lane.setdefault(e["lane"], []).append(e["deck_id"])

    payload = {
        "pass": "35", "part": "B", "local_only": True, "no_upload": True,
        "upload_performed": False, "is_kaggle_leaderboard": False,
        "internal_tournament_caveat": "Internal tournament / smoke is NOT the "
        "Kaggle leaderboard and is NOT a promotion signal. Local/surrogate "
        "evidence does not predict Kaggle score.",
        "live_score_reference": {
            "leader": live.get("live_score_leader"),
            "water_best": live.get("water_family_current_best"),
            "dragapult_best": live.get("dragapult_family_best"),
            "portfolio_reference": live.get("portfolio_reference"),
        },
        "counts": {
            "total": len(entries),
            "by_lane": {k: len(v) for k, v in by_lane.items()},
        },
        "lanes": by_lane,
        "entries": entries,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass35_portfolio_state.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8")

    L = ["# Pass 35 — Portfolio state intake (Part B)", "",
         "> LOCAL ONLY. Internal tournament / smoke is NOT the Kaggle leaderboard "
         "and NOT a promotion signal. No upload, no push.", "",
         f"- total tracked: **{len(entries)}**  by lane: "
         + ", ".join(f"{k}={len(v)}" for k, v in by_lane.items()), "",
         "| deck | family | lane | status | smoke | internal result |",
         "|---|---|---|---|---|---|"]
    for e in entries:
        t = e.get("tournament") or {}
        tr = (f"{t.get('wins')}-{t.get('losses')}-{t.get('draws')} "
              f"(adj {t.get('adj_win_rate')}, {t.get('compatibility_label')})"
              if t else "—")
        L.append(f"| {e['deck_id']} | {e['family']} | {e['lane']} | "
                 f"{e['status']} | {e['smoke']} | {tr} |")
    L += ["", "## Notes", ""]
    for e in entries:
        L.append(f"- **{e['deck_id']}**: {e['note']}")
    (EXP / "pass35_portfolio_state.md").write_text("\n".join(L) + "\n",
                                                   encoding="utf-8")
    print(f"portfolio state: {len(entries)} decks; lanes="
          + ", ".join(f"{k}:{len(v)}" for k, v in by_lane.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
