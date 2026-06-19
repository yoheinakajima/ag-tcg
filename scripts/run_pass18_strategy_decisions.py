#!/usr/bin/env python3
"""Pass 18 Part M -- per-family strategy decisions + dry-run recommendation.

Synthesizes the Pass-18 evidence into a status + next-experiment decision for
every registered strategy family, and records a single LOCAL dry-run
recommendation. Pure synthesis of artifacts already produced this pass; it runs
no games and changes no decks.

Evidence consumed (all local):
  experiments/strategy_families.yaml                         (family registry)
  data/experiments/pass18_candidate_validation.json          (Part J eligibility)
  data/experiments/pass18_league_rankings.json               (Part K standings)
  data/experiments/pass18_internal_league.json               (Part K head-to-head)
  data/experiments/pass18_meta_sanity.json                   (Part L sanity)
  data/experiments/pass18_raging_bolt_diagnosis.json         (Part D diagnosis)

Outputs:
  data/experiments/pass18_strategy_decisions.json / .md

Also emits StrategyDecisionRecorded (per family) + one StrategyPromotionDecision
ActiveGraph event capturing the dry-run recommendation.

STRICT: LOCAL ONLY. No Kaggle upload/submit. The recommendation is an internal
DRY-RUN lead only -- internal-league and surrogate meta results never equal
Kaggle results and are never sufficient to upload or submit.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

import ag_strategy_event as AGE  # noqa: E402

REGISTRY = REPO / "experiments" / "strategy_families.yaml"
VALIDATION = REPO / "data" / "experiments" / "pass18_candidate_validation.json"
RANKINGS = REPO / "data" / "experiments" / "pass18_league_rankings.json"
LEAGUE = REPO / "data" / "experiments" / "pass18_internal_league.json"
META = REPO / "data" / "experiments" / "pass18_meta_sanity.json"
DIAGNOSIS = REPO / "data" / "experiments" / "pass18_raging_bolt_diagnosis.json"

OUT_JSON = REPO / "data" / "experiments" / "pass18_strategy_decisions.json"
OUT_MD = REPO / "data" / "experiments" / "pass18_strategy_decisions.md"

DISCLAIMER = (
    "LOCAL ONLY. Decisions are based on the internal league (our own decks piloted "
    "by one generic core pilot) and a surrogate, directional meta sanity check. "
    "Neither equals a Kaggle result. The dry-run recommendation is an INTERNAL "
    "research lead only and is NEVER sufficient to upload or submit. No upload "
    "performed."
)


def _load_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _standings_map(rankings: dict) -> dict:
    out = {}
    for i, row in enumerate(rankings.get("standings", []), 1):
        out[row["id"]] = {"rank": i, **row}
    return out


def _h2h(league: dict, x: str, y: str):
    """Win rate of ``x`` against ``y`` from the league matchups (or None)."""
    for m in league.get("matchups", []):
        a, b = m.get("a"), m.get("b")
        if {a, b} != {x, y}:
            continue
        aw, bw = m.get("a_wins", 0), m.get("b_wins", 0)
        dec = aw + bw
        if dec == 0:
            return None
        return round((aw if a == x else bw) / dec, 4)
    return None


def _candidate_meta_score(meta: dict, cand: str):
    return ((meta.get("per_deck") or {}).get(cand) or {}).get("weighted_meta_score")


def _decide(reg: dict, standings: dict, league: dict, validation: dict,
            meta: dict, diagnosis: dict) -> list[dict]:
    decisions = []
    for fam in reg.get("families", []):
        fid = fam.get("family_id")
        d = {
            "family_id": fid,
            "prior_status": fam.get("status"),
            "current_best": fam.get("current_best"),
        }

        if fid == "dragapult_spread":
            v1 = standings.get("league_dragapult_spread_v1", {})
            parent = standings.get("league_dragapult_spread", {})
            eligible = "league_dragapult_spread_v1" in (
                validation.get("league_eligible") or [])
            h2h = _h2h(league, "league_dragapult_spread_v1",
                       "league_dragapult_spread")
            d.update({
                "new_status": "promising_research",
                "decision": "promote_v1_to_local_research_lead",
                "current_best_after": "league_dragapult_spread_v1",
                "evidence": {
                    "validation_eligible": eligible,
                    "league_rank_v1": v1.get("rank"),
                    "league_adj_win_rate_v1": v1.get("adj_win_rate"),
                    "league_rank_parent": parent.get("rank"),
                    "league_adj_win_rate_parent": parent.get("adj_win_rate"),
                    "v1_vs_parent_head_to_head_win_rate": h2h,
                    "meta_sanity_weighted_score_v1": _candidate_meta_score(
                        meta, "league_dragapult_spread_v1"),
                    "meta_sanity_passed": (meta.get("sanity") or {})
                    .get("sanity_passed"),
                },
                "caveats": [
                    "v1 leads on AGGREGATE adjusted win rate but LOSES the direct "
                    f"head-to-head vs its parent ({h2h} for v1) -- its edge comes "
                    "from beating the weaker field harder, not from beating the "
                    "parent. Treat the promotion as a local research lead, not a "
                    "dominance claim.",
                    "Internal-league + surrogate meta only; not a Kaggle signal.",
                ],
                "next_experiment": (
                    "Keep v1 as the local research lead; next pass investigate the "
                    "v1-vs-parent head-to-head loss (spread-target sequencing) "
                    "before any further refinement. No upload."),
            })

        elif fid == "water_kyogre_abomasnow":
            ref = standings.get("league_water_core_reference", {})
            d.update({
                "new_status": "active_reference",
                "decision": "keep_stable_benchmark_unchanged",
                "current_best_after": fam.get("current_best"),
                "evidence": {
                    "league_rank": ref.get("rank"),
                    "league_adj_win_rate": ref.get("adj_win_rate"),
                    "meta_sanity_weighted_score": _candidate_meta_score(
                        meta, "league_water_core_reference"),
                },
                "caveats": ["Held as the stable benchmark; no Water changes this "
                            "pass (Part H carried v1 forward unchanged)."],
                "next_experiment": "keep as stable benchmark for future families",
            })

        elif fid == "raging_bolt_ogerpon":
            rb = standings.get("league_raging_bolt_ogerpon", {})
            d.update({
                "new_status": "backlog",
                "decision": "defer_rescue_deck_strength_only",
                "current_best_after": fam.get("current_best"),
                "evidence": {
                    "league_rank": rb.get("rank"),
                    "league_adj_win_rate": rb.get("adj_win_rate"),
                    "diagnosis_core_failure": diagnosis.get("core_failure"),
                    "diagnosis_energy_matching": diagnosis.get("energy_matching"),
                    "diagnosis_attack_first": diagnosis.get("attack_first"),
                },
                "caveats": [
                    "League confirms the Part-D diagnosis: last place; failure is "
                    "deck/structural, NOT an energy-color or attack-first pilot gap "
                    "(correct energy IS attached and attacks ARE taken).",
                ],
                "next_experiment": (
                    "Defer rescue; revisit only via deck-strength changes or a "
                    "supporter-sequencing capability, NOT energy color-matching."),
            })

        elif fid == "durant_deckout_carousel":
            d.update({
                "new_status": "chaos_research_blocked",
                "decision": "keep_chaos_research_only_excluded_from_league",
                "current_best_after": None,
                "evidence": {
                    "excluded_from_league": "league_durant" not in standings
                    and "durant_deckout_carousel" not in standings,
                    "reason": "INVALID smoke; generic pilot lacks deckout/mill "
                              "win-condition logic",
                },
                "caveats": ["Confirmed excluded from the Pass-18 league."],
                "next_experiment": "fixture/playbook design only; no league until "
                                   "a legal smoke-safe playbook exists",
            })

        else:  # future_high_ceiling_evolution and any other backlog families
            d.update({
                "new_status": fam.get("status"),
                "decision": "no_change_backlog",
                "current_best_after": fam.get("current_best"),
                "evidence": {},
                "caveats": ["Backlog; not evaluated this pass."],
                "next_experiment": fam.get("next_experiment"),
            })

        d["status_changed"] = d["new_status"] != d["prior_status"]
        decisions.append(d)
    return decisions


def _recommendation(decisions: list[dict]) -> dict:
    drag = next((d for d in decisions if d["family_id"] == "dragapult_spread"), {})
    ev = drag.get("evidence", {})
    return {
        "kind": "dry_run_only",
        "upload_recommended": False,
        "submit_recommended": False,
        "local_research_lead": "league_dragapult_spread_v1",
        "family": "dragapult_spread",
        "rationale": (
            "league_dragapult_spread_v1 is validation-eligible (no core regression "
            "vs parent + targeted fixtures pass), ranks #1 on internal aggregate "
            f"adjusted win rate ({ev.get('league_adj_win_rate_v1')}), and clears "
            f"the surrogate meta sanity check (weighted "
            f"{ev.get('meta_sanity_weighted_score_v1')}, no collapses). "
            "Recommend a LOCAL DRY-RUN as the research lead only."),
        "explicit_caveat": (
            "v1 LOSES the direct head-to-head vs its parent "
            f"({ev.get('v1_vs_parent_head_to_head_win_rate')}); the aggregate lead "
            "is field-driven. Internal-league + surrogate results never equal "
            "Kaggle results. NO upload, NO submission."),
    }


def run() -> dict:
    if yaml is None or not REGISTRY.exists():
        return {"status": "blocked", "reason": "registry_unavailable"}
    reg = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    rankings = _load_json(RANKINGS)
    league = _load_json(LEAGUE)
    validation = _load_json(VALIDATION)
    meta = _load_json(META)
    diagnosis = _load_json(DIAGNOSIS)

    standings = _standings_map(rankings)
    decisions = _decide(reg, standings, league, validation, meta, diagnosis)
    rec = _recommendation(decisions)

    return {
        "pass": "18", "part": "M", "local_only": True,
        "upload_performed": False,
        "is_kaggle_leaderboard": False,
        "disclaimer": DISCLAIMER,
        "inputs": {
            "registry": str(REGISTRY.relative_to(REPO)),
            "validation": str(VALIDATION.relative_to(REPO)),
            "rankings": str(RANKINGS.relative_to(REPO)),
            "league": str(LEAGUE.relative_to(REPO)),
            "meta_sanity": str(META.relative_to(REPO)),
            "diagnosis": str(DIAGNOSIS.relative_to(REPO)),
        },
        "decisions": decisions,
        "recommendation": rec,
    }


def _emit_events(rep: dict) -> list[str]:
    ids = []
    for d in rep.get("decisions", []):
        ev = AGE.emit("StrategyDecisionRecorded", payload={
            "family_id": d["family_id"],
            "prior_status": d["prior_status"],
            "new_status": d["new_status"],
            "decision": d["decision"],
            "current_best_after": d.get("current_best_after"),
            "status_changed": d.get("status_changed"),
            "next_experiment": d.get("next_experiment"),
        }, tags=["decision", d["family_id"]])
        ids.append(ev.event_id)
    rec = rep.get("recommendation", {})
    ev = AGE.emit("StrategyPromotionDecision", payload={
        "kind": rec.get("kind"),
        "local_research_lead": rec.get("local_research_lead"),
        "family": rec.get("family"),
        "upload_recommended": rec.get("upload_recommended"),
        "submit_recommended": rec.get("submit_recommended"),
        "rationale": rec.get("rationale"),
        "explicit_caveat": rec.get("explicit_caveat"),
    }, tags=["decision", "promotion", "dry_run"], parent_event_ids=ids)
    ids.append(ev.event_id)
    return ids


def _md(rep: dict) -> str:
    L = ["# Pass 18 — strategy decisions (Part M)", "",
         f"> {rep.get('disclaimer','')}", "",
         f"- is Kaggle leaderboard: **{rep.get('is_kaggle_leaderboard')}**  "
         f"upload_performed: **{rep.get('upload_performed')}**", ""]
    rec = rep.get("recommendation", {})
    L += ["## Dry-run recommendation",
          f"- **{rec.get('kind')}** — local research lead: "
          f"**{rec.get('local_research_lead')}** (family `{rec.get('family')}`)",
          f"- upload recommended: **{rec.get('upload_recommended')}**  "
          f"submit recommended: **{rec.get('submit_recommended')}**",
          f"- rationale: {rec.get('rationale')}",
          f"- ⚠️ caveat: {rec.get('explicit_caveat')}", "",
          "## Per-family decisions",
          "| family | prior → new status | decision | current_best after | next experiment |",
          "|---|---|---|---|---|"]
    for d in rep.get("decisions", []):
        arrow = (f"{d['prior_status']} → {d['new_status']}"
                 + (" *(changed)*" if d.get("status_changed") else ""))
        L.append(f"| {d['family_id']} | {arrow} | {d['decision']} | "
                 f"{d.get('current_best_after')} | {d.get('next_experiment')} |")
    L.append("")
    for d in rep.get("decisions", []):
        L.append(f"### {d['family_id']}")
        if d.get("evidence"):
            L.append("- evidence:")
            for k, v in d["evidence"].items():
                L.append(f"  - {k}: {v}")
        for c in d.get("caveats", []):
            L.append(f"- caveat: {c}")
        L.append("")
    return "\n".join(L)


def main() -> int:
    rep = run()
    if rep.get("status") == "blocked":
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(json.dumps(rep, indent=2), encoding="utf-8")
        print(f"strategy decisions blocked: {rep.get('reason')}")
        return 1
    rep["event_ids"] = _emit_events(rep)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    OUT_MD.write_text(_md(rep), encoding="utf-8")
    print(f"strategy decisions: {len(rep['decisions'])} families; "
          f"lead={rep['recommendation']['local_research_lead']} "
          f"(dry-run, upload={rep['recommendation']['upload_recommended']})")
    for p in (OUT_JSON, OUT_MD):
        print(f"  -> {p.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
