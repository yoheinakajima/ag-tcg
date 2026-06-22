#!/usr/bin/env python3
"""PASS 46G (Part B) — deterministic 2-3 internal source-FAMILY selection.

LOCAL / read-only. Generalises the Pass-46F single-source rule to pick a SMALL set
of internal source families (and the best internal source within each) for the
multi-profile turn-planner sprint, using a pre-registered, fully deterministic
evidence rule:

  1. Internal pool ONLY — every public reference id is excluded up front
     (zero-leakage: a public reference is NEVER a source/parent/candidate).
  2. Exclude statuses that must never seed new work:
     retired / quarantined / special_pilot_only / invalid, AND held_probe
     (a held probe stays held; never re-parented).
  3. Require a minimum internal evidence floor (>= MIN_GAMES games) so a source is
     "stable, with enough internal games" (the FIRST charter Part-B criterion).
  4. ARCHETYPE FIT — "simple enough for turn planning". The 46G turn-planner scores
     COARSE ACTION FAMILIES conditioned on observable phase/role and makes NO
     spread / targeting / lethal claims. So a source's archetype is classified:
       * midrange / toolbox / tempo / control  -> GOOD  (the planner's wheelhouse:
         steady develop -> attach -> attack)
       * spread                                -> POOR  (win-con = distribute damage
         across targets, which the planner cannot represent honestly)
       * burst / combo / otk                   -> MARGINAL (wants one big setup turn)
       * search-driven                         -> MARGINAL (search-driven parent;
         the candidate hot-path runs NO online search)
     Only GOOD-fit sources are eligible to be SELECTED; MARGINAL/POOR are recorded
     with reasons. (If fewer than MIN_FAMILIES GOOD families exist, the rule widens
     to admit MARGINAL families, still excluding POOR/spread.)
  5. Rank GOOD survivors by (Wilson lower bound desc, games desc, adj win-rate desc,
     candidate_id asc); take the best source PER family.
  6. SHORTLIST the top SHORTLIST_FAMILIES families; the top BUILD_FAMILIES of those
     are the build set for Part E (the rest are documented expansion families).

Writes data/experiments/pass46g_source_selection.{json,md}. No mutation, no upload,
no events, no candidate generation. The public-reference gap is reported as a *gap to
close*, NEVER as a parity or beating claim.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament import promotion  # noqa: E402
from ptcg_activegraph.tournament.pool import (  # noqa: E402
    CandidatePool, NEVER_SCHEDULE, HELD_PROBE,
)

EXP = REPO / "data" / "experiments"
PROJ = REPO / "data" / "tournament" / "projections"
SUBM = REPO / "data" / "submissions"

MIN_GAMES = 8  # documented "enough internal games" stability floor (== 46F)
MIN_FAMILIES = 2
SHORTLIST_FAMILIES = 3
BUILD_FAMILIES = 2
EXCLUDED_STATUSES = set(NEVER_SCHEDULE) | {HELD_PROBE}

# Deterministic archetype classifier by id/family name tokens. Order matters:
# POOR/MARGINAL tokens are checked before GOOD so a "spread"/"burst" source is never
# mislabelled GOOD on an incidental token.
ARCHETYPE_RULES = [
    ("spread", "spread", "poor",
     "win-con distributes damage across targets; the planner makes NO spread claims"),
    ("search_only", "search_driven", "marginal",
     "search-driven parent; the candidate hot-path runs no online search"),
    ("searchonly", "search_driven", "marginal",
     "search-driven parent; the candidate hot-path runs no online search"),
    ("otk", "burst_combo", "marginal",
     "one-big-turn archetype; less suited to incremental turn-planning"),
    ("burst", "burst_combo", "marginal",
     "one-big-turn archetype; less suited to incremental turn-planning"),
    ("combo", "burst_combo", "marginal",
     "one-big-turn archetype; less suited to incremental turn-planning"),
    ("toolbox", "midrange_toolbox", "good",
     "toolbox midrange: steady develop/attach/attack — planner wheelhouse"),
    ("anti_disruption", "midrange_tempo", "good",
     "tempo/pivot midrange: steady develop/attach/attack — planner wheelhouse"),
    ("pivot", "midrange_tempo", "good",
     "tempo/pivot midrange: steady develop/attach/attack — planner wheelhouse"),
    ("tank", "midrange_control", "good",
     "control/tank midrange: steady develop/attach/attack — planner wheelhouse"),
    ("ramp", "midrange_ramp", "good",
     "ramp midrange: steady develop/attach/attack — planner wheelhouse"),
    ("control", "midrange_control", "good",
     "control midrange: steady develop/attach/attack — planner wheelhouse"),
]
FIT_RANK = {"good": 0, "marginal": 1, "poor": 2}


def classify_archetype(candidate_id: str, family_id: str) -> dict:
    hay = f"{candidate_id} {family_id}".lower()
    for token, archetype, fit, why in ARCHETYPE_RULES:
        if token in hay:
            return {"archetype": archetype, "fit": fit, "reason": why,
                    "matched_token": token}
    # Unknown archetype: treat as GOOD-eligible (do not penalise the unknown), but
    # flagged so the report is honest about the inferred classification.
    return {"archetype": "unknown", "fit": "good",
            "reason": "no archetype token matched; treated as turn-plannable midrange",
            "matched_token": None}


def _load_rankings() -> dict[str, dict]:
    p = PROJ / "rankings.json"
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    rows = d.get("rankings") if isinstance(d, dict) else d
    out: dict[str, dict] = {}
    for r in rows or []:
        cid = r.get("candidate_id")
        if cid:
            out[cid] = r
    return out


def _ref_gap(cid: str) -> dict:
    """Aggregate a source's record vs public references (a GAP TO CLOSE, not a claim)."""
    p = PROJ / "benchmark_results.json"
    out = {"games": 0, "our_wins": 0, "reference_wins": 0, "draws": 0,
           "invalid": 0, "by_reference": [], "gap_exists": None}
    if not p.exists():
        return out
    d = json.loads(p.read_text(encoding="utf-8"))
    for row in d.get("by_pair") or []:
        if row.get("our_candidate") != cid:
            continue
        for k in ("games", "our_wins", "reference_wins", "draws", "invalid"):
            out[k] += int(row.get(k) or 0)
        out["by_reference"].append({
            "reference_id": row.get("reference_id"),
            "games": row.get("games"), "our_wins": row.get("our_wins"),
            "reference_wins": row.get("reference_wins"),
            "our_decisive_win_rate": row.get("our_decisive_win_rate"),
        })
    # "gap exists" = there is room to improve vs references (we have NOT cleanly
    # out-won every reference). None when there is no benchmark evidence at all.
    if out["games"] > 0:
        out["gap_exists"] = not (out["reference_wins"] == 0 and out["draws"] == 0)
    return out


