#!/usr/bin/env python3
"""PASS 46G (Part C) — interpretable multi-profile catalog (not a single profile).

Hand-designs a SMALL catalog of fully interpretable turn-planner profiles for the
Pass-46G v2 scorer (``turn_planner_profiles.py``, schema ``pass46g_turn_scorer_v1``).
Every profile is a transparent additive linear model:

    score = bias + family_weight + phase_adj[phase][family] + role_adj[role]
            + end_pass_penalty(if ending while productive options remain)
            + deckout_draw_penalty(if deck is low and the family is draw-ish)

All designed profiles SHARE ONE base family-weight floor SEEDED from the Pass-46F
search-oracle calibration (``pass46f_score_profile.json``'s robust-median weights) so
that each profile differs from the next ONLY by the interpretable phase / role /
penalty layer it adds. Two measurement-anchor profiles are included so Part D can
DECOMPOSE the offline lift:

  * ``generic_progress_v0``          — the canonical uncalibrated family ordering
    (the charter's named baseline; from the scorer module's DEFAULT_PROFILE).
  * ``search_seeded_family_only_v1`` — the 46F search-seeded family weights with NO
    phase/role layer; isolates "better family weights" from "phase/role awareness".

Designed (candidate) profiles (charter Part C required types):
  1. ``phase_aware_tempo_v1`` — different scoring by phase; strong penalty on ending
     the turn while productive options remain.
  2. ``role_aware_energy_v1`` — stronger role-aware attach/search/move; invests in the
     active attacker (targets_active) while still developing a benched backup
     (targets_bench rewarded), gated by phase so it only leans into attacking once an
     attack option is actually on the menu.
  3. ``balanced_control_v1``  — more cautious draw / deckout / discard penalties
     (applicable here: the build set is Water + Diamond).

Each profile EXPLICITLY lists: action-family weights, phase weights, role weights,
deckout/draw safety, the unsupported-claims guard, and an explicit no-claims list
(no exact damage / lethal / Boss / gust / spread / best-action). The catalog is
DETERMINISTIC (hand-coded constants seeded from a deterministic source) — a canonical
sha256 is recorded so a test can assert reproducibility.

LOCAL / READ-ONLY. No mutation, no upload, no candidate generation, no events.
Runnable standalone and importable (``run_catalog() -> dict``).
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.analysis import turn_planner_profiles as TP  # noqa: E402

EXP = REPO / "data" / "experiments"
SEED_JSON = EXP / "pass46f_score_profile.json"

# Profiles that Part E actually BUILDS into candidates (default-4 batch: 2 of these
# x 2 source families). The rest are catalog-designed measurement anchors / expansion.
BUILD_PROFILE_IDS = ["phase_aware_tempo_v1", "role_aware_energy_v1"]
EXPANSION_PROFILE_IDS = ["balanced_control_v1"]

NO_CLAIMS = [
    "no_exact_damage", "no_lethal", "no_missed_ko", "no_boss_gust", "no_spread",
    "no_best_action", "phase_is_observable_label_not_strength_claim",
    "role_is_target_area_label_not_correctness_claim",
]


def _seed_family_weights() -> tuple[dict, str]:
    """Base family weights seeded from the 46F search-oracle calibration (fallback:
    the scorer module's DEFAULT_PROFILE)."""
    if SEED_JSON.exists():
        d = json.loads(SEED_JSON.read_text(encoding="utf-8"))
        cp = d.get("calibrated_profile") or {}
        w = cp.get("weights")
        if isinstance(w, dict) and w:
            return ({k: float(v) for k, v in w.items()},
                    f"pass46f:{cp.get('profile_id', 'search_calibrated_v0')}")
    return ({k: float(v) for k, v in TP.DEFAULT_PROFILE["weights"].items()},
            "scorer_default_profile")


def _profile(profile_id, rationale, base_weights, weight_deltas=None,
             phase_weights=None, role_weights=None,
             end_pass_penalty_when_productive=0.0, deckout_draw_penalty=0.0,
             calibrated=False, source="hand_designed"):
    weights = dict(base_weights)
    for fkey, dv in (weight_deltas or {}).items():
        weights[fkey] = round(weights.get(fkey, 0.0) + dv, 4)
    return {
        "profile_id": profile_id,
        "schema_version": TP.PROFILE_SCHEMA_VERSION,
        "calibrated": calibrated,
        "source": source,
        "rationale": rationale,
        "weights": weights,
        "phase_weights": phase_weights or {},
        "role_weights": role_weights or {},
        "end_pass_penalty_when_productive": float(end_pass_penalty_when_productive),
        "deckout_draw_penalty": float(deckout_draw_penalty),
        "deckout_draw_safety": {
            "deckout_draw_penalty": float(deckout_draw_penalty),
            "drawish_families": list(TP.DRAWISH_FAMILIES),
            "low_deck_threshold": TP.PHASE_LOW_DECK,
            "note": "penalty applied to draw-ish families only when your visible "
            "deckCount is at/below the low-deck threshold (count-only signal).",
        },
        "unsupported_claims": TP.unsupported_scorer_claims(),
        "no_claims": list(NO_CLAIMS),
    }


def build_profiles() -> dict:
    base, seed_src = _seed_family_weights()

    profiles = {}

    # ---- Measurement-anchor profiles (NOT built into candidates) ----
    profiles["generic_progress_v0"] = {
        **copy.deepcopy(TP.DEFAULT_PROFILE),
        "rationale": "Canonical uncalibrated 'make progress, end turn last' family "
        "ordering. The charter-named Part-D baseline. No phase/role layer.",
        "deckout_draw_safety": {
            "deckout_draw_penalty": 0.0,
            "drawish_families": list(TP.DRAWISH_FAMILIES),
            "low_deck_threshold": TP.PHASE_LOW_DECK,
            "note": "baseline applies no deckout/draw penalty.",
        },
        "no_claims": list(NO_CLAIMS),
        "unsupported_claims": TP.unsupported_scorer_claims(),
        "role": "measurement_baseline",
    }
    profiles["search_seeded_family_only_v1"] = {
        **_profile(
            "search_seeded_family_only_v1",
            "46F search-oracle-seeded family weights with NO phase/role layer. Lets "
            "Part D separate the value of better family weights from the value of "
            "phase/role awareness.",
            base, source=f"seed:{seed_src}"),
        "role": "measurement_family_reference",
    }

    # ---- Designed (candidate) profiles ----
    profiles["phase_aware_tempo_v1"] = {
        **_profile(
            "phase_aware_tempo_v1",
            "Tempo planner: scores the SAME action family differently by observable "
            "phase (setup develops the board and avoids attacking; develop attaches/"
            "uses abilities; attack_ready commits to the attack family; recovery "
            "rebuilds the board and re-routes energy; late_game leans on attacking). "
            "Ending the turn is strongly penalised whenever a productive option "
            "remains. phase is a coarse observable label, not a strength/lethal claim.",
            base,
            phase_weights={
                "setup": {"play_from_hand": 0.6, "play_in_play": 0.5,
                          "attach_energy": 0.3, "attack": -0.4},
                "develop": {"attach_energy": 0.5, "use_ability": 0.4,
                            "play_from_hand": 0.3, "attack": -0.2},
                "attack_ready": {"attack": 1.0, "attach_energy": 0.2,
                                 "play_from_hand": -0.2},
                "recovery": {"play_from_hand": 0.5, "play_in_play": 0.5,
                             "use_ability": 0.4, "move_energy": 0.4, "attack": -0.3},
                "late_game": {"attack": 0.6, "use_ability": 0.3, "select_card": -0.2},
            },
            role_weights={},
            end_pass_penalty_when_productive=-3.0,
            deckout_draw_penalty=0.0,
            source=f"hand_designed; family_seed={seed_src}"),
        "role": "candidate",
    }
    profiles["role_aware_energy_v1"] = {
        **_profile(
            "role_aware_energy_v1",
            "Role/energy planner (PURE phase/role layer on the shared family floor — "
            "no family-weight deltas): prefers options that target an in-play pokemon — "
            "the active attacker most (targets_active) but a benched backup too "
            "(targets_bench still rewarded), so it develops a backup rather than "
            "over-investing in one attacker. Phase weights gate it so attacking only "
            "outscores development once an attack option is actually on the legal menu "
            "(attack_ready). role is a target-AREA label (which of YOUR pokemon), never "
            "a targeting/lethal claim.",
            base,
            phase_weights={
                "setup": {"play_from_hand": 0.4, "play_in_play": 0.4},
                "develop": {"attach_energy": 0.4, "select_card": 0.2},
                "attack_ready": {"attack": 0.7, "attach_energy": 0.3},
                "recovery": {"play_in_play": 0.4, "move_energy": 0.4},
                "late_game": {"attack": 0.4},
            },
            role_weights={"targets_active": 0.8, "targets_bench": 0.5,
                          "role_none": 0.0},
            end_pass_penalty_when_productive=-2.0,
            deckout_draw_penalty=-0.5,
            source=f"hand_designed; family_seed={seed_src}"),
        "role": "candidate",
    }
    profiles["balanced_control_v1"] = {
        **_profile(
            "balanced_control_v1",
            "Cautious control planner (Water/Diamond; PURE phase/role layer on the "
            "shared family floor — no family-weight deltas): applies a STRONG "
            "deckout/draw safety penalty so it stops drawing/searching when the deck is "
            "visibly low, and late_game phase weights further suppress draw-ish "
            "families to avoid decking out while leaning on attacking. Patient "
            "(moderate end-pass penalty) but still progresses. No deckout/loss claim is "
            "asserted.",
            base,
            phase_weights={
                "setup": {"play_from_hand": 0.5, "play_in_play": 0.4},
                "develop": {"attach_energy": 0.4, "use_ability": 0.3},
                "attack_ready": {"attack": 0.8},
                "recovery": {"play_in_play": 0.5, "play_from_hand": 0.4,
                             "use_ability": 0.3},
                "late_game": {"attack": 0.5, "use_ability": -0.4,
                              "select_card": -0.4},
            },
            role_weights={"targets_active": 0.4, "targets_bench": 0.4,
                          "role_none": 0.0},
            end_pass_penalty_when_productive=-1.5,
            deckout_draw_penalty=-2.5,
            source=f"hand_designed; family_seed={seed_src}"),
        "role": "expansion",
    }
    return profiles, base, seed_src


def _validate_profile(pid: str, prof: dict) -> dict:
    """Structural + never-raise + legality checks for one profile."""
    issues = []
    valid_fams = set(TP.FAMILY_FEATURE.keys())
    valid_fkeys = set(TP.FEATURE_KEYS)
    # weight keys must be known feature keys
    for k in prof.get("weights", {}):
        if k not in valid_fkeys:
            issues.append(f"unknown_weight_key:{k}")
    # phase_weights keys must be valid phases; inner keys valid family names
    for ph, fam_adj in (prof.get("phase_weights") or {}).items():
        if ph not in TP.PHASES:
            issues.append(f"unknown_phase:{ph}")
        for fam in fam_adj:
            if fam not in valid_fams:
                issues.append(f"unknown_phase_family:{ph}.{fam}")
    # role_weights keys must be valid roles
    for r in (prof.get("role_weights") or {}):
        if r not in TP.ROLES:
            issues.append(f"unknown_role:{r}")
    # never-raise + legal pick on a battery of fixtures (incl. malformed)
    fixtures = [
        {"select": {"option": [{"type": 13, "inPlayArea": 4}, {"type": 8},
                               {"type": 14}], "minCount": 1, "maxCount": 1},
         "board": {"yourIndex": 0, "turn": 5,
                   "players": [{"active": [{"hp": 200, "maxHp": 200}], "bench": [],
                               "deckCount": 30, "prize": [None] * 6}, {}]}},
        {"select": {"option": [{"type": 9}, {"type": 7, "inPlayArea": 5},
                               {"type": 14}], "minCount": 1, "maxCount": 1},
         "board": {"yourIndex": 1, "turn": 1,
                   "players": [{}, {"active": [], "bench": [], "deckCount": 6,
                                    "prize": [None] * 2}]}},
        {"select": {"option": [{"type": 8}, {"type": 8}, {"type": 3}],
                    "minCount": 2, "maxCount": 2},
         "board": {"yourIndex": 0, "turn": 9,
                   "players": [{"active": [{"hp": 40, "maxHp": 200}], "bench": [{}],
                               "deckCount": 4, "prize": [None]}, {}]}},
        {"select": {"option": [{"type": 0}], "minCount": 0, "maxCount": 0},
         "board": None},
        {"select": "garbage", "board": "garbage"},
        {"select": None, "board": None},
    ]
    legal_ok = True
    for fx in fixtures:
        sel = fx["select"]
        board = fx["board"]
        try:
            out = TP.choose_indices(sel, board, prof)
        except Exception as exc:  # noqa: BLE001
            issues.append(f"raised:{type(exc).__name__}")
            legal_ok = False
            continue
        if not isinstance(out, list):
            issues.append("non_list_decision")
            legal_ok = False
            continue
        opts = TP._raw_options(sel) if isinstance(sel, dict) else []
        for i in out:
            if not (isinstance(i, int) and 0 <= i < len(opts)):
                issues.append(f"illegal_index:{i}")
                legal_ok = False
    # required fields present
    for fld in ("weights", "phase_weights", "role_weights",
                "deckout_draw_safety", "unsupported_claims", "no_claims"):
        if fld not in prof:
            issues.append(f"missing_field:{fld}")
    return {"profile_id": pid, "ok": not issues, "issues": issues,
            "never_raise_legal_ok": legal_ok}


def _canonical_sha(profiles: dict) -> str:
    payload = json.dumps(profiles, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_catalog() -> dict:
    EXP.mkdir(parents=True, exist_ok=True)
    profiles, base, seed_src = build_profiles()
    validations = {pid: _validate_profile(pid, p) for pid, p in profiles.items()}
    all_valid = all(v["ok"] for v in validations.values())

    data = {
        "pass": "46g", "part": "C", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "candidate_generated": False,
        "scorer_module": "src/ptcg_activegraph/analysis/turn_planner_profiles.py",
        "scorer_schema_version": TP.PROFILE_SCHEMA_VERSION,
        "family_weight_seed": seed_src,
        "base_family_weights": base,
        "phases": list(TP.PHASES), "roles": list(TP.ROLES),
        "feature_keys": list(TP.FEATURE_KEYS),
        "build_profile_ids": BUILD_PROFILE_IDS,
        "expansion_profile_ids": EXPANSION_PROFILE_IDS,
        "n_profiles": len(profiles),
        "profiles": profiles,
        "validations": validations,
        "all_profiles_valid": all_valid,
        "catalog_sha256": _canonical_sha(profiles),
        "no_claims_global": list(NO_CLAIMS),
        "notes": [
            "Hand-designed interpretable priors; NOT fit to win-rate. Part D MEASURES "
            "their offline fit vs the search oracle.",
            "All designed profiles share one 46F-seeded family-weight floor; they "
            "differ ONLY by the phase/role/penalty layer.",
            "Default batch builds the 2 candidate profiles x 2 source families (=4); "
            "balanced_control_v1 is catalog-designed + Part-D-measured but not built "
            "by default (kept for tractable eval; immediate expansion if it measures "
            "best).",
            "phase is a coarse OBSERVABLE label (own board + legal menu); role is a "
            "target-AREA label. No exact-damage/lethal/Boss/gust/spread/best-action.",
        ],
    }
    (EXP / "pass46g_profile_catalog.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        "# Pass 46G — Part C: interpretable multi-profile catalog", "",
        "_Hand-designed interpretable turn-planner profiles for the v2 scorer "
        "(`pass46g_turn_scorer_v1`). NOT fit to win-rate — Part D measures offline "
        "fit. LOCAL / READ-ONLY; no generation / upload / events. No exact-damage / "
        "lethal / Boss / gust / spread / best-action claim._", "",
        f"- family-weight seed: `{seed_src}`",
        f"- catalog sha256: `{data['catalog_sha256']}`",
        f"- all profiles valid (never-raise + legal): **{all_valid}**",
        f"- built into candidates: {BUILD_PROFILE_IDS}",
        f"- expansion (designed, not built by default): {EXPANSION_PROFILE_IDS}", "",
        "## Base family weights (shared 46F-seeded floor)",
        "| feature | weight |", "|---|---:|",
    ]
    for k in TP.FEATURE_KEYS:
        md.append(f"| {k} | {base.get(k)} |")
    for pid, p in profiles.items():
        md += [
            "", f"## `{pid}` ({p.get('role')})", "",
            f"_{p.get('rationale')}_", "",
            f"- end-pass penalty (when productive): "
            f"{p['end_pass_penalty_when_productive']}",
            f"- deckout/draw penalty (low deck, draw-ish families): "
            f"{p['deckout_draw_penalty']}",
            f"- role weights: {p['role_weights'] or '(none)'}",
        ]
        if p.get("phase_weights"):
            md.append("- phase weights:")
            for ph in TP.PHASES:
                fam_adj = p["phase_weights"].get(ph)
                if fam_adj:
                    md.append(f"  - **{ph}**: " + ", ".join(
                        f"{f} {v:+}" for f, v in fam_adj.items()))
        else:
            md.append("- phase weights: (none)")
    (EXP / "pass46g_profile_catalog.md").write_text("\n".join(md) + "\n",
                                                    encoding="utf-8")

    print(json.dumps({
        "n_profiles": len(profiles),
        "build_profile_ids": BUILD_PROFILE_IDS,
        "all_profiles_valid": all_valid,
        "catalog_sha256": data["catalog_sha256"],
        "family_weight_seed": seed_src,
        "invalid": {pid: v["issues"] for pid, v in validations.items() if not v["ok"]},
    }, indent=2))
    return data


if __name__ == "__main__":
    out = run_catalog()
    raise SystemExit(0 if out["all_profiles_valid"] else 1)
