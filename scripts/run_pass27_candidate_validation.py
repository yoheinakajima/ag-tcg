#!/usr/bin/env python3
"""Pass 27 (Part G) — aggregate candidate validation / league eligibility. LOCAL.

Composes the single eligibility verdict per portfolio candidate from the
independent gates, re-running the cheap stdlib validators in-process and reading
the smoke report:

  * tarball validator      (scripts/validate_candidate_tarball.py)
  * entrypoint validator   (scripts/validate_candidate_entrypoint.py)
  * deck registry legality (data/experiments/pass27_portfolio_registry.json)
  * live cabt smoke        (data/experiments/pass27_live_smoke.json)

ELIGIBILITY (validity bar, NOT promotion):
    tarball_valid AND entrypoint_valid AND deck_legal AND smoke_clean.

LEAGUE-ELIGIBLE = eligible AND NOT blocked_from_league. Durant is built and may
even smoke clean, but it is blocked_from_league by design (deckout win condition
the generic pilot cannot pilot), so it is eligible-as-artifact yet NOT
league-eligible.

Run the deck validator and smoke first. Writes
data/experiments/pass27_candidate_validation.{json,md}. Exit non-zero iff any
buildable candidate is ineligible. No upload, no root edits.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

import yaml  # type: ignore

EXP = REPO / "data" / "experiments"
CAND = REPO / "data" / "submissions" / "candidates_pass27"
REGISTRY = REPO / "experiments" / "pass27_portfolio_decks.yaml"


def _load_validator(fname: str):
    spec = importlib.util.spec_from_file_location(
        fname.replace(".py", ""), REPO / "scripts" / fname)
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    tarball_v = _load_validator("validate_candidate_tarball.py")
    entry_v = _load_validator("validate_candidate_entrypoint.py")

    reg = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    decks = reg.get("decks") or {}
    legality = _read_json(EXP / "pass27_portfolio_registry.json") or {}
    legal_by_cid = {d.get("candidate_id"): d.get("valid")
                    for d in legality.get("decks", [])}
    smoke = _read_json(EXP / "pass27_live_smoke.json") or {}
    smoke_cands = smoke.get("results") or {}

    rows = []
    for _key, spec in decks.items():
        if not spec.get("buildable"):
            continue
        cid = spec["candidate_id"]
        blocked = bool(spec.get("blocked_from_league"))
        tar = CAND / f"{cid}.tar.gz"
        tb_ok = tar.exists() and tarball_v.validate(str(tar)) == 0
        ep_ok = tar.exists() and entry_v.validate(str(tar)) == 0
        legal = bool(legal_by_cid.get(cid))

        sm = smoke_cands.get(cid, {})
        smoke_clean = bool(sm.get("clean"))
        smoke_bad = sm.get("all_bad_statuses") or []

        eligible = tb_ok and ep_ok and legal and smoke_clean
        league_eligible = eligible and not blocked
        rows.append({
            "candidate_id": cid,
            "family": spec.get("family"),
            "archetype": spec.get("archetype"),
            "tarball": str(tar.relative_to(REPO)),
            "tarball_valid": tb_ok,
            "entrypoint_valid": ep_ok,
            "deck_legal": legal,
            "smoke_clean": smoke_clean,
            "smoke_bad_statuses": smoke_bad,
            "blocked_from_league": blocked,
            "block_reason": (spec.get("block_reason") or "").strip() or None,
            "eligible": eligible,
            "league_eligible": league_eligible,
        })

    all_eligible = all(r["eligible"] for r in rows)
    league_eligible = [r["candidate_id"] for r in rows if r["league_eligible"]]
    report = {
        "pass": "27", "part": "G", "local_only": True, "no_upload": True,
        "upload_performed": False, "is_kaggle_leaderboard": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "eligibility_rule": ("tarball_valid AND entrypoint_valid AND deck_legal "
                             "AND smoke_clean"),
        "league_rule": "eligible AND NOT blocked_from_league",
        "note": ("Eligibility is a SAFETY/VALIDITY bar for inclusion in the Part-I "
                 "internal league, NOT a promotion or upload decision. All numbers "
                 "local/surrogate; never equal Kaggle."),
        "all_eligible": all_eligible,
        "league_eligible": league_eligible,
        "candidates": rows,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass27_candidate_validation.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")

    cols = ["tarball_valid", "entrypoint_valid", "deck_legal", "smoke_clean",
            "eligible", "blocked_from_league", "league_eligible"]
    L = ["# Pass 27 — Candidate validation / eligibility (Part G)", "",
         "> LOCAL ONLY — eligibility is a validity/safety bar, NOT promotion. "
         "NOT a Kaggle leaderboard.", "",
         f"- generated: {report['generated_at']}",
         f"- eligibility rule: `{report['eligibility_rule']}`",
         f"- league rule: `{report['league_rule']}`",
         f"- all eligible: **{all_eligible}**",
         f"- league-eligible: **{league_eligible}**", "",
         "| candidate | " + " | ".join(c.replace('_', ' ') for c in cols) + " |",
         "|---|" + "|".join(["---"] * len(cols)) + "|"]
    for r in rows:
        L.append("| " + r["candidate_id"] + " | "
                 + " | ".join(("yes" if r[c] else "NO") for c in cols) + " |")
    for r in rows:
        if r["blocked_from_league"]:
            L += ["", f"### League-blocked — `{r['candidate_id']}`",
                  r["block_reason"] or ""]
    L += ["", report["note"], ""]
    (EXP / "pass27_candidate_validation.md").write_text("\n".join(L), encoding="utf-8")

    for r in rows:
        print(f"{r['candidate_id']:38} eligible={r['eligible']} "
              f"league_eligible={r['league_eligible']} "
              f"(tb={r['tarball_valid']} ep={r['entrypoint_valid']} "
              f"legal={r['deck_legal']} smoke={r['smoke_clean']})")
    print(f"\nall_eligible={all_eligible} league_eligible={league_eligible}")
    return 0 if all_eligible else 1


if __name__ == "__main__":
    raise SystemExit(main())
