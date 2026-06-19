#!/usr/bin/env python3
"""Pass 30 (Part C+D) — existing-portfolio registry + hardening plan. LOCAL.

Reads experiments/pass30_existing_portfolio.yaml (OUR families/candidates only —
no opponent clones) and the Part-E build manifest, then emits:

  * data/experiments/pass30_existing_portfolio_registry.{json,md} — per-candidate
    inventory (candidate_id, family_id, parent_id, tarball/playbook/deck paths,
    status, validation status if known, prior league/Kaggle result, notes).
  * data/experiments/pass30_hardening_plan.{json,md} — at most 5 variant tracks
    (Dragapult confirm, Venusaur loop guard, Raging Bolt structural A/B, Water
    benchmark, Charizard/Gardevoir diagnostics) with hypothesis / expected
    improvement / risk / parent / delta type / build_allowed / reason.

Read-only over artifacts; no upload, no root edits.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import yaml  # type: ignore  # noqa: E402

REGISTRY = REPO / "experiments" / "pass30_existing_portfolio.yaml"
MANIFEST = REPO / "data" / "experiments" / "pass30_candidate_manifest.json"
LIVE = REPO / "data" / "experiments" / "pass30_live_score_status.json"
EXP = REPO / "data" / "experiments"

# Prior internal-league results carried forward as context (directional only).
PRIOR_LEAGUE = {
    "league_water_core_reference": "Pass 27 strong_reference (top of internal league)",
    "league_dragapult_spread": "Pass 17/27 viable control; parent of family",
    "league_dragapult_v1_search_only": "Pass 19 child; near-parent, unstable H2H",
    "league_dragapult_v1_draw_only": "Pass 19 child; weaker than search_only",
    "league_mega_venusaur_tank": "Pass 27 effect-loop stalls; broken in league",
    "effect_loop_exit_guard_v1": "Pass 29 runtime guard; not yet league-confirmed",
    "league_raging_bolt_ogerpon": "Pass 17/27/28 ~0-win baseline in internal league",
    "league_mega_charizard_x_burst": "Pass 27 high-complexity diagnostic",
    "league_mega_gardevoir_psychic_ramp": "Pass 27 high-complexity diagnostic",
    "league_durant_deckout_carousel": "blocked_from_league by design (deckout pilot)",
}


def _deck_path(cid: str) -> str:
    p = REPO / "experiments" / "runs_pass30" / cid / "deck.csv"
    if p.exists():
        return str(p.relative_to(REPO))
    return f"(embedded in data/submissions/candidates_pass30/{cid}.tar.gz)"


def build_registry(reg: dict, manifest: dict, live: dict) -> dict:
    by_cid = {r["candidate_id"]: r for r in manifest.get("results", [])}
    fams = []
    for fam_key, fam in (reg.get("families") or {}).items():
        cands = []
        for c in fam.get("candidates", []):
            cid = c["candidate_id"]
            info = by_cid.get(cid, {})
            cands.append({
                "candidate_id": cid,
                "family_id": fam.get("family_id", fam_key),
                "parent_id": c.get("parent_id"),
                "kind": c.get("kind"),
                "role": c.get("role"),
                "tarball": info.get("tarball")
                or f"data/submissions/candidates_pass30/{cid}.tar.gz",
                "source_tarball": c.get("source_tarball"),
                "playbook": c.get("playbook"),
                "deck": _deck_path(cid),
                "status": "built" if info.get("built") else "blocked_build",
                "validation_status": "pending_part_F",
                "prior_league_result": PRIOR_LEAGUE.get(cid),
                "prior_kaggle_score": c.get("prior_kaggle_score"),
                "blocked_from_league": bool(c.get("blocked_from_league")),
                "notes": (c.get("notes") or "").strip() or None,
                "no_upload": True,
            })
        fams.append({
            "family_key": fam_key, "family_id": fam.get("family_id", fam_key),
            "role": fam.get("role"),
            "hardening_stance": (fam.get("hardening_stance") or "").strip(),
            "candidates": cands,
        })
    return {
        "pass": "30", "part": "C", "local_only": True, "no_upload": True,
        "upload_performed": False, "is_kaggle_leaderboard": False,
        "no_opponent_clones": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "live_score_leader": (live.get("live_score_leader") or {}).get("fileName"),
        "water_family_current_best":
            (live.get("water_family_current_best") or {}).get("fileName"),
        "portfolio_reference":
            (live.get("portfolio_reference") or {}).get("fileName"),
        "families": fams,
        "note": ("All entries are OUR existing decks or variants of them; no opponent "
                 "decks were cloned. Internal results are not Kaggle results."),
    }


def build_plan(reg: dict, manifest: dict) -> dict:
    by_cid = {r["candidate_id"]: r for r in manifest.get("results", [])}

    def built(cid):
        return bool(by_cid.get(cid, {}).get("built"))

    tracks = [
        {
            "track": "Track 1 — Dragapult confirmation",
            "candidates": ["league_dragapult_spread",
                           "league_dragapult_v1_search_only",
                           "league_dragapult_v1_draw_only"],
            "hypothesis": ("search_only/draw_only children change draw vs search "
                           "weighting; more games should resolve whether either is "
                           "robustly better than the parent."),
            "expected_improvement": ("stable H2H verdict (parent vs children) at "
                                     "10+ games/seat."),
            "risk": "children may remain within noise of the parent.",
            "parent": "league_dragapult_spread",
            "delta_type": "reused_prior_candidate",
            "build_allowed": False,
            "reason": "reuse existing pass19 children; no new Dragapult build needed.",
        },
        {
            "track": "Track 2 — Venusaur effect-loop fixed candidate",
            "candidates": ["league_mega_venusaur_tank", "effect_loop_exit_guard_v1"],
            "hypothesis": ("the Pass 29 runtime exit guard breaks the non-progressing "
                           "loop; question is whether that makes Venusaur "
                           "league-playable, not just statically fixed."),
            "expected_improvement": ("guard child completes games and wins more than "
                                     "the looping parent."),
            "risk": "may fix the loop yet remain fixed_but_not_competitive.",
            "parent": "league_mega_venusaur_tank",
            "delta_type": "runtime_hook",
            "build_allowed": False,
            "reason": "reuse Pass 29 effect_loop_exit_guard_v1 (deck identical to parent).",
        },
        {
            "track": "Track 3 — Raging Bolt structural hardening (A + B)",
            "candidates": ["league_raging_bolt_consistency_v1",
                           "league_raging_bolt_energy_attacker_v1"],
            "variants": [
                {"variant": "A — consistency rebuild",
                 "candidate": "league_raging_bolt_consistency_v1",
                 "hypothesis": ("trimming situational disruption/recovery and "
                                "smoothing the energy base raises consistent "
                                "attach/attack frequency."),
                 "expected_improvement": ("improve from the ~0-win base baseline via "
                                          "deck skeleton only (no runtime rules)."),
                 "risk": "structural-only changes may not overcome pilot/deck "
                         "mismatch."},
                {"variant": "B — energy attacker rebuild",
                 "candidate": "league_raging_bolt_energy_attacker_v1",
                 "hypothesis": ("maximizing the Fighting energy base + Crispin accel "
                                "fuels Raging Bolt ex's energy-scaling attack faster."),
                 "expected_improvement": ("earlier/bigger attacks than the base "
                                          "skeleton."),
                 "risk": "over-weighting energy can starve the draw/setup engine."},
            ],
            "hypothesis": ("two small structural rebuilds of the base Raging Bolt "
                           "skeleton (consistency vs energy-attacker) test whether a "
                           "deck-only change can lift the ~0-win base."),
            "expected_improvement": ("at least one variant beats the base skeleton via "
                                     "deck structure alone (no runtime rules)."),
            "risk": "structural-only changes may not overcome the pilot/deck mismatch.",
            "parent": "league_raging_bolt_ogerpon",
            "delta_type": "deck_skeleton",
            "build_allowed": True,
            "reason": ("the single Raging Bolt structural track; AT MOST 2 NEW RB "
                       "builds (variants A + B) from OUR RB idea, validated ids only."),
        },
        {
            "track": "Track 4 — Water benchmark",
            "candidates": ["league_water_anti_disruption_pivot_v1",
                           "league_water_core_reference",
                           "core_pilot_water_v2_runtime"],
            "hypothesis": ("Water remains the local reference; no new Water candidate "
                           "is needed."),
            "expected_improvement": "n/a — benchmark only.",
            "risk": "none; benchmark anchor.",
            "parent": "league_water_core_reference",
            "delta_type": "reused_prior_candidate",
            "build_allowed": False,
            "reason": "keep current best Water as benchmark; build nothing.",
        },
        {
            "track": "Track 5 — Charizard / Gardevoir diagnostics",
            "candidates": ["league_mega_charizard_x_burst",
                           "league_mega_gardevoir_psychic_ramp"],
            "hypothesis": ("high-complexity engines remain diagnostics until card "
                           "observability improves; include as benchmarks only."),
            "expected_improvement": "n/a — diagnostics.",
            "risk": "engine-card behavior under-observable.",
            "parent": None,
            "delta_type": "reused_prior_candidate",
            "build_allowed": False,
            "reason": "no new complex-engine variant; include existing if smoke-valid.",
        },
    ]
    new_builds = [c for t in tracks if t["build_allowed"] for c in t["candidates"]]
    return {
        "pass": "30", "part": "D", "local_only": True, "no_upload": True,
        "upload_performed": False, "is_kaggle_leaderboard": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "max_variants": 5,
        "new_raging_bolt_builds": [c for c in new_builds if "raging_bolt" in c],
        "new_builds_total": len(new_builds),
        "new_builds_actually_built": [c for c in new_builds if built(c)],
        "tracks": tracks,
        "note": ("At most 5 hardening variant tracks. Only the two Raging Bolt "
                 "structural skeletons are newly built; everything else reuses prior "
                 "artifacts. No opponent clones, no invented ids."),
    }


def _md_registry(reg_out: dict) -> str:
    L = ["# Pass 30 — Existing Portfolio Registry (Part C)", "",
         "> LOCAL ONLY. OUR decks/variants only — **no opponent clones**. Internal "
         "results are NOT Kaggle results.", "",
         f"- generated: {reg_out['generated_at']}",
         f"- live_score_leader: `{reg_out['live_score_leader']}`",
         f"- water_family_current_best: `{reg_out['water_family_current_best']}`",
         f"- portfolio_reference: `{reg_out['portfolio_reference']}`",
         f"- upload_performed: **{reg_out['upload_performed']}**  no_upload: **True**",
         ""]
    for fam in reg_out["families"]:
        L += [f"## {fam['family_id']} — {fam['role']}", "",
              f"_{fam['hardening_stance']}_", "",
              "| candidate | parent | kind | role | status | prior league | "
              "prior Kaggle | blocked |",
              "|---|---|---|---|---|---|---|---|"]
        for c in fam["candidates"]:
            L.append(f"| `{c['candidate_id']}` | {c['parent_id'] or '—'} | "
                     f"{c['kind']} | {c['role']} | {c['status']} | "
                     f"{c['prior_league_result'] or '—'} | "
                     f"{c['prior_kaggle_score'] or '—'} | "
                     f"{c['blocked_from_league']} |")
        L.append("")
    L += [reg_out["note"], ""]
    return "\n".join(L)


def _md_plan(plan: dict) -> str:
    L = ["# Pass 30 — Hardening Plan (Part D)", "",
         "> LOCAL ONLY. At most 5 variant tracks; only Raging Bolt structural "
         "skeletons are newly built. No opponent clones, no invented ids.", "",
         f"- generated: {plan['generated_at']}",
         f"- new Raging Bolt builds: **{plan['new_raging_bolt_builds']}**",
         f"- new builds actually built: **{plan['new_builds_actually_built']}**", ""]
    for t in plan["tracks"]:
        L += [f"## {t['track']}", "",
              f"- candidates: {', '.join('`%s`' % c for c in t['candidates'])}",
              f"- hypothesis: {t['hypothesis']}",
              f"- expected improvement: {t['expected_improvement']}",
              f"- risk: {t['risk']}",
              f"- parent: `{t['parent']}`" if t['parent'] else "- parent: —",
              f"- delta type: **{t['delta_type']}**",
              f"- build_allowed: **{t['build_allowed']}** — {t['reason']}", ""]
    L += [plan["note"], ""]
    return "\n".join(L)


def main() -> int:
    reg = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() \
        else {"results": []}
    live = json.loads(LIVE.read_text(encoding="utf-8")) if LIVE.exists() else {}

    reg_out = build_registry(reg, manifest, live)
    plan = build_plan(reg, manifest)

    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass30_existing_portfolio_registry.json").write_text(
        json.dumps(reg_out, indent=2), encoding="utf-8")
    (EXP / "pass30_existing_portfolio_registry.md").write_text(
        _md_registry(reg_out), encoding="utf-8")
    (EXP / "pass30_hardening_plan.json").write_text(
        json.dumps(plan, indent=2), encoding="utf-8")
    (EXP / "pass30_hardening_plan.md").write_text(_md_plan(plan), encoding="utf-8")

    n_cands = sum(len(f["candidates"]) for f in reg_out["families"])
    print(f"registry: {len(reg_out['families'])} families, {n_cands} candidates")
    print(f"plan: {len(plan['tracks'])} tracks, "
          f"new_builds={plan['new_builds_actually_built']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
