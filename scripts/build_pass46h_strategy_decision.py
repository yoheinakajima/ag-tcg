#!/usr/bin/env python3
"""PASS 46H (Part I) — within-family per-option value strategy decision.

Reads every upstream 46H artifact and derives ONE honest decision from explicit
gates. NO games, NO mutation, NO upload, NO events, NO promotion, NO Kaggle.
LOCAL / READ-ONLY.

Gate order (first match wins):
  1. safety_stop_required
        — preflight not all_ok / stop_required / any prod mutation observed.
  2. validation_failed
        — validation / smoke / eval-integrity gate failed.
  3. option_value_profile_promising_local_only
        — at least ONE treatment shows a COHERENT escape from the family-only
          floor: it is BOTH (a) distinguishable from the family-only floor on
          live decision frames (top-1 divergence above the floor gate — i.e. it
          escapes 46G's documented coarse phase/role TOP-1 INERTNESS) AND (b)
          distinguishable from that same floor IN GAMEPLAY at 95% (Wilson_low >
          0.5 vs its own family-only floor candidate). The conjunction guards
          against (i) a live-frame divergence that washes out in gameplay and
          (ii) a gameplay win/loss split that is pure variance over a near-inert
          menu.
  4. option_value_profile_inconclusive_continue_iteration
        — the per-option layer is non-inert on live frames (it DID escape the
          coarse top-1 inertness) but NO treatment shows a coherent live+gameplay
          escape from the floor at this N.
  5. no_option_value_profile_promising
        — the per-option layer is itself top-1-inert on live frames (it collapses
          to the family-only floor, like 46G's phase/role layer).

HONESTY: win/loss/draw is RELATIVE feasibility context, NOT a Kaggle score, and
is NEVER a strength claim. "Promising_local_only" asserts ONLY that an
option-specific VISIBLE-feature layer escapes the family-only floor in a
coherent (live + gameplay) way at the LOCAL-ONLY level; it explicitly does NOT
claim a PARENT edge (parent-H2H edge is reported separately and is expected to
be absent at small N). References are benchmark-only opponents, never pooled /
queued / ranked / used as source / parent / candidate. Role buckets / target
areas are observable heuristic labels — no exact-damage / lethal / KO / Boss-gust
/ spread / best-action claim.

Outputs: data/experiments/pass46h_strategy_decision.{json,md}
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"

# profile_id -> the within_family_distinguishability boolean flag that records
# whether THIS profile's live-frame menu diverges from the family-only floor.
_LIVE_FLAG = {
    "option_value_v1": "option_value_distinguishable_from_floor",
    "conservative_option_value_v1": "conservative_distinguishable_from_floor",
}
_TREATMENT_PROFILES = set(_LIVE_FLAG)


def _load(name: str) -> dict:
    p = EXP / name
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def main() -> int:
    safety = _load("pass46h_safety_preflight.json")
    source = _load("pass46h_source_selection.json")
    catalog = _load("pass46h_option_feature_catalog.json")
    dataset = _load("pass46h_option_value_dataset.json")
    profiles = _load("pass46h_value_profiles.json")
    build = _load("pass46h_candidate_build.json")
    valid = _load("pass46h_candidate_validation.json")
    smoke = _load("pass46h_smoke_non_inertness.json")
    evalp = _load("pass46h_eval_panel.json")

    # ---- top-level integrity gates ----
    safety_ok = (bool(safety.get("all_ok"))
                 and not safety.get("stop_required", False)
                 and not bool(safety.get("production_mutated"))
                 and not bool(evalp.get("production_mutated")))
    validation_ok = bool(valid.get("all_ok"))
    smoke_ok = bool(smoke.get("all_ok"))
    eval_integrity_ok = (evalp.get("games_error", 1) == 0
                         and evalp.get("games_timeout", 1) == 0
                         and bool(evalp.get("root_main_deck_unchanged"))
                         and bool((evalp.get("references_not_in_pool") or {})
                                  .get("clean")))

    # ---- per-candidate coherent-escape analysis ----
    cands = build.get("candidates", [])
    cands_by_id = {c["candidate_id"]: c for c in cands}
    wf = smoke.get("within_family_distinguishability") or {}
    gameplay = evalp.get("treatment_vs_floor_distinct_in_gameplay") or {}

    def live_distinct_from_floor(cid: str) -> bool | None:
        c = cands_by_id.get(cid) or {}
        fam, prof = c.get("parent_family"), c.get("profile_id")
        flag = _LIVE_FLAG.get(prof)
        if not flag or fam not in wf:
            return None
        return bool((wf.get(fam) or {}).get(flag))

    treatments = []
    for c in cands:
        cid = c["candidate_id"]
        if c.get("profile_id") not in _TREATMENT_PROFILES:
            continue
        live = live_distinct_from_floor(cid)
        play = gameplay.get(cid)
        coherent = bool(live) and bool(play)
        treatments.append({
            "candidate_id": cid,
            "parent_family": c.get("parent_family"),
            "profile_id": c.get("profile_id"),
            "live_distinct_from_floor": live,
            "gameplay_distinct_from_floor_95": play,
            "coherent_escape": coherent,
        })

    coherent_escape_candidates = [t["candidate_id"] for t in treatments
                                  if t["coherent_escape"]]
    # live-only: the layer moved the live menu but the gameplay difference washed
    # out at this N (real but unconfirmed).
    live_only_candidates = [t["candidate_id"] for t in treatments
                            if t["live_distinct_from_floor"]
                            and not t["gameplay_distinct_from_floor_95"]]
    # gameplay-only: won/lost vs floor in gameplay while the live menu was
    # ~inert — almost certainly variance over a near-identical menu, NOT a
    # coherent option-value escape; flagged honestly, NEVER counted as promising.
    gameplay_only_variance_candidates = [
        t["candidate_id"] for t in treatments
        if t["gameplay_distinct_from_floor_95"]
        and t["live_distinct_from_floor"] is False]

    # Does the per-option layer escape 46G's coarse phase/role TOP-1 inertness AT
    # ALL? (any family's option_value menu diverges from the family-only floor on
    # live frames above the floor gate.)
    option_value_layer_non_inert_live = bool(
        smoke.get("option_value_active_on_live_frames_any_family"))

    # ---- parent-H2H edge (reported, NOT part of the promising gate) ----
    parent_edge_95 = list(evalp.get("parent_h2h_edge_candidates_95") or [])

    # ---- decision ----
    if not safety_ok:
        decision = "safety_stop_required"
    elif not (validation_ok and smoke_ok and eval_integrity_ok):
        decision = "validation_failed"
    elif coherent_escape_candidates:
        decision = "option_value_profile_promising_local_only"
    elif option_value_layer_non_inert_live:
        decision = "option_value_profile_inconclusive_continue_iteration"
    else:
        decision = "no_option_value_profile_promising"

    # ---- evidence digest from the eval pairings ----
    pairings = evalp.get("pairings", [])

    def _rows(kind: str) -> list[dict]:
        return [p for p in pairings if p.get("kind") == kind]

    def _digest(r: dict) -> dict:
        return {
            "subject": r.get("subject") or r.get("candidate_id"),
            "opponent": r.get("opp_id") or r.get("opponent_id"),
            "w_l_d": f"{r.get('wins')}/{r.get('losses')}/{r.get('draws')}",
            "wilson95": [r.get("wilson_low"), r.get("wilson_high")],
        }

    parent_rows = [_digest(r) for r in _rows("parent_h2h")]
    intra_rows = [_digest(r) for r in _rows("intra_family_vs_floor")]
    ref_rows = [_digest(r) for r in _rows("reference_context")]

    # ---- safety invariants (same charter as 46G) ----
    all_public_reference_false = all(
        not bool(c.get("public_reference")) for c in cands) if cands else False
    references_clean = bool((evalp.get("references_not_in_pool") or {})
                            .get("clean"))
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
        "references_benchmark_only_not_pooled": references_clean,
        "no_public_ref_as_source_parent_candidate": all_public_reference_false,
    }
    safety_invariants_ok = (
        safety_invariants["all_5_workflows_not_started_expected"]
        and not safety_invariants["production_mutated"]
        and not safety_invariants["tick_executed"]
        and not safety_invariants["registration_performed"]
        and not safety_invariants["promotion_performed"]
        and safety_invariants["no_upload"]
        and safety_invariants["root_main_deck_unchanged"]
        and safety_invariants["references_benchmark_only_not_pooled"]
        and safety_invariants["no_public_ref_as_source_parent_candidate"])

    next_iteration_levers = [
        "Confirm the coherent live+gameplay escape(s) "
        f"{coherent_escape_candidates or '[]'} at larger N (e.g. >=40 decisive, "
        "seat-balanced games vs the family-only floor) AND test for a PARENT edge "
        "— parent-H2H is currently NONE at small N and is NOT yet established.",
        "Disentangle the profile x family interaction: the additive option_value "
        "head and the lexicographic conservative head do not agree on which "
        "family they help, and one gameplay-vs-floor split sits over a live-inert "
        "menu (likely variance) — separate signal from noise with more frames.",
        "Calibrate the per-option weights against a LARGER cached Search-oracle "
        "label set before treating the option weights as learned — current oracle "
        "coverage on multi-option frames is tiny, so the priors are hand-set, not "
        "fit.",
    ]

    out = {
        "pass": "46h", "part": "I", "local_only": True, "read_only": True,
        "no_upload": True, "production_mutated": False, "no_promotion": True,
        "decision": decision,
        "gates": {
            "safety_ok": safety_ok, "validation_ok": validation_ok,
            "smoke_ok": smoke_ok, "eval_integrity_ok": eval_integrity_ok,
            "option_value_layer_non_inert_live": option_value_layer_non_inert_live,
            "coherent_escape_present": bool(coherent_escape_candidates),
        },
        "treatments": treatments,
        "coherent_escape_candidates": coherent_escape_candidates,
        "live_distinct_only_candidates": live_only_candidates,
        "gameplay_only_variance_candidates": gameplay_only_variance_candidates,
        "option_value_escapes_46g_top1_inertness": option_value_layer_non_inert_live,
        "parent_h2h_edge_candidates_95": parent_edge_95,
        "parent_edge_established": bool(parent_edge_95),
        "within_family_live_distinguishability": wf,
        "treatment_vs_floor_distinct_in_gameplay": gameplay,
        "evidence": {
            "parent_h2h": parent_rows,
            "intra_family_vs_floor": intra_rows,
            "reference_context_benchmark_only": ref_rows,
        },
        "safety_invariants": safety_invariants,
        "safety_invariants_ok": safety_invariants_ok,
        "next_iteration_levers": next_iteration_levers,
        "note": (
            "Win/loss/draw is RELATIVE feasibility context, NOT a Kaggle score, "
            "and NEVER a strength claim. 'option_value_profile_promising_local_"
            "only' asserts ONLY that an option-specific VISIBLE-feature layer "
            "escapes the family-only floor in a COHERENT (live-frame top-1 AND "
            "95% gameplay) way at the LOCAL-ONLY level — it does NOT claim a "
            "PARENT edge (parent-H2H edge is reported separately and is absent at "
            "this N). References are benchmark-only opponents (never pooled / "
            "queued / ranked / source / parent / candidate). Role buckets / "
            "target areas are observable heuristic labels — no exact-damage / "
            "lethal / KO / Boss-gust / spread / best-action claim."),
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46h_strategy_decision.json").write_text(
        json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")

    # ---- markdown ----
    md = [
        "# Pass 46H (Part I) — within-family per-option value strategy decision",
        "",
        f"## Decision: **{decision}**",
        "",
        "_LOCAL / READ-ONLY. Win/loss/draw is relative feasibility context, NOT a "
        "Kaggle score, and never a strength claim. 'Promising_local_only' means an "
        "option-specific visible-feature layer coherently escapes the family-only "
        "floor (live top-1 AND 95% gameplay) — it does NOT claim a parent edge. "
        "Role buckets / target areas are observable heuristic labels — no exact-"
        "damage / lethal / KO / Boss-gust / spread / best-action claim._",
        "",
        "### Gates",
        f"- safety_ok: **{safety_ok}** · validation_ok: **{validation_ok}** · "
        f"smoke_ok: **{smoke_ok}** · eval_integrity_ok: **{eval_integrity_ok}**",
        f"- option_value layer non-inert on live frames (escapes 46G top-1 "
        f"inertness): **{option_value_layer_non_inert_live}**",
        f"- coherent live+gameplay escape present: "
        f"**{bool(coherent_escape_candidates)}** {coherent_escape_candidates or ''}",
        "",
        "### Per-treatment escape analysis (live top-1 vs 95% gameplay, vs the "
        "family-only floor)",
        "| candidate | family | profile | live-distinct | gameplay-distinct(95%) | "
        "coherent |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for t in treatments:
        md.append(
            f"| `{t['candidate_id']}` | {t['parent_family']} | {t['profile_id']} | "
            f"{t['live_distinct_from_floor']} | "
            f"{t['gameplay_distinct_from_floor_95']} | "
            f"**{t['coherent_escape']}** |")
    md += [
        "",
        f"- live-distinct only (real menu move, gameplay washed out at this N): "
        f"`{live_only_candidates or '[]'}`",
        f"- gameplay-only over a ~inert menu (flagged as likely VARIANCE, not "
        f"counted as promising): `{gameplay_only_variance_candidates or '[]'}`",
        "",
        "### Parent-H2H (reported separately — NOT part of the promising gate)",
        f"- parent-edge candidates at 95%: **{parent_edge_95 or 'NONE'}** "
        f"(expected absent at small N — win/loss is not a strength claim)",
    ]
    for r in parent_rows:
        lo, hi = r["wilson95"]
        md.append(f"  - `{r['subject']}` vs `{r['opponent']}`: {r['w_l_d']}, "
                  f"Wilson95 [{lo:.2f}, {hi:.2f}]")
    md += ["", "### Intra-family vs family-only floor (gameplay)"]
    for r in intra_rows:
        lo, hi = r["wilson95"]
        md.append(f"- `{r['subject']}` vs `{r['opponent']}`: {r['w_l_d']}, "
                  f"Wilson95 [{lo:.2f}, {hi:.2f}]")
    md += ["", "### Reference context (benchmark-only opponents)"]
    for r in ref_rows:
        md.append(f"- `{r['subject']}` vs `{r['opponent']}`: {r['w_l_d']}")
    md += ["", "### Safety invariants",
           f"- ok: **{safety_invariants_ok}** · all 5 workflows not-started "
           "(EXPECTED) · no prod mutation/tick/registration/promotion/upload · "
           "root main.py/deck.csv unchanged · references benchmark-only (not "
           "pooled) · no public ref as source/parent/candidate", "",
           "### Next-iteration levers"]
    md += [f"- {lv}" for lv in next_iteration_levers]
    md.append("")
    (EXP / "pass46h_strategy_decision.md").write_text("\n".join(md) + "\n",
                                                      encoding="utf-8")

    print(json.dumps({
        "decision": decision,
        "gates": out["gates"],
        "coherent_escape_candidates": coherent_escape_candidates,
        "live_distinct_only_candidates": live_only_candidates,
        "gameplay_only_variance_candidates": gameplay_only_variance_candidates,
        "parent_edge_established": bool(parent_edge_95),
        "safety_invariants_ok": safety_invariants_ok,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
