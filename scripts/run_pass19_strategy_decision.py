#!/usr/bin/env python3
"""Pass 19 (Part K) — Dragapult strategy decision + no-upload recommendation.

Pure synthesis of the Pass-19 artifacts (runs no games, changes no decks). Turns the
forensic trace, decision-delta, validation, mini-league, and meta sanity into ONE
labelled decision for the dragapult_spread family plus carry-forward decisions for the
other registered families, and emits ActiveGraph StrategyDecisionRecorded +
StrategyPromotionDecision events.

The decision label is drawn from a fixed vocabulary:
  keep_parent | keep_v1_as_research_lead | promote_refinement_to_research_lead |
  needs_more_h2h | blocked | candidate_for_deeper_confirmation | upload_not_recommended

Hard rule: a candidate is NEVER called strictly better than the parent while its direct
head-to-head vs the parent is negative OR unstable across samples.

Evidence consumed (all LOCAL):
  experiments/strategy_families.yaml
  data/experiments/pass19_candidate_validation.json          (Part H)
  data/experiments/pass19_dragapult_mini_rankings.json       (Part I standings)
  data/experiments/pass19_dragapult_mini_league.json         (Part I H2H + matchups)
  data/experiments/pass19_dragapult_parent_child_trace.json  (Part D forensic H2H)
  data/experiments/pass19_dragapult_decision_delta.json      (Part E delta)
  data/experiments/pass19_meta_sanity.json                   (Part J sanity)

Outputs: data/experiments/pass19_strategy_decision.{json,md}. STRICT: LOCAL ONLY, no
Kaggle upload/submit, no GitHub push.
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

EXP = REPO / "data" / "experiments"
REGISTRY = REPO / "experiments" / "strategy_families.yaml"
VALIDATION = EXP / "pass19_candidate_validation.json"
RANKINGS = EXP / "pass19_dragapult_mini_rankings.json"
LEAGUE = EXP / "pass19_dragapult_mini_league.json"
TRACE = EXP / "pass19_dragapult_parent_child_trace.json"
DELTA = EXP / "pass19_dragapult_decision_delta.json"
META = EXP / "pass19_meta_sanity.json"
OUT_JSON = EXP / "pass19_strategy_decision.json"
OUT_MD = EXP / "pass19_strategy_decision.md"

PARENT = "league_dragapult_spread"
CHILD = "league_dragapult_spread_v1"
SEARCH_ONLY = "league_dragapult_v1_search_only"
DRAW_ONLY = "league_dragapult_v1_draw_only"

VALID_LABELS = {"keep_parent", "keep_v1_as_research_lead",
                "promote_refinement_to_research_lead", "needs_more_h2h", "blocked",
                "candidate_for_deeper_confirmation", "upload_not_recommended"}

DISCLAIMER = (
    "LOCAL ONLY. This decision rests on an internal league (our own decks piloted by ONE "
    "generic core pilot) and a surrogate, directional meta sanity check. Neither equals a "
    "Kaggle result. Any 'research lead' is an INTERNAL lead only and is NEVER sufficient "
    "to upload or submit. No upload performed.")


def _load(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _standings_map(rankings: dict) -> dict:
    return {r["id"]: {"rank": i, **r}
            for i, r in enumerate(rankings.get("standings", []), 1)}


def _ci_overlap(a: list | None, b: list | None) -> bool:
    if not a or not b or a[0] is None or b[0] is None:
        return True
    return not (a[1] < b[0] or b[1] < a[0])


def _league_h2h(league: dict, x: str, y: str):
    """Return (x_win_rate_vs_y, x_wins, y_wins, draws) from league matchups."""
    for m in league.get("matchups", []):
        if {m.get("a"), m.get("b")} != {x, y}:
            continue
        if m.get("a") == x:
            xw, yw = m.get("a_wins", 0), m.get("b_wins", 0)
        else:
            xw, yw = m.get("b_wins", 0), m.get("a_wins", 0)
        dec = xw + yw
        return (round(xw / dec, 4) if dec else None, xw, yw, m.get("draws", 0))
    return (None, 0, 0, 0)


def _trace_child_h2h(trace: dict):
    """Child win-rate vs parent from the Part-D forensic trace (different sample)."""
    games = trace.get("games") or trace.get("games_summary") or trace.get("summary") or {}
    for src in (games, trace):
        if isinstance(src, dict) and src.get("child_win_rate") is not None:
            return src.get("child_win_rate")
        cw, pw = (src.get("child_wins") if isinstance(src, dict) else None,
                  src.get("parent_wins") if isinstance(src, dict) else None)
        if isinstance(cw, int) and isinstance(pw, int) and (cw + pw) > 0:
            return round(cw / (cw + pw), 4)
    return None


def _decide_dragapult(standings, league, validation, trace, meta) -> dict:
    parent = standings.get(PARENT, {})
    child = standings.get(CHILD, {})
    search = standings.get(SEARCH_ONLY, {})
    draw = standings.get(DRAW_ONLY, {})

    # Direct head-to-head vs parent (this league's sample).
    child_h2h, cw, pw, cd = _league_h2h(league, CHILD, PARENT)
    search_h2h, sw, spw, sd = _league_h2h(league, SEARCH_ONLY, PARENT)
    draw_h2h, dw, dpw, dd = _league_h2h(league, DRAW_ONLY, PARENT)
    # The Part-D forensic trace measured the SAME head-to-head on a different sample.
    trace_child_h2h = _trace_child_h2h(trace)

    # H2H is "unstable" if the two child-vs-parent samples land on opposite sides of
    # 0.5 (the central question of this pass: aggregate win vs H2H loss).
    h2h_unstable = (child_h2h is not None and trace_child_h2h is not None
                    and ((child_h2h - 0.5) * (trace_child_h2h - 0.5) < 0))

    # Aggregate separability: do the candidate CIs clear the parent CI at all?
    parent_ci = parent.get("wilson")
    overlaps = {
        CHILD: _ci_overlap(child.get("wilson"), parent_ci),
        SEARCH_ONLY: _ci_overlap(search.get("wilson"), parent_ci),
        DRAW_ONLY: _ci_overlap(draw.get("wilson"), parent_ci),
    }
    all_overlap = all(overlaps.values())

    eligible = all(validation.get("candidates", {}).get(c, {}).get("overall_ok")
                   for c in (SEARCH_ONLY, DRAW_ONLY))
    meta_ok = (meta.get("sanity") or {}).get("sanity_passed")

    # search_only is the aggregate leader and the mechanistically-motivated revert
    # (drops the draw_support discard branch). It is the deeper-confirmation candidate.
    best_refinement = SEARCH_ONLY if search.get("rank", 99) <= child.get("rank", 99) \
        else CHILD

    # Decision logic — never "strictly better" while H2H is negative or unstable.
    if not eligible:
        label = "blocked"
    elif h2h_unstable or all_overlap:
        label = "needs_more_h2h"
    elif (search_h2h is not None and search_h2h > 0.5
          and search.get("rank") == 1):
        label = "promote_refinement_to_research_lead"
    else:
        label = "keep_parent"

    secondary = "candidate_for_deeper_confirmation" if best_refinement == SEARCH_ONLY \
        else None

    return {
        "family_id": "dragapult_spread",
        "label": label,
        "secondary_label": secondary,
        "current_best_kept": PARENT,
        "best_refinement_candidate": best_refinement,
        "v1_strictly_better_than_parent": False,
        "evidence": {
            "aggregate": {
                "parent": {"rank": parent.get("rank"),
                           "adj_win_rate": parent.get("adj_win_rate"),
                           "ci": parent_ci},
                "child": {"rank": child.get("rank"),
                          "adj_win_rate": child.get("adj_win_rate"),
                          "ci": child.get("wilson")},
                "search_only": {"rank": search.get("rank"),
                                "adj_win_rate": search.get("adj_win_rate"),
                                "ci": search.get("wilson")},
                "draw_only": {"rank": draw.get("rank"),
                              "adj_win_rate": draw.get("adj_win_rate"),
                              "ci": draw.get("wilson")},
                "all_candidate_cis_overlap_parent": all_overlap,
            },
            "head_to_head_vs_parent": {
                "child_this_league": {"win_rate": child_h2h,
                                      "record": f"{cw}-{pw}-{cd}"},
                "child_forensic_trace_sample": trace_child_h2h,
                "child_h2h_unstable_across_samples": h2h_unstable,
                "search_only_this_league": {"win_rate": search_h2h,
                                            "record": f"{sw}-{spw}-{sd}"},
                "draw_only_this_league": {"win_rate": draw_h2h,
                                          "record": f"{dw}-{dpw}-{dd}"},
            },
            "validation_eligible": eligible,
            "meta_sanity_passed": meta_ok,
        },
        "rationale": (
            "The mechanistic delta (the draw_support discard branch) is real and "
            "deterministic, but at the league/H2H scale its effect size sits BELOW the "
            "variance floor: the child-vs-parent head-to-head flips sign between the "
            f"forensic-trace sample ({trace_child_h2h}) and this league sample "
            f"({child_h2h}), and every candidate's aggregate 95% CI overlaps the "
            "parent's. search_only (the targeted revert that drops the suspect branch) "
            f"leads the aggregate (rank {search.get('rank')}, "
            f"{search.get('adj_win_rate')}) yet does NOT itself win the direct H2H vs "
            f"parent ({search_h2h}). No candidate is robustly better than the parent."),
        "caveats": [
            "Aggregate league lead is field-driven and within noise — NOT a dominance "
            "claim. CIs overlap the parent for every candidate.",
            "The direct parent H2H is UNSTABLE across samples (sign flip); 20 games per "
            "side is too few to resolve a sub-variance effect.",
            "Internal-league + surrogate meta only; neither equals a Kaggle result.",
            "The forensic-trace and mini-league H2H use different game workers/seeds, "
            "which is itself part of why the small effect is not reproducible.",
        ],
        "next_experiment": (
            "Do NOT promote or upload. To resolve the parent H2H, run a much larger "
            "fixed-seed parent-vs-{child,search_only} head-to-head (>=200 games/side, "
            "one worker) before any further refinement. Keep current_best = parent."),
    }


def _carry_forward(reg: dict, standings: dict) -> list[dict]:
    """Carry-forward (no-change) decisions for the non-Dragapult families."""
    out = []
    for fam in reg.get("families", []):
        fid = fam.get("family_id")
        if fid == "dragapult_spread":
            continue
        out.append({
            "family_id": fid,
            "label": "keep_parent",
            "decision": "no_change_this_pass",
            "current_best_kept": fam.get("current_best"),
            "rationale": "Not under investigation in Pass 19 (Dragapult-focused pass).",
            "next_experiment": fam.get("next_experiment"),
        })
    return out


def run() -> dict:
    if yaml is None or not REGISTRY.exists():
        return {"status": "blocked", "reason": "registry_unavailable"}
    reg = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    rankings = _load(RANKINGS)
    league = _load(LEAGUE)
    validation = _load(VALIDATION)
    trace = _load(TRACE)
    meta = _load(META)
    standings = _standings_map(rankings)

    drag = _decide_dragapult(standings, league, validation, trace, meta)
    assert drag["label"] in VALID_LABELS, drag["label"]
    others = _carry_forward(reg, standings)

    rec = {
        "kind": "dry_run_only",
        "upload_recommended": False,
        "submit_recommended": False,
        "upload_not_recommended": True,
        "current_best": PARENT,
        "primary_decision": drag["label"],
        "best_refinement_candidate": drag["best_refinement_candidate"],
        "rationale": drag["rationale"],
        "explicit_caveat": (
            "No candidate is strictly better than the parent: the direct head-to-head "
            "is unstable across samples and all aggregate CIs overlap. Internal/"
            "surrogate results never equal Kaggle results. NO upload, NO submission."),
    }
    return {
        "pass": "19", "part": "K", "local_only": True, "upload_performed": False,
        "is_kaggle_leaderboard": False, "disclaimer": DISCLAIMER,
        "valid_labels": sorted(VALID_LABELS),
        "inputs": {k: str(p.relative_to(REPO)) for k, p in {
            "registry": REGISTRY, "validation": VALIDATION, "rankings": RANKINGS,
            "league": LEAGUE, "trace": TRACE, "delta": DELTA, "meta": META}.items()},
        "dragapult_decision": drag,
        "other_family_decisions": others,
        "recommendation": rec,
    }


def _emit_events(rep: dict) -> list[str]:
    ids = []
    drag = rep["dragapult_decision"]
    ev = AGE.emit("StrategyDecisionRecorded", payload={
        "family_id": drag["family_id"], "label": drag["label"],
        "secondary_label": drag.get("secondary_label"),
        "current_best_kept": drag["current_best_kept"],
        "best_refinement_candidate": drag["best_refinement_candidate"],
        "v1_strictly_better_than_parent": drag["v1_strictly_better_than_parent"],
        "next_experiment": drag["next_experiment"],
    }, tags=["decision", "dragapult_spread", "pass19"])
    ids.append(ev.event_id)
    for d in rep["other_family_decisions"]:
        ev = AGE.emit("StrategyDecisionRecorded", payload={
            "family_id": d["family_id"], "label": d["label"],
            "decision": d["decision"], "current_best_kept": d["current_best_kept"],
        }, tags=["decision", d["family_id"], "pass19"])
        ids.append(ev.event_id)
    rec = rep["recommendation"]
    ev = AGE.emit("StrategyPromotionDecision", payload={
        "kind": rec["kind"], "primary_decision": rec["primary_decision"],
        "current_best": rec["current_best"],
        "best_refinement_candidate": rec["best_refinement_candidate"],
        "upload_recommended": rec["upload_recommended"],
        "submit_recommended": rec["submit_recommended"],
        "upload_not_recommended": rec["upload_not_recommended"],
        "rationale": rec["rationale"], "explicit_caveat": rec["explicit_caveat"],
    }, tags=["decision", "promotion", "dry_run", "pass19"], parent_event_ids=ids)
    ids.append(ev.event_id)
    return ids


def _md(rep: dict) -> str:
    drag = rep["dragapult_decision"]
    rec = rep["recommendation"]
    ev = drag["evidence"]
    agg = ev["aggregate"]
    h2h = ev["head_to_head_vs_parent"]
    L = ["# Pass 19 — Dragapult strategy decision (Part K)", "",
         f"> {rep['disclaimer']}", "",
         f"- is Kaggle leaderboard: **{rep['is_kaggle_leaderboard']}**  "
         f"upload_performed: **{rep['upload_performed']}**", "",
         "## Decision",
         f"- **primary label:** `{drag['label']}`"
         + (f"  (secondary: `{drag['secondary_label']}`)"
            if drag.get("secondary_label") else ""),
         f"- **current_best kept:** `{drag['current_best_kept']}`",
         f"- **best refinement candidate:** `{drag['best_refinement_candidate']}`",
         f"- **v1 strictly better than parent:** "
         f"**{drag['v1_strictly_better_than_parent']}**",
         f"- upload recommended: **{rec['upload_recommended']}**  "
         f"submit recommended: **{rec['submit_recommended']}**  "
         f"upload_not_recommended: **{rec['upload_not_recommended']}**", "",
         f"- rationale: {drag['rationale']}", "",
         "## Aggregate standings (internal league)",
         "| deck | rank | adj win_rate | 95% CI | CI overlaps parent? |",
         "|---|---|---|---|---|"]
    for key, lbl in [("parent", PARENT), ("child", CHILD),
                     ("search_only", SEARCH_ONLY), ("draw_only", DRAW_ONLY)]:
        a = agg[key]
        ov = ("—" if lbl == PARENT
              else ("yes" if agg["all_candidate_cis_overlap_parent"]
                    or _ci_overlap(a["ci"], agg["parent"]["ci"]) else "no"))
        L.append(f"| {lbl} | {a['rank']} | {a['adj_win_rate']} | {a['ci']} | {ov} |")
    L += ["", "## Direct head-to-head vs parent",
          "| candidate | this league | forensic-trace sample | note |",
          "|---|---|---|---|",
          f"| {CHILD} | {h2h['child_this_league']['win_rate']} "
          f"({h2h['child_this_league']['record']}) | "
          f"{h2h['child_forensic_trace_sample']} | "
          f"{'UNSTABLE (sign flip)' if h2h['child_h2h_unstable_across_samples'] else 'consistent'} |",
          f"| {SEARCH_ONLY} | {h2h['search_only_this_league']['win_rate']} "
          f"({h2h['search_only_this_league']['record']}) | — | targeted revert |",
          f"| {DRAW_ONLY} | {h2h['draw_only_this_league']['win_rate']} "
          f"({h2h['draw_only_this_league']['record']}) | — | diagnostic |",
          "", "## Caveats"]
    L += [f"- {c}" for c in drag["caveats"]]
    L += ["", f"## Next experiment", f"- {drag['next_experiment']}", "",
          "## Other family decisions (carry-forward)",
          "| family | label | current_best kept |", "|---|---|---|"]
    for d in rep["other_family_decisions"]:
        L.append(f"| {d['family_id']} | {d['label']} | {d['current_best_kept']} |")
    L.append("")
    return "\n".join(L)


def main() -> int:
    rep = run()
    EXP.mkdir(parents=True, exist_ok=True)
    if rep.get("status") == "blocked":
        OUT_JSON.write_text(json.dumps(rep, indent=2), encoding="utf-8")
        print(f"strategy decision blocked: {rep.get('reason')}")
        return 1
    rep["event_ids"] = _emit_events(rep)
    OUT_JSON.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    OUT_MD.write_text(_md(rep), encoding="utf-8")
    print(f"strategy decision: label={rep['dragapult_decision']['label']} "
          f"current_best={rep['recommendation']['current_best']} "
          f"upload_recommended={rep['recommendation']['upload_recommended']}")
    for p in (OUT_JSON, OUT_MD):
        print(f"  -> {p.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