def _rank_key(r: dict) -> tuple:
    return (-(r["wilson_low"] or 0.0), -(r["games"] or 0),
            -(r["adj_win_rate"] or 0.0), r["candidate_id"])


def run_source_selection() -> dict:
    EXP.mkdir(parents=True, exist_ok=True)
    pool = CandidatePool.load()
    rankings = _load_rankings()
    ref_ids = set(promotion.load_reference_ids())

    considered = []
    good_eligible = []      # status ok + games>=floor + archetype GOOD
    marginal_eligible = []  # status ok + games>=floor + archetype MARGINAL
    for c in sorted(pool.candidates, key=lambda x: x.candidate_id):
        rk = rankings.get(c.candidate_id, {})
        games = int(rk.get("games") or 0)
        arc = classify_archetype(c.candidate_id, c.family_id)
        reasons = []
        if c.candidate_id in ref_ids:
            reasons.append("public_reference_excluded")
        if c.status in EXCLUDED_STATUSES:
            reasons.append(f"status_excluded:{c.status}")
        if games < MIN_GAMES:
            reasons.append(f"insufficient_games:{games}<{MIN_GAMES}")
        if arc["fit"] == "poor":
            reasons.append(f"archetype_poor_fit:{arc['archetype']}")
        rec = {
            "candidate_id": c.candidate_id, "family_id": c.family_id,
            "status": c.status, "games": games,
            "wins": int(rk.get("wins") or 0), "losses": int(rk.get("losses") or 0),
            "draws": int(rk.get("draws") or 0),
            "adj_win_rate": rk.get("adj_win_rate"),
            "wilson_low": rk.get("wilson_low"), "wilson_high": rk.get("wilson_high"),
            "archetype": arc["archetype"], "archetype_fit": arc["fit"],
            "archetype_reason": arc["reason"],
            "deck_fingerprint": c.deck_fingerprint,
            "main_fingerprint": c.main_fingerprint,
            "tarball_path": c.tarball_path,
            "eligible": not reasons, "exclusion_reasons": reasons,
        }
        considered.append(rec)
        if not reasons and arc["fit"] == "good":
            good_eligible.append(rec)
        elif (c.candidate_id not in ref_ids and c.status not in EXCLUDED_STATUSES
              and games >= MIN_GAMES and arc["fit"] == "marginal"):
            marginal_eligible.append(rec)

    # Best source per family within GOOD; widen to MARGINAL only if too few GOOD.
    def _best_per_family(rows):
        by_fam: dict[str, dict] = {}
        for r in sorted(rows, key=_rank_key):
            fam = r["family_id"]
            if fam not in by_fam:
                by_fam[fam] = r
        return by_fam

    good_by_fam = _best_per_family(good_eligible)
    pool_used = "good_fit_only"
    chosen_by_fam = dict(good_by_fam)
    if len(chosen_by_fam) < MIN_FAMILIES:
        # widen: admit marginal-fit families (still never POOR/spread)
        for fam, r in _best_per_family(marginal_eligible).items():
            chosen_by_fam.setdefault(fam, r)
        pool_used = "good_plus_marginal_fit"

    family_ranked = sorted(chosen_by_fam.values(), key=_rank_key)
    shortlist = family_ranked[:SHORTLIST_FAMILIES]
    build_set = family_ranked[:BUILD_FAMILIES]

    decision = ("families_selected" if len(build_set) >= MIN_FAMILIES
                else "insufficient_eligible_families")

    # attach ref gap + tarball existence to shortlisted sources
    for r in shortlist:
        tb = SUBM / r["tarball_path"] if r["tarball_path"] else None
        r["tarball_exists"] = bool(tb and tb.exists())
        r["public_reference_gap"] = _ref_gap(r["candidate_id"])

    data = {
        "pass": "46g", "part": "B", "read_only": True, "no_upload": True,
        "local_only": True, "production_mutated": False, "candidate_generated": False,
        "selection_rule": {
            "internal_pool_only_refs_excluded": True,
            "excluded_statuses": sorted(EXCLUDED_STATUSES),
            "min_games_floor": MIN_GAMES,
            "archetype_fit": "GOOD(midrange/toolbox/tempo/control) selectable; "
            "MARGINAL(burst/combo/otk/search) only if too few GOOD; "
            "POOR(spread) never selectable — planner makes no spread claims",
            "ranking": "(wilson_low desc, games desc, adj_win_rate desc, id asc)",
            "min_families": MIN_FAMILIES, "shortlist_families": SHORTLIST_FAMILIES,
            "build_families": BUILD_FAMILIES,
            "candidate_pool_used": pool_used,
        },
        "reference_ids_excluded": sorted(ref_ids),
        "n_candidates_considered": len(considered),
        "n_good_eligible": len(good_eligible),
        "n_marginal_eligible": len(marginal_eligible),
        "decision": decision,
        "selected_families_shortlist": [
            {k: r[k] for k in (
                "candidate_id", "family_id", "status", "games", "wins", "losses",
                "draws", "adj_win_rate", "wilson_low", "archetype", "archetype_fit",
                "deck_fingerprint", "main_fingerprint", "tarball_path",
                "tarball_exists", "public_reference_gap")}
            for r in shortlist],
        "build_set": [
            {"family_id": r["family_id"], "candidate_id": r["candidate_id"],
             "status": r["status"], "games": r["games"],
             "wilson_low": r["wilson_low"], "archetype": r["archetype"],
             "deck_fingerprint": r["deck_fingerprint"],
             "tarball_path": r["tarball_path"]}
            for r in build_set],
        "expansion_families": [r["family_id"] for r in shortlist[BUILD_FAMILIES:]],
        "considered": considered,
        "public_reference_gap_note": "Reported as a GAP TO CLOSE for the internal "
        "source, NOT a parity/beating claim. References are benchmark opponents only.",
        "lightning_note": "Lightning was NOT selected: its best internal source has "
        "fewer than the MIN_GAMES floor of internal games (under-evidenced), and its "
        "other source is on probation with 0 games. Evidence selects Water + Diamond.",
    }
    (EXP / "pass46g_source_selection.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        "# Pass 46G — Part B: deterministic 2-3 internal source-family selection", "",
        "> LOCAL, read-only. Public references are excluded up front and never become "
        "a source/parent/candidate. No mutation, no upload, no generation, no events.",
        "", "## Pre-registered rule",
        f"1. internal pool only (excluded refs: {len(ref_ids)})",
        f"2. exclude statuses: {sorted(EXCLUDED_STATUSES)}",
        f"3. min internal games floor = {MIN_GAMES} (stability)",
        "4. archetype fit (simple enough for turn planning): GOOD "
        "(midrange/toolbox/tempo/control) selectable; MARGINAL (burst/combo/otk/"
        "search) only if too few GOOD; POOR (spread) never — planner makes NO spread "
        "claims",
        "5. rank by (wilson_low desc, games desc, adj_win_rate desc, id asc); "
        "best source per family",
        f"6. shortlist top {SHORTLIST_FAMILIES}; build top {BUILD_FAMILIES}", "",
        f"## Decision: **{decision}** (pool used: {pool_used})", "",
        "## Build set (source x profile candidates assembled in Part E)",
    ]
    for r in build_set:
        md.append(
            f"- **{r['family_id']}** -> `{r['candidate_id']}` "
            f"({r['status']}, {r['archetype']}, {r['games']} games, "
            f"wilson_low {r['wilson_low']})")
    if data["expansion_families"]:
        md.append("")
        md.append(f"_expansion families (shortlisted, not built by default): "
                  f"{', '.join(data['expansion_families'])}_")
    md += ["", "## Shortlist (ranked, with public-reference gap)"]
    for r in shortlist:
        g = r.get("public_reference_gap") or {}
        md.append(
            f"- `{r['candidate_id']}` ({r['family_id']}, {r['archetype']}/"
            f"{r['archetype_fit']}) — wilson_low {r['wilson_low']}, games "
            f"{r['games']}, tarball_present {r.get('tarball_exists')}; "
            f"ref-gap exists: {g.get('gap_exists')} "
            f"({g.get('our_wins')}-{g.get('reference_wins')}-{g.get('draws')} over "
            f"{g.get('games')} ref games)")
    md += ["", "## Excluded / not-selected (with reasons)"]
    for r in sorted(considered, key=lambda x: x["candidate_id"]):
        if r in build_set:
            continue
        why = ", ".join(r["exclusion_reasons"]) if r["exclusion_reasons"] else (
            f"not_top_{BUILD_FAMILIES}_family" if r["archetype_fit"] == "good"
            else f"archetype_{r['archetype_fit']}_fit:{r['archetype']}")
        md.append(f"- `{r['candidate_id']}` ({r['family_id']}) — {why}")
    md += ["", f"> {data['lightning_note']}"]
    (EXP / "pass46g_source_selection.md").write_text("\n".join(md) + "\n",
                                                     encoding="utf-8")

    print(json.dumps({
        "decision": decision, "pool_used": pool_used,
        "build_set": [(r["family_id"], r["candidate_id"]) for r in build_set],
        "shortlist": [(r["family_id"], r["candidate_id"]) for r in shortlist],
        "expansion_families": data["expansion_families"],
        "n_good_eligible": len(good_eligible),
    }, indent=2))
    return data


if __name__ == "__main__":
    out = run_source_selection()
    ok = (out["decision"] == "families_selected"
          and all(r.get("tarball_exists") for r in out["selected_families_shortlist"]
                  [:BUILD_FAMILIES]))
    raise SystemExit(0 if ok else 1)
