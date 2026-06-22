#!/usr/bin/env python3
"""PASS 46H (Part B) — source re-affirmation + per-deck ROLE MAP attribution plan.
LOCAL / read-only.

46H does NOT re-derive the family selection from scratch: the evidence basis is the
already-registered Pass-46G source selection (same internal pool, same deterministic
evidence rule). 46H's Part-B contribution is (1) RE-VALIDATING that every built-upon
source still satisfies the hard safety constraints (internal pool only, public refs
NEVER a source, status not never-schedule/held, >= MIN_GAMES internal games, archetype
fit), and (2) building the per-deck ROLE MAP (card_id -> coarse role tokens) and the
profile-allocation plan that the within-family per-option value sprint needs.

Budget: <= 6 candidates. With 3 interpretable profiles per family
(family_only_floor_v1 / option_value_v1 / conservative_option_value_v1) the budget is
exactly two families x three profiles. The 46G evidence selected Water + Diamond and
explicitly did NOT select Lightning (under the MIN_GAMES floor); that exclusion is
carried forward and recorded as considered-not-selected.

Writes data/experiments/pass46h_source_selection.{json,md}. No mutation, no upload, no
events, no candidate generation, no prod access. The public-reference gap is reported as
a *gap to close*, NEVER a parity / beating claim.
"""
from __future__ import annotations

import json
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from ptcg_activegraph.analysis import option_value_features as OV  # noqa: E402

EXP = REPO / "data" / "experiments"
SUBM = REPO / "data" / "submissions"
CARD_CSV = REPO / "data" / "cards" / "EN_Card_Data.csv"
G_SELECTION = EXP / "pass46g_source_selection.json"

MIN_GAMES = 8  # carried forward from 46F/46G stability floor
GOOD_FIT = {"midrange", "toolbox", "tempo", "control", "midrange_tempo",
            "midrange_toolbox", "midrange_control", "midrange_ramp"}
MARGINAL_FIT = {"burst", "combo", "otk", "search", "search_driven", "burst_combo"}
PROFILES = ("family_only_floor_v1", "option_value_v1", "conservative_option_value_v1")


def _is_public_ref(candidate_id: str) -> bool:
    cid = (candidate_id or "").lower()
    return cid.startswith("public_ref") or "public_ref" in cid


def _archetype_fit(archetype: str) -> str:
    a = (archetype or "").lower()
    if a in GOOD_FIT or any(k in a for k in ("midrange", "toolbox", "tempo", "control")):
        return "good"
    if a in MARGINAL_FIT or any(k in a for k in ("burst", "combo", "otk", "search")):
        return "marginal"
    if "spread" in a:
        return "poor"
    return "unknown"


def _read_deck(tarball_path: Path):
    with tarfile.open(tarball_path, "r:gz") as t:
        member = t.extractfile("deck.csv")
        if member is None:
            return []
        raw = member.read().decode("utf-8")
    ids = []
    for tok in raw.replace(",", " ").split():
        tok = tok.strip()
        if tok.isdigit():
            ids.append(int(tok))
    return ids


def _validate_source(entry: dict) -> dict:
    candidate_id = entry.get("candidate_id", "")
    archetype = entry.get("archetype", "")
    games = entry.get("games")
    status = entry.get("status", "")
    fit = _archetype_fit(archetype)
    checks = {
        "internal_not_public_ref": not _is_public_ref(candidate_id),
        "status_buildable": status not in (
            "retired", "quarantined", "special_pilot_only", "invalid", "held_probe"),
        "min_games_met": isinstance(games, int) and games >= MIN_GAMES,
        "archetype_fit_ok": fit in ("good", "marginal"),
    }
    return {"candidate_id": candidate_id, "family_id": entry.get("family_id"),
            "archetype": archetype, "archetype_fit": fit, "games": games,
            "wilson_low": entry.get("wilson_low"), "status": status,
            "tarball_path": entry.get("tarball_path"),
            "deck_fingerprint": entry.get("deck_fingerprint"),
            "checks": checks, "eligible": all(checks.values())}


