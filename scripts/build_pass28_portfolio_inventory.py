#!/usr/bin/env python3
"""Pass 28 (Part C) — read-only portfolio inventory. LOCAL / READ-ONLY.

Consolidates the Pass-27 candidate validation, candidate manifest, portfolio
decks spec and internal-league rankings into one inventory per deck:
candidate_id, family, archetype, tarball, playbook, validation flags, smoke
status, internal-league eligibility + performance, and warnings. NEVER mutates
any tarball, deck, or root file. Writes
data/experiments/pass28_portfolio_inventory.{json,md}.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
VALID = EXP / "pass27_candidate_validation.json"
MANIFEST = EXP / "pass27_candidate_manifest.json"
RANK = EXP / "pass27_portfolio_rankings.json"
DECKS = REPO / "experiments" / "pass27_portfolio_decks.yaml"
OUT_JSON = EXP / "pass28_portfolio_inventory.json"
OUT_MD = EXP / "pass28_portfolio_inventory.md"


def main() -> int:
    valid = json.loads(VALID.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rank = json.loads(RANK.read_text(encoding="utf-8"))
    decks = yaml.safe_load(DECKS.read_text(encoding="utf-8"))

    by_cand_deck = {d["candidate_id"]: {**d, "deck_key": k}
                    for k, d in decks.get("decks", {}).items()
                    if isinstance(d, dict) and d.get("candidate_id")}
    by_cand_build = {c["candidate_id"]: c
                     for c in manifest.get("candidates_built", [])}
    by_cand_rank = {s["id"]: s for s in rank.get("standings", [])}

    league_eligible = set(valid.get("league_eligible", []))
    items = []
    for c in valid.get("candidates", []):
        cid = c["candidate_id"]
        d = by_cand_deck.get(cid, {})
        b = by_cand_build.get(cid, {})
        st = by_cand_rank.get(cid)
        warnings = []
        if c.get("blocked_from_league"):
            warnings.append(f"blocked_from_league: {c.get('block_reason')}")
        if not c.get("deck_legal"):
            warnings.append("deck_legal=false")
        if not c.get("smoke_clean"):
            warnings.append(f"smoke_bad_statuses={c.get('smoke_bad_statuses')}")
        if cid not in league_eligible:
            warnings.append("not in internal-league eligible set")
        if st is None:
            warnings.append("no internal-league standing (excluded / not run)")

        items.append({
            "candidate_id": cid,
            "family": c.get("family") or d.get("family"),
            "archetype": c.get("archetype") or d.get("archetype"),
            "role": d.get("role") or b.get("role"),
            "tarball": c.get("tarball"),
            "playbook": d.get("playbook"),
            "runtime_contexts": d.get("runtime_contexts"),
            "validation": {
                "tarball_valid": c.get("tarball_valid"),
                "entrypoint_valid": c.get("entrypoint_valid"),
                "deck_legal": c.get("deck_legal"),
                "eligible": c.get("eligible"),
            },
            "smoke": {
                "smoke_clean": c.get("smoke_clean"),
                "smoke_bad_statuses": c.get("smoke_bad_statuses"),
            },
            "league": {
                "league_eligible": cid in league_eligible,
                "blocked_from_league": c.get("blocked_from_league"),
                "block_reason": c.get("block_reason"),
                "games": st.get("games") if st else None,
                "record": (f"{st['wins']}-{st['losses']}-{st['draws']}"
                           if st else None),
                "adj_win_rate": st.get("adj_win_rate") if st else None,
            },
            "warnings": warnings,
        })

    # Stable order: by internal-league win rate desc, then id (None last).
    items.sort(key=lambda it: (-(it["league"]["adj_win_rate"] or -1),
                               it["candidate_id"]))

    out = {
        "pass": "28", "part": "C",
        "local_only": True, "no_upload": True, "upload_performed": False,
        "is_kaggle_leaderboard": False,
        "note": ("Read-only inventory. Internal-league performance is OUR-vs-OUR "
                 "generic-pilot measurement, NOT the Kaggle leaderboard. No tarball, "
                 "deck, or root file is mutated by this pass."),
        "source": {
            "validation": str(VALID.relative_to(REPO)),
            "manifest": str(MANIFEST.relative_to(REPO)),
            "rankings": str(RANK.relative_to(REPO)),
            "decks": str(DECKS.relative_to(REPO)),
        },
        "base_from": manifest.get("base_from"),
        "count": len(items),
        "decks": items,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

    L = ["# Pass 28 — Portfolio Inventory (Part C, read-only)", "",
         "> Internal-league performance is **our decks vs our decks** under the same "
         "generic core pilot — NOT a Kaggle leaderboard. No tarball/deck/root file is "
         "mutated.", "",
         f"- base pilot: `{manifest.get('base_from')}`", f"- decks: {len(items)}", "",
         "| candidate_id | family | archetype | role | league | record | adj_wr | "
         "smoke | warnings |", "|---|---|---|---|---|---|---|---|---|"]
    for it in items:
        lg = it["league"]
        L.append(
            f"| {it['candidate_id']} | {it['family']} | {it['archetype']} | "
            f"{it['role']} | {lg['league_eligible']} | {lg['record']} | "
            f"{lg['adj_win_rate']} | {it['smoke']['smoke_clean']} | "
            f"{'; '.join(it['warnings']) or '—'} |")
    L += ["", "## Playbooks & runtime contexts", "",
          "| candidate_id | playbook | runtime_contexts |", "|---|---|---|"]
    for it in items:
        L.append(f"| {it['candidate_id']} | {it['playbook']} | "
                 f"{it['runtime_contexts']} |")
    L += ["", f"- {out['note']}", ""]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")

    print(f"inventory: {len(items)} decks -> {OUT_JSON.relative_to(REPO)}")
    for it in items:
        print(f"  {it['candidate_id']:38s} wr={it['league']['adj_win_rate']} "
              f"warnings={len(it['warnings'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
