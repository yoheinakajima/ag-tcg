#!/usr/bin/env python3
"""PASS 46F (Part B) — deterministic source/parent selection for the pilot.

LOCAL / read-only. Picks the ONE internal candidate whose deck + lineage the
search-calibrated turn-planner pilot will be built on, using a pre-registered,
fully deterministic evidence rule:

  1. Internal pool ONLY — every public reference id is excluded up front
     (zero-leakage: a public reference is NEVER a source/parent/candidate).
  2. Exclude statuses that must never seed new work:
     retired / quarantined / special_pilot_only / invalid, AND held_probe
     (a held probe stays held; never re-parented).
  3. Restrict to the target family ``water`` — the internal line with the most
     evaluation games and the clearest public-reference gap; improving its turn
     play is this pass's stated goal.
  4. Require a minimum internal evidence floor (>= MIN_GAMES games) so the source
     is "stable, with enough internal games".
  5. Rank survivors by (Wilson lower bound desc, games desc, adj win-rate desc,
     candidate_id asc) and take the top — deterministic, tie-broken by id.

Writes data/experiments/pass46f_source_selection.{json,md}. No mutation, no
upload, no events. The public-reference gap is reported as a *gap to close*,
NEVER as a parity or beating claim.
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

TARGET_FAMILY = "water"
MIN_GAMES = 8  # documented "enough internal games" floor
EXCLUDED_STATUSES = set(NEVER_SCHEDULE) | {HELD_PROBE}


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
    """Aggregate the source's record vs public references (gap to close)."""
    p = PROJ / "benchmark_results.json"
    out = {"games": 0, "our_wins": 0, "reference_wins": 0, "draws": 0,
           "invalid": 0, "by_reference": []}
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
    return out


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    pool = CandidatePool.load()
    rankings = _load_rankings()
    ref_ids = set(promotion.load_reference_ids())

    considered = []
    eligible = []
    for c in sorted(pool.candidates, key=lambda x: x.candidate_id):
        rk = rankings.get(c.candidate_id, {})
        games = int(rk.get("games") or 0)
        reasons = []
        if c.candidate_id in ref_ids:
            reasons.append("public_reference_excluded")
        if c.status in EXCLUDED_STATUSES:
            reasons.append(f"status_excluded:{c.status}")
        if c.family_id != TARGET_FAMILY:
            reasons.append(f"family_not_{TARGET_FAMILY}:{c.family_id}")
        if games < MIN_GAMES:
            reasons.append(f"insufficient_games:{games}<{MIN_GAMES}")
        rec = {
            "candidate_id": c.candidate_id, "family_id": c.family_id,
            "status": c.status, "games": games,
            "wins": int(rk.get("wins") or 0), "losses": int(rk.get("losses") or 0),
            "draws": int(rk.get("draws") or 0),
            "adj_win_rate": rk.get("adj_win_rate"),
            "wilson_low": rk.get("wilson_low"), "wilson_high": rk.get("wilson_high"),
            "deck_fingerprint": c.deck_fingerprint,
            "main_fingerprint": c.main_fingerprint,
            "tarball_path": c.tarball_path,
            "eligible": not reasons, "exclusion_reasons": reasons,
        }
        considered.append(rec)
        if not reasons:
            eligible.append(rec)

    eligible.sort(key=lambda r: (
        -(r["wilson_low"] or 0.0), -(r["games"] or 0),
        -(r["adj_win_rate"] or 0.0), r["candidate_id"]))

    selected = eligible[0] if eligible else None
    decision = "source_selected" if selected else "no_eligible_source"

    src_tarball_ok = None
    ref_gap = None
    if selected:
        tb = SUBM / selected["tarball_path"]
        src_tarball_ok = tb.exists()
        ref_gap = _ref_gap(selected["candidate_id"])

    data = {
        "pass": "46f", "part": "B", "read_only": True, "no_upload": True,
        "local_only": True, "production_mutated": False,
        "selection_rule": {
            "internal_pool_only_refs_excluded": True,
            "excluded_statuses": sorted(EXCLUDED_STATUSES),
            "target_family": TARGET_FAMILY, "min_games_floor": MIN_GAMES,
            "ranking": "(wilson_low desc, games desc, adj_win_rate desc, id asc)",
        },
        "reference_ids_excluded": sorted(ref_ids),
        "n_candidates_considered": len(considered),
        "n_eligible": len(eligible),
        "eligible_ranked": eligible,
        "considered": considered,
        "selected_source": selected,
        "selected_tarball_exists": src_tarball_ok,
        "public_reference_gap": ref_gap,
        "public_reference_gap_note": "Reported as a GAP TO CLOSE for the internal "
        "source, NOT a parity/beating claim. References are benchmark opponents only.",
        "decision": decision,
        "parent_candidate_id": selected["candidate_id"] if selected else None,
        "deck_fingerprint_to_copy": selected["deck_fingerprint"] if selected else None,
    }
    (EXP / "pass46f_source_selection.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        "# Pass 46F — Part B: deterministic source / parent selection", "",
        "> LOCAL, read-only. Public references are excluded up front and never "
        "become a source/parent/candidate. No mutation, no upload, no events.", "",
        "## Pre-registered rule",
        f"1. internal pool only (excluded refs: {len(ref_ids)})",
        f"2. exclude statuses: {sorted(EXCLUDED_STATUSES)}",
        f"3. target family = `{TARGET_FAMILY}`",
        f"4. min internal games floor = {MIN_GAMES}",
        "5. rank by (wilson_low desc, games desc, adj_win_rate desc, id asc)", "",
        f"## Decision: **{decision}**",
    ]
    if selected:
        md += [
            f"- **selected source / parent**: `{selected['candidate_id']}` "
            f"({selected['status']}, {selected['family_id']})",
            f"- internal record: {selected['wins']}-{selected['losses']}-"
            f"{selected['draws']} over {selected['games']} games "
            f"(adj_win_rate {selected['adj_win_rate']}, wilson_low "
            f"{selected['wilson_low']})",
            f"- deck_fingerprint (byte-copied to candidate): "
            f"`{selected['deck_fingerprint']}`",
            f"- source tarball present: {src_tarball_ok}",
        ]
        if ref_gap:
            md.append(
                f"- public-reference gap (to close, NOT a claim): "
                f"{ref_gap['our_wins']} wins / {ref_gap['games']} games vs "
                f"{len(ref_gap['by_reference'])} references")
    md += ["", "## Eligible (ranked)"]
    for r in eligible:
        md.append(f"- `{r['candidate_id']}` — wilson_low {r['wilson_low']}, "
                  f"games {r['games']}, win_rate {r['adj_win_rate']}")
    md += ["", "## Excluded (sample)"]
    for r in considered:
        if not r["eligible"]:
            md.append(f"- `{r['candidate_id']}` — {', '.join(r['exclusion_reasons'])}")
    (EXP / "pass46f_source_selection.md").write_text("\n".join(md) + "\n",
                                                     encoding="utf-8")

    print(json.dumps({"decision": decision,
                      "selected": selected["candidate_id"] if selected else None,
                      "n_eligible": len(eligible),
                      "tarball_ok": src_tarball_ok}, indent=2))
    return 0 if selected and src_tarball_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