def main() -> int:
    if not G_SELECTION.exists():
        print(f"FATAL: missing 46G evidence basis {G_SELECTION}", file=sys.stderr)
        return 2
    g = json.loads(G_SELECTION.read_text(encoding="utf-8"))
    build_set = g.get("build_set") or []

    sources = []
    role_maps = {}
    all_ok = True
    for entry in build_set:
        v = _validate_source(entry)
        tarball = SUBM / (entry.get("tarball_path") or "")
        deck = _read_deck(tarball) if tarball.exists() else []
        uniq = sorted(set(deck))
        rm = OV.build_deck_role_map(str(CARD_CSV), uniq)
        covered = sum(1 for cid in uniq if rm.get(str(cid)))
        token_counts = {}
        for toks in rm.values():
            for tok in toks:
                token_counts[tok] = token_counts.get(tok, 0) + 1
        v.update({
            "tarball_exists": tarball.exists(),
            "deck_size": len(deck),
            "deck_unique": len(uniq),
            "role_map_covered": covered,
            "role_map_coverage_frac": round(covered / len(uniq), 4) if uniq else 0.0,
            "role_token_distribution": dict(sorted(token_counts.items())),
            "profiles_allocated": list(PROFILES),
        })
        role_maps[entry.get("family_id")] = {
            "candidate_id": entry.get("candidate_id"),
            "deck_unique": len(uniq),
            "role_map": rm,
        }
        sources.append(v)
        if not v["eligible"]:
            all_ok = False

    n_candidates_planned = sum(len(PROFILES) for s in sources if s["eligible"])

    considered_not_selected = [{
        "family_id": "lightning",
        "reason": g.get("lightning_note",
                         "Lightning under the MIN_GAMES internal evidence floor; "
                         "not selected by the 46G evidence rule."),
        "carried_forward_from": "pass46g_source_selection",
    }]

    out = {
        "pass": "46H",
        "part": "B_source_selection_role_maps",
        "evidence_basis": "pass46g_source_selection",
        "local_only": True,
        "no_upload": True,
        "read_only": True,
        "min_games_floor": MIN_GAMES,
        "budget_max_candidates": 6,
        "profiles_per_family": list(PROFILES),
        "n_families_selected": sum(1 for s in sources if s["eligible"]),
        "n_candidates_planned": n_candidates_planned,
        "all_sources_eligible": all_ok,
        "sources": sources,
        "considered_not_selected": considered_not_selected,
        "public_reference_role": "benchmark_opponent_only",
        "public_reference_gap_note": (
            "Any gap to public references is reported as a GAP TO CLOSE for the internal "
            "source, NEVER a parity / beating claim. References are benchmark opponents "
            "only and are never a source / parent / candidate."),
        "honesty_notes": [
            "Role tokens are a COARSE deck-composition label from the local card CSV; they "
            "assert no card value, tempo, lethal, spread, or best-action.",
            "The shared cards/role_tags.tag_roles tagger mis-parses EN_Card_Data (reads the "
            "mostly-'n/a' Category column, tagging every card 'Basic Pokémon'); 46H instead "
            "uses the audited pilot_typed.compiler classifier (correct Stage/Type column).",
        ],
        "decision": "sources_reaffirmed" if all_ok else "source_validation_failed",
    }

    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46h_source_selection.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    # role maps in a separate artifact (consumed by Part D / Part F)
    (EXP / "pass46h_role_maps.json").write_text(
        json.dumps(role_maps, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# PASS 46H — Part B: Source Re-affirmation + Per-Deck Role Maps", "",
        f"- Evidence basis: `{out['evidence_basis']}` (LOCAL, read-only, no upload).",
        f"- Budget: <= {out['budget_max_candidates']} candidates; "
        f"profiles/family = {', '.join(PROFILES)}.",
        f"- Families selected: **{out['n_families_selected']}**; "
        f"candidates planned: **{out['n_candidates_planned']}**.",
        f"- All sources eligible: **{out['all_sources_eligible']}** "
        f"-> decision = `{out['decision']}`.", "",
        "## Re-validated sources", "",
        "| family | candidate | archetype (fit) | games | Wilson low | role-map cov | tokens |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in sources:
        toks = ", ".join(f"{k}:{v}" for k, v in s["role_token_distribution"].items())
        lines.append(
            f"| {s['family_id']} | `{s['candidate_id']}` | {s['archetype']} "
            f"({s['archetype_fit']}) | {s['games']} | {s['wilson_low']} | "
            f"{s['role_map_covered']}/{s['deck_unique']} | {toks} |")
    lines += ["", "## Considered, not selected", ""]
    for c in considered_not_selected:
        lines.append(f"- **{c['family_id']}**: {c['reason']}")
    lines += [
        "", "## Honesty", "",
        f"- {out['public_reference_gap_note']}",
    ]
    for n in out["honesty_notes"]:
        lines.append(f"- {n}")
    (EXP / "pass46h_source_selection.md").write_text("\n".join(lines) + "\n",
                                                     encoding="utf-8")

    print(f"OK: {out['n_families_selected']} families, "
          f"{out['n_candidates_planned']} candidates planned, "
          f"all_eligible={all_ok}, decision={out['decision']}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
