#!/usr/bin/env python3
"""PASS 46G (Part I) — selection / strategy decision.

Reads every upstream 46G artifact and derives ONE honest decision from explicit
gates. NO games, NO mutation, NO upload, NO events, NO promotion. LOCAL / READ-ONLY.

Gate order (first failure wins):
  1. safety_stop_required               — preflight not all_ok / stop_required.
  2. validation_failed                  — validation / smoke / eval integrity gate failed.
  3. turnplanner_profile_promising_local_only
        — a candidate BOTH (a) beats its internal parent at 95% (wilson_low>0.5)
          AND (b) that edge is ATTRIBUTABLE to the phase/role profile (the profile
          is distinguishable from the family-only floor in gameplay).
  4. no_profile_promising_continue_iteration
        — otherwise (the default honest outcome when the phase/role layer collapses
          to the family-only floor, even if a family-weighted TRANSFER signal exists).

HONESTY: win/loss is relative feasibility context, NOT a Kaggle score. Phase/role are
observable heuristic labels — no exact-damage / lethal / KO / Boss-gust / spread /
best-action claim. A parent edge that is indistinguishable from the family-only floor
is reported as a FAMILY-WEIGHTED TRANSFER signal, never a phase/role success.

Outputs: data/experiments/pass46g_strategy_decision.{json,md}
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"


def _load(name: str) -> dict:
    p = EXP / name
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def main() -> int:
    safety = _load("pass46g_safety_preflight.json")
    source = _load("pass46g_source_selection.json")
    catalog = _load("pass46g_profile_catalog.json")
    calib = _load("pass46g_profile_calibration.json")
    build = _load("pass46g_candidate_build.json")
    valid = _load("pass46g_candidate_validation.json")
    smoke = _load("pass46g_smoke_non_inertness.json")
    evalp = _load("pass46g_eval_panel.json")
    f46 = _load("pass46f_candidate_smoke.json")

    # ---- gates ----
    safety_ok = bool(safety.get("all_ok")) and not safety.get("stop_required", False)
    validation_ok = bool(valid.get("all_ok"))
    smoke_ok = bool(smoke.get("all_ok"))
    eval_integrity_ok = (evalp.get("games_error", 1) == 0
                         and evalp.get("games_timeout", 1) == 0
                         and bool(evalp.get("root_main_deck_unchanged"))
                         and bool((evalp.get("references_not_in_pool") or {})
                                  .get("clean")))

    # parent-H2H edge candidates (statistically confident).
    edge = list(evalp.get("parent_h2h_edge_candidates_95") or [])
    indistinct = evalp.get("phase_vs_role_indistinct_in_gameplay") or {}
    # internal top-1 distinguishability from the family-only floor (Part G).
    internal = smoke.get("internal_distinguishability") or {}

    cands_by_id = {c["candidate_id"]: c for c in build.get("candidates", [])}

    def profile_attributable(cid: str) -> bool:
        """An edge is attributable to the profile ONLY if the profile's menu is
        distinguishable from the FAMILY-ONLY floor (in gameplay if measured,
        else by the Part-G per-profile-vs-family-only top-1 divergence). The
        family-level phase-vs-role flag is deliberately NOT used here: a role
        profile can sit exactly on the family-only floor while phase moves the
        menu, so phase-vs-role separation alone must never make a role edge look
        profile-attributable."""
        if cid in indistinct:           # measured in gameplay → must NOT be indistinct
            return not indistinct[cid]
        fam = (cands_by_id.get(cid) or {}).get("parent_family")
        return bool((internal.get(fam) or {}).get("each_vs_family_only_distinguishable"))

    promising = [c for c in edge if profile_attributable(c)]

    if not safety_ok:
        decision = "safety_stop_required"
    elif not (validation_ok and smoke_ok and eval_integrity_ok):
        decision = "validation_failed"
    elif promising:
        decision = "turnplanner_profile_promising_local_only"
    else:
        decision = "no_profile_promising_continue_iteration"

    # ---- evidence digest (parent-H2H + intra-family + refs) ----
    pairings = evalp.get("pairings", [])
    parent_rows = [p for p in pairings if p["kind"] == "parent_h2h"]
    intra_rows = [p for p in pairings if p["kind"] == "intra_family_phase_vs_role"]
    ref_rows = [p for p in pairings if p["kind"] == "reference_context"]

    best_parent = max(parent_rows, key=lambda r: (r.get("win_rate_decisive") or 0,
                                                  r["wins"]), default=None)
    # 46F parent-H2H baseline (for "clearer parent edge than 46F?").
    f46_parent = next((o for o in (f46.get("per_opponent") or [])
                       if o.get("kind") == "parent"), None)
    f46_parent_wl = (f"{f46_parent['cand_wins']}/{f46_parent['cand_losses']}"
                     if f46_parent else "n/a")

    # ---- honest narrative flags ----
    family_weighted_transfer_signal = bool(
        best_parent and (best_parent.get("win_rate_decisive") or 0) >= 0.7
        and not best_parent.get("beats_opp_95"))
    # The phase/role layer is top-1-inert iff NO family separates either profile
    # from the family-only floor (each_vs_family_only) — the layer adds
    # interpretability vocabulary but no separable signal at the decision.
    phase_layer_inert = all(
        not (internal.get(fam) or {}).get("each_vs_family_only_distinguishable", False)
        for fam in internal) if internal else True

    safety_invariants = {
        "all_5_workflows_not_started_expected": True,
        "production_mutated": bool(safety.get("production_mutated"))
        or bool(evalp.get("production_mutated")),
        "tick_executed": bool(safety.get("tick_executed")),
        "registration_performed": bool(safety.get("registration_performed")),
        "promotion_performed": bool(safety.get("promotion_performed")),
        "no_upload": bool(safety.get("no_upload", True))
        and bool(evalp.get("no_upload", True)),
        "root_main_deck_unchanged": bool(evalp.get("root_main_deck_unchanged")),
        "references_benchmark_only_not_pooled":
            bool((evalp.get("references_not_in_pool") or {}).get("clean")),
        "no_public_ref_as_source_parent_candidate":
            bool(source.get("reference_ids_excluded") is not None),
    }
    safety_invariants_ok = (safety_invariants["all_5_workflows_not_started_expected"]
                            and not safety_invariants["production_mutated"]
                            and not safety_invariants["tick_executed"]
                            and not safety_invariants["registration_performed"]
                            and not safety_invariants["promotion_performed"]
                            and safety_invariants["no_upload"]
                            and safety_invariants["root_main_deck_unchanged"]
                            and safety_invariants["references_benchmark_only_not_pooled"])

    next_iteration_levers = [
        "Replace the additive phase×family / role-target layer with WITHIN-FAMILY "
        "per-option value features (which specific attach/search/play is stronger) — "
        "the cross-family phase layer is structurally top-1-inert on real menus.",
        "Confirm the diamond family-weighted TRANSFER signal (cg_typed turn-scorer "
        "vs diamond parent) at larger N (e.g. >=40 decisive games / seat-balanced) "
        "before treating it as real — current Wilson_low just misses 0.5.",
        "Consider the cut Lightning / Dragapult families and a from-scratch value "
        "head rather than seeding from 46F robust medians.",
    ]

    out = {
        "pass": "46g", "part": "I", "local_only": True, "read_only": True,
        "no_upload": True, "production_mutated": False, "no_promotion": True,
        "decision": decision,
        "gates": {"safety_ok": safety_ok, "validation_ok": validation_ok,
                  "smoke_ok": smoke_ok, "eval_integrity_ok": eval_integrity_ok,
                  "profile_promising": bool(promising)},
        "parent_h2h_edge_candidates_95": edge,
        "profile_attributable_edge_candidates": promising,
        "best_parent_h2h": ({
            "subject": best_parent["subject"], "opponent": best_parent["opp_id"],
            "w_l_d": f"{best_parent['wins']}/{best_parent['losses']}/"
                     f"{best_parent['draws']}",
            "win_rate_decisive": best_parent.get("win_rate_decisive"),
            "wilson95": [best_parent.get("wilson_low"), best_parent.get("wilson_high")],
            "beats_parent_95": best_parent.get("beats_opp_95")} if best_parent
            else None),
        "f46_parent_h2h_w_l": f46_parent_wl,
        "clearer_point_estimate_than_46f": bool(
            best_parent and f46_parent
            and (best_parent.get("win_rate_decisive") or 0) > (
                f46_parent["cand_wins"]
                / max(1, f46_parent["cand_wins"] + f46_parent["cand_losses"]))),
        "family_weighted_transfer_signal": family_weighted_transfer_signal,
        "phase_role_layer_inert_top1": phase_layer_inert,
        "intra_family_phase_vs_role": [
            {"subject": r["subject"], "opponent": r["opp_id"],
             "w_l_d": f"{r['wins']}/{r['losses']}/{r['draws']}",
             "wilson95": [r.get("wilson_low"), r.get("wilson_high")],
             "indistinct_spans_0.5": (not r.get("beats_opp_95")
                                      and not r.get("loses_to_opp_95"))}
            for r in intra_rows],
        "reference_context": [
            {"subject": r["subject"], "opponent": r["opp_id"],
             "w_l_d": f"{r['wins']}/{r['losses']}/{r['draws']}",
             "loses_to_ref_95": r.get("loses_to_opp_95")} for r in ref_rows],
        "safety_invariants": safety_invariants,
        "safety_invariants_ok": safety_invariants_ok,
        "next_iteration_levers": next_iteration_levers,
        "note": ("Win/loss is RELATIVE feasibility context, NOT a Kaggle score. The "
                 "role profile == the family-only floor at top-1, so an indistinct "
                 "intra-family phase-vs-role result means any parent edge is a "
                 "FAMILY-WEIGHTED TRANSFER signal, NOT a phase/role success. Phase/"
                 "role are observable heuristic labels — no exact-damage / lethal / "
                 "KO / Boss-gust / spread / best-action claim."),
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46g_strategy_decision.json").write_text(
        json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")

    bp = out["best_parent_h2h"]
    md = [
        "# Pass 46G (Part I) — strategy decision", "",
        f"## Decision: **{decision}**", "",
        "_LOCAL / READ-ONLY. Win/loss is relative feasibility context, NOT a Kaggle "
        "score. Phase/role are observable heuristic labels — no exact-damage / lethal "
        "/ KO / Boss-gust / spread / best-action claim._", "",
        "### Gates",
        f"- safety_ok: **{safety_ok}** · validation_ok: **{validation_ok}** · "
        f"smoke_ok: **{smoke_ok}** · eval_integrity_ok: **{eval_integrity_ok}**",
        f"- profile_promising (parent-edge AND attributable to profile): "
        f"**{bool(promising)}** {promising or ''}", "",
        "### Parent-H2H (key comparison)",
        f"- best: **{bp['subject']}** vs `{bp['opponent']}` → {bp['w_l_d']} "
        f"(win% {bp['win_rate_decisive']:.0%}), Wilson95 "
        f"[{bp['wilson95'][0]:.2f}, {bp['wilson95'][1]:.2f}], beats_parent_95="
        f"**{bp['beats_parent_95']}**" if bp else "- (no parent-H2H rows)",
        f"- 46F parent-H2H baseline (W/L): `{f46_parent_wl}` · clearer point "
        f"estimate than 46F: **{out['clearer_point_estimate_than_46f']}**",
        f"- family-weighted TRANSFER signal (high point estimate, not 95%-confident): "
        f"**{family_weighted_transfer_signal}**",
        f"- phase/role layer top-1-inert vs family-only floor: **{phase_layer_inert}**",
        "", "### Intra-family phase vs role (== family-only floor)"]
    for r in out["intra_family_phase_vs_role"]:
        md.append(f"- `{r['subject']}` vs `{r['opponent']}`: {r['w_l_d']}, Wilson95 "
                  f"[{r['wilson95'][0]:.2f}, {r['wilson95'][1]:.2f}], "
                  f"indistinct(spans 0.5)=**{r['indistinct_spans_0.5']}**")
    md += ["", "### Reference context (benchmark-only)"]
    for r in out["reference_context"]:
        md.append(f"- `{r['subject']}` vs `{r['opponent']}`: {r['w_l_d']} "
                  f"(loses_to_ref_95={r['loses_to_ref_95']})")
    md += ["", "### Safety invariants",
           f"- ok: **{safety_invariants_ok}** · all 5 workflows not-started "
           "(EXPECTED) · no prod mutation/tick/registration/promotion/upload · root "
           "main.py/deck.csv unchanged · references benchmark-only (not pooled)", "",
           "### Next-iteration levers"]
    md += [f"- {lv}" for lv in next_iteration_levers]
    md.append("")
    (EXP / "pass46g_strategy_decision.md").write_text("\n".join(md) + "\n",
                                                      encoding="utf-8")

    print(json.dumps({"decision": decision, "gates": out["gates"],
                      "parent_edge_95": edge,
                      "family_weighted_transfer_signal":
                      family_weighted_transfer_signal,
                      "clearer_than_46f": out["clearer_point_estimate_than_46f"],
                      "safety_invariants_ok": safety_invariants_ok}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
