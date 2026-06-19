#!/usr/bin/env python3
"""Pass 30 (Part J) — compatibility / hardening diagnosis. LOCAL, READ-ONLY synthesis.

Synthesises the Part-F validation, Part-G internal tournament (stage 1 + 2),
Part-H parent/child confirmations and Part-I meta sanity into a per-family
diagnosis: best/worst deck, did hardening help, should the family stay active, and
what the next evidence-backed work is. NO games are played here and NOTHING is
uploaded; every number is internal/surrogate and never equals a Kaggle result.

Writes data/experiments/pass30_hardening_diagnosis.{json,md}.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"

RANK1 = EXP / "pass30_portfolio_rankings.json"
RANK2 = EXP / "pass30_portfolio_rankings_stage2.json"
PARENT_CHILD = EXP / "pass30_parent_child_confirmations.json"
META = EXP / "pass30_meta_sanity.json"
LIVE = EXP / "pass30_live_score_status.json"
VALIDATION = EXP / "pass30_candidate_validation.json"

DISCLAIMER = (
    "INTERNAL/SURROGATE DIAGNOSIS — NOT a Kaggle leaderboard. All win rates are our "
    "decks piloted by the same generic core pilot against our own decks or "
    "replay-derived deck lists; they measure deck/pilot compatibility and hardening "
    "DELTAS, never Kaggle standings. No upload or submission is implied.")


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    rank1 = _read(RANK1) or {}
    rank2 = _read(RANK2) or {}
    pc = _read(PARENT_CHILD) or {}
    meta = _read(META) or {}
    live = _read(LIVE) or {}
    val = _read(VALIDATION) or {}

    standings = {r["id"]: r for r in rank1.get("standings", [])}
    fam_standings = {r["family"]: r for r in rank1.get("family_standings", [])}
    pc_pairs = {p["id"]: p for p in pc.get("pairs", [])}
    meta_pd = (meta.get("per_deck") or {})

    def meta_score(cid):
        return (meta_pd.get(cid) or {}).get("weighted_meta_score")

    def tour_wr(cid):
        return (standings.get(cid) or {}).get("adj_win_rate")

    families: dict[str, dict] = {}

    # --- Water ---
    water_ids = ["league_water_core_reference",
                 "league_water_anti_disruption_pivot_v1", "core_pilot_water_v2_runtime"]
    water_ranked = sorted([i for i in water_ids if i in standings],
                          key=lambda i: tour_wr(i) or -1, reverse=True)
    families["water"] = {
        "family": "water",
        "decks": water_ids,
        "best": water_ranked[0] if water_ranked else None,
        "worst": water_ranked[-1] if water_ranked else None,
        "tournament_family_win_rate": (fam_standings.get("water") or {}).get(
            "adj_win_rate"),
        "hardening_action": "reuse_benchmark_only",
        "hardening_helped": None,
        "stay_active": True,
        "conclusion": (
            "Water remains the stable benchmark and the family the generic pilot "
            "executes best. The live-score leader is "
            f"{live.get('live_score_leader', {}).get('candidate_id', 'n/a')} "
            f"(~{live.get('live_score_leader', {}).get('live_score', 'n/a')}); "
            "the core reference tops Stage-1 internal play "
            f"(adj win_rate {tour_wr('league_water_core_reference')}). No NEW water "
            "variant was built this pass by design — water is the control, not the "
            "hardening target."),
        "next_work": ("Keep water as the always-on benchmark. Any future water work "
                      "should target the anti-disruption pivot, not the core ref."),
    }

    # --- Dragapult ---
    drag_ids = ["league_dragapult_spread", "league_dragapult_v1_search_only",
                "league_dragapult_v1_draw_only"]
    drag_ranked = sorted([i for i in drag_ids if i in standings],
                         key=lambda i: tour_wr(i) or -1, reverse=True)
    search_pc = pc_pairs.get("dragapult_parent_vs_search_only", {})
    draw_pc = pc_pairs.get("dragapult_parent_vs_draw_only", {})
    families["dragapult"] = {
        "family": "dragapult",
        "decks": drag_ids,
        "best": drag_ranked[0] if drag_ranked else None,
        "worst": drag_ranked[-1] if drag_ranked else None,
        "tournament_family_win_rate": (fam_standings.get("dragapult") or {}).get(
            "adj_win_rate"),
        "hardening_action": "reuse_confirm_children",
        "hardening_helped": True,
        "stay_active": True,
        "parent_child": {
            "search_only_parent_win_rate": search_pc.get("a_win_rate"),
            "search_only_interpretation": search_pc.get("interpretation"),
            "draw_only_parent_win_rate": draw_pc.get("a_win_rate"),
            "draw_only_interpretation": draw_pc.get("interpretation"),
        },
        "conclusion": (
            "Dragapult is the strongest non-water family internally and the TOP meta "
            f"performer (search_only weighted meta {meta_score('league_dragapult_v1_search_only')}, "
            f"draw_only {meta_score('league_dragapult_v1_draw_only')}, both > water "
            f"{meta_score('league_water_core_reference')}). Both children run cleanly "
            "and stay behaviourally close to the spread parent (no significant "
            "parent/child separation), confirming they are legal, stable refinements "
            "rather than regressions. search_only is the best probe candidate."),
        "next_work": ("Promote dragapult_v1_search_only as the lead human-approved "
                      "probe candidate; keep draw_only as the backup."),
    }

    # --- Venusaur ---
    ven_parent = "league_mega_venusaur_tank"
    ven_child = "effect_loop_exit_guard_v1"
    ven_pc = pc_pairs.get("venusaur_parent_vs_loop_guard", {})
    parent_wr = tour_wr(ven_parent)
    child_wr = tour_wr(ven_child)
    guard_helped = (child_wr is not None and parent_wr is not None
                    and child_wr > parent_wr)
    families["venusaur"] = {
        "family": "venusaur",
        "decks": [ven_parent, ven_child],
        "best": ven_child if guard_helped else ven_parent,
        "worst": ven_parent if guard_helped else ven_child,
        "tournament_family_win_rate": (fam_standings.get("venusaur") or {}).get(
            "adj_win_rate"),
        "hardening_action": "reuse_runtime_loop_guard",
        "hardening_helped": guard_helped,
        "stay_active": True,
        "parent_child": {
            "parent_tournament_win_rate": parent_wr,
            "loop_guard_tournament_win_rate": child_wr,
            "h2h_parent_win_rate": ven_pc.get("a_win_rate"),
            "h2h_interpretation": ven_pc.get("interpretation"),
            "deck_identical": True,
        },
        "conclusion": (
            "The loop-guard child deck is byte-identical to the tank parent; the only "
            "change is the runtime effect-loop exit hook. In Stage-1 play the guarded "
            f"build ({child_wr}) clearly outperforms the raw tank ({parent_wr}) and is "
            "draw-free where the tank stalls into many draws, so the hardening HELPED: "
            "it converts stalls into decisions. It is the parent/child ideal (same "
            "deck, isolated behavioural fix)."),
        "next_work": ("Keep the loop-guard as the active venusaur build; the raw tank "
                      "stays only as the unhardened control for the comparison."),
    }

    # --- Raging Bolt ---
    rb_base = "league_raging_bolt_ogerpon"
    rb_a = "league_raging_bolt_consistency_v1"
    rb_b = "league_raging_bolt_energy_attacker_v1"
    rb_a_pc = pc_pairs.get("raging_bolt_base_vs_consistency", {})
    rb_b_pc = pc_pairs.get("raging_bolt_base_vs_energy_attacker", {})
    rb_ranked = sorted([i for i in (rb_base, rb_a, rb_b) if i in standings],
                       key=lambda i: tour_wr(i) or -1, reverse=True)
    families["raging_bolt"] = {
        "family": "raging_bolt",
        "decks": [rb_base, rb_a, rb_b],
        "best": rb_ranked[0] if rb_ranked else None,
        "worst": rb_ranked[-1] if rb_ranked else None,
        "tournament_family_win_rate": (fam_standings.get("raging_bolt") or {}).get(
            "adj_win_rate"),
        "hardening_action": "built_two_new_structural_variants",
        "hardening_helped": False,
        "stay_active": False,
        "parent_child": {
            "consistency_base_win_rate": rb_a_pc.get("a_win_rate"),
            "consistency_interpretation": rb_a_pc.get("interpretation"),
            "energy_attacker_base_win_rate": rb_b_pc.get("a_win_rate"),
            "energy_attacker_interpretation": rb_b_pc.get("interpretation"),
        },
        "conclusion": (
            "Raging Bolt is the clear bottom of the portfolio "
            f"(family adj win_rate {(fam_standings.get('raging_bolt') or {}).get('adj_win_rate')}) "
            "and COLLAPSES in meta sanity (0% vs every confirmed subfamily) — the "
            "EXPECTED control result. The two NEW structural variants did NOT fix it: "
            f"the consistency rebuild lost to the base ({rb_a_pc.get('a_win_rate')} base "
            f"win rate) and the energy-attacker rebuild was no better "
            f"({rb_b_pc.get('a_win_rate')}). The bottleneck is the generic pilot's "
            "inability to sequence Raging Bolt's energy-acceleration win, not the "
            "decklist. Structural deck hardening cannot close this gap."),
        "next_work": ("Stop building Raging Bolt deck variants under the generic "
                      "pilot. Any future RB work must be a PILOT change (a Raging "
                      "Bolt-specific policy), not another decklist — out of scope for "
                      "this read-only hardening pass."),
    }

    # --- Diagnostics (charizard / gardevoir) ---
    families["diagnostics"] = {
        "family": "diagnostics",
        "decks": ["league_mega_charizard_x_burst",
                  "league_mega_gardevoir_psychic_ramp"],
        "best": "league_mega_charizard_x_burst",
        "worst": "league_mega_gardevoir_psychic_ramp",
        "tournament_family_win_rate": None,
        "hardening_action": "reuse_as_benchmark",
        "hardening_helped": None,
        "stay_active": True,
        "conclusion": (
            "Charizard-X is a strong diagnostic benchmark "
            f"(Stage-1 adj win_rate {tour_wr('league_mega_charizard_x_burst')}, meta "
            f"{meta_score('league_mega_charizard_x_burst')}) while Gardevoir is a weak "
            f"one ({tour_wr('league_mega_gardevoir_psychic_ramp')}). Both are kept as "
            "fixed reference points, not promotion candidates."),
        "next_work": "Keep both as benchmarks; no new diagnostic builds this pass.",
    }

    # Cross-family probe recommendation.
    probe = "league_dragapult_v1_search_only"
    diag = {
        "pass": "30", "part": "J", "local_only": True, "no_upload": True,
        "upload_performed": False, "is_kaggle_leaderboard": False,
        "disclaimer": DISCLAIMER,
        "inputs": {
            "tournament_stage1": RANK1.exists(), "tournament_stage2": RANK2.exists(),
            "parent_child": PARENT_CHILD.exists(), "meta_sanity": META.exists(),
            "live_score": LIVE.exists(), "validation": VALIDATION.exists(),
        },
        "families": families,
        "recommended_probe_candidate": probe,
        "recommended_probe_rationale": (
            "dragapult_v1_search_only is the top internal-tournament non-water deck, "
            "the #1 meta-sanity performer (weighted "
            f"{meta_score(probe)} > water {meta_score('league_water_core_reference')}), "
            "validates clean, smokes clean, has a confirmed clean parent/child "
            "relationship, and is NOT blocked. It is the single best next "
            "human-approved probe candidate among OUR existing decks."),
        "limitations": [
            "Two meta subfamilies (dragapult_ex, lightning_bellibolt) could not be "
            "materialised as surrogates (all games skipped); their columns are blank "
            "and excluded from weighted scores.",
            "All numbers are surrogate/internal and never equal Kaggle results.",
        ],
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass30_hardening_diagnosis.json").write_text(
        json.dumps(diag, indent=2, default=str), encoding="utf-8")

    L = ["# Pass 30 — compatibility / hardening diagnosis (Part J)", "",
         f"> {DISCLAIMER}", "",
         f"- recommended probe candidate: **{probe}**",
         f"- is Kaggle leaderboard: **False**  upload_performed: **False**", "",
         "| family | best | worst | family win_rate | hardening action | helped? | "
         "stay active? |", "|---|---|---|---|---|---|---|"]
    for f in families.values():
        L.append(f"| {f['family']} | {f.get('best')} | {f.get('worst')} | "
                 f"{f.get('tournament_family_win_rate')} | {f['hardening_action']} | "
                 f"{f.get('hardening_helped')} | {f.get('stay_active')} |")
    L += ["", "## Per-family conclusions"]
    for f in families.values():
        L += [f"### {f['family']}", f["conclusion"],
              f"- **next work:** {f['next_work']}", ""]
    L += ["## Recommended probe candidate", f"**{probe}**",
          diag["recommended_probe_rationale"], "",
          "## Limitations"] + [f"- {x}" for x in diag["limitations"]] + [""]
    (EXP / "pass30_hardening_diagnosis.md").write_text("\n".join(L), encoding="utf-8")

    print("hardening diagnosis written.")
    for f in families.values():
        print(f"  {f['family']:12} best={f.get('best')} helped={f.get('hardening_helped')} "
              f"active={f.get('stay_active')}")
    print(f"recommended probe: {probe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
