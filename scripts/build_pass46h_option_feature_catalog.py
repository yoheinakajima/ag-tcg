#!/usr/bin/env python3
"""PASS 46H (Part C) — per-option feature & profile catalog.
LOCAL / read-only.

Emits a machine-readable + human-readable catalog of the within-family per-OPTION value
scorer (``ptcg_activegraph.analysis.option_value_features``): the family map, the coarse
role-token vocabulary, the observable feature schema, the three interpretable profiles
(family_only_floor_v1 / option_value_v1 / conservative_option_value_v1), the lexicographic
safety bound, and the fixed ledger of claims the scorer REFUSES to make. Also re-extracts
the INLINE region and confirms it execs as a self-contained pure-builtin module.

Writes data/experiments/pass46h_option_feature_catalog.{json,md}. No mutation, no upload,
no events, no candidate generation, no prod access.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from ptcg_activegraph.analysis import option_value_features as OV  # noqa: E402

EXP = REPO / "data" / "experiments"
ROLE_MAPS = EXP / "pass46h_role_maps.json"

FEATURE_SCHEMA = [
    ("bias", "constant 1.0 (the family-floor intercept)"),
    ("family", "coarse action family from the option's own type code (honest label)"),
    ("resolved_card_id", "card id the option PLAYS/SELECTS, resolved from area/index "
     "against YOUR visible hand or the OFFERED select.deck (None if not resolvable)"),
    ("target_card_id", "card id of the in-play pokemon the option targets "
     "(inPlayArea 4 active / 5 bench, inPlayIndex into your own board)"),
    ("target_area", "'active' / 'bench' / 'none' — WHICH of your pokemon, not that it is correct"),
    ("target_energy_count", "visible energy COUNT on the target (len of its energy list)"),
    ("productive_alternatives", "1.0 if a non-end-turn option remains in the menu"),
]

ROLE_TOKEN_DOC = {
    "energy": "a Basic/Special Energy card",
    "basic": "a Basic Pokémon",
    "evo": "a Stage 1/2 (evolution) Pokémon",
    "item": "a Trainer Item",
    "supporter": "a Trainer Supporter",
    "tool": "a Pokémon Tool (Trainer; note it contains 'pok' yet is NOT a Pokémon)",
    "stadium": "a Stadium (Trainer)",
    "search": "card text searches the deck (search your deck / search for / look at the top)",
    "draw": "card text draws cards",
    "attacker": "a Pokémon with a printed attack (Move Name + Damage present)",
    "ex": "a Pokémon ex / Mega Pokémon ex",
}


def main() -> int:
    inline_src = OV.inline_region_source()
    inline_ok = bool(inline_src)
    exec_ok = False
    exported = []
    if inline_ok:
        ns: dict = {}
        try:
            exec(inline_src, ns)  # noqa: S102 (verifying the region is self-contained)
            exec_ok = True
            exported = sorted(
                k for k in ("choose_indices", "score_option", "score_options",
                            "extract_features", "family_for_option", "option_value",
                            "resolve_play_card")
                if k in ns)
        except Exception as exc:  # noqa: BLE001
            exported = [f"exec_error:{exc}"]

    # Example profiles over whatever role maps Part B produced (else empty).
    role_maps = {}
    if ROLE_MAPS.exists():
        role_maps = json.loads(ROLE_MAPS.read_text(encoding="utf-8"))
    example_family = next(iter(role_maps), None)
    example_rm = role_maps.get(example_family, {}).get("role_map", {}) \
        if example_family else {}

    profiles = OV.default_profiles(example_rm)
    # strip the (large) embedded role map from the catalog copy; keep weights only.
    profile_summaries = {}
    for pid, prof in profiles.items():
        profile_summaries[pid] = {
            "profile_id": prof["profile_id"],
            "scoring_mode": prof["scoring_mode"],
            "schema_version": prof["schema_version"],
            "weights": prof.get("weights"),
            "option_weights": prof.get("option_weights", {}),
            "role_map_embedded": bool(prof.get("role_map")),
        }

    lex_bounds = {}
    for fam, info in role_maps.items():
        rm = info.get("role_map", {})
        lex_bounds[fam] = {
            "max_abs_option_value": round(OV.max_abs_option_value(rm), 4),
            "lex_scale": OV.LEX_SCALE,
            "strictly_dominated": OV.max_abs_option_value(rm) < OV.LEX_SCALE,
        }

    out = {
        "pass": "46H",
        "part": "C_option_feature_catalog",
        "module": "ptcg_activegraph.analysis.option_value_features",
        "schema_version": OV.PROFILE_SCHEMA_VERSION,
        "local_only": True,
        "no_upload": True,
        "inline_region": {
            "extracted": inline_ok,
            "self_contained_exec_ok": exec_ok,
            "exported_callables": exported,
            "chars": len(inline_src),
        },
        "option_type_to_family": OV.OPTION_TYPE_CLASS,
        "family_feature_keys": OV.FAMILY_FEATURE,
        "role_tokens": dict(ROLE_TOKEN_DOC),
        "feature_schema": [{"key": k, "doc": d} for k, d in FEATURE_SCHEMA],
        "profiles": profile_summaries,
        "option_value_priors": OV.OPTION_VALUE_PRIORS,
        "floor_family_weights": OV.FLOOR_FAMILY_WEIGHTS,
        "lexicographic_safety": lex_bounds,
        "unsupported_claims": OV.unsupported_scorer_claims(),
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46h_option_feature_catalog.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# PASS 46H — Part C: Per-Option Feature & Profile Catalog", "",
        f"- Module: `{out['module']}` (schema `{out['schema_version']}`).",
        f"- INLINE region: extracted={inline_ok}, self-contained exec OK={exec_ok}, "
        f"exports {', '.join(exported)}.", "",
        "## Observable feature schema (per option)", "",
        "| feature | meaning |", "|---|---|",
    ]
    for k, d in FEATURE_SCHEMA:
        lines.append(f"| `{k}` | {d} |")
    lines += ["", "## Coarse role-token vocabulary", "", "| token | meaning |",
              "|---|---|"]
    for k, d in ROLE_TOKEN_DOC.items():
        lines.append(f"| `{k}` | {d} |")
    lines += ["", "## Profiles", "",
              "| profile | mode | option layer |", "|---|---|---|"]
    for pid, ps in profile_summaries.items():
        layer = "inert (family floor only)" if not ps["option_weights"] \
            else f"{len(ps['option_weights'])} interpretable priors"
        lines.append(f"| `{pid}` | {ps['scoring_mode']} | {layer} |")
    lines += ["", "## Lexicographic safety (conservative profile)", ""]
    for fam, b in lex_bounds.items():
        lines.append(f"- {fam}: max|option_value| = {b['max_abs_option_value']} "
                     f"< LEX_SCALE {b['lex_scale']} -> dominated: {b['strictly_dominated']}.")
    lines += ["", "## Claims this scorer REFUSES to make", ""]
    for k, v in out["unsupported_claims"].items():
        lines.append(f"- **{k}** — {v}")
    (EXP / "pass46h_option_feature_catalog.md").write_text("\n".join(lines) + "\n",
                                                          encoding="utf-8")
    print(f"OK: inline exec={exec_ok}, exports={len(exported)}, "
          f"profiles={len(profile_summaries)}, families_with_bounds={len(lex_bounds)}")
    return 0 if (inline_ok and exec_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
