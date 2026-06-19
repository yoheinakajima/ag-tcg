#!/usr/bin/env python3
"""Pass 30 (Part F) — aggregate candidate validation / tournament eligibility. LOCAL.

Composes the single eligibility verdict per portfolio candidate from independent
gates, re-running the cheap stdlib validators in-process and reading the smoke
report:

  * tarball validator      (scripts/validate_candidate_tarball.py)
  * entrypoint validator   (scripts/validate_candidate_entrypoint.py)
  * deck legality          (computed here vs data/cards/EN_Card_Data.csv:
                            exactly 60 cards, non-basic-energy <= 4, no invented ids)
  * live cabt smoke        (data/experiments/pass30_live_smoke.json)

ELIGIBILITY (validity bar, NOT promotion):
    tarball_valid AND entrypoint_valid AND deck_legal AND smoke_clean.

TOURNAMENT-ELIGIBLE = eligible AND NOT blocked_from_league. Durant is built and
smoke-tested but blocked_from_league by design (deckout win condition the generic
pilot cannot pilot), so it is eligible-as-artifact yet NOT tournament-eligible.

Writes data/experiments/pass30_candidate_validation.{json,md}. Exit non-zero iff
any non-blocked candidate is ineligible. No upload, no root edits.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

import yaml  # type: ignore  # noqa: E402

EXP = REPO / "data" / "experiments"
CAND = REPO / "data" / "submissions" / "candidates_pass30"
REGISTRY = REPO / "experiments" / "pass30_existing_portfolio.yaml"
CARD_DB = REPO / "data" / "cards" / "EN_Card_Data.csv"


def _load_validator(fname: str):
    spec = importlib.util.spec_from_file_location(
        fname.replace(".py", ""), REPO / "scripts" / fname)
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _load_card_ids() -> tuple[set[int], set[int]]:
    all_ids: set[int] = set()
    basic_energy: set[int] = set()
    with CARD_DB.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                cid = int(row["Card ID"].strip())
            except (KeyError, ValueError):
                continue
            all_ids.add(cid)
            if (row.get("Stage (Pokémon)/Type (Energy and Trainer)") or "").strip() \
                    == "Basic Energy":
                basic_energy.add(cid)
    return all_ids, basic_energy


def _deck_legal(tar: Path, all_ids: set[int], basic_energy: set[int]) -> tuple[bool, str]:
    if not tar.exists():
        return False, "tarball missing"
    try:
        with tarfile.open(tar, "r:gz") as t:
            m = t.extractfile("deck.csv")
            if m is None:
                return False, "no deck.csv"
            ids = [int(x) for x in m.read().decode("utf-8").splitlines() if x.strip()]
    except Exception as exc:  # noqa: BLE001
        return False, f"read error: {exc!r}"
    if len(ids) != 60:
        return False, f"deck has {len(ids)} cards (need 60)"
    counts: dict[int, int] = {}
    for cid in ids:
        if cid not in all_ids:
            return False, f"invented id {cid}"
        counts[cid] = counts.get(cid, 0) + 1
    for cid, n in counts.items():
        if cid not in basic_energy and n > 4:
            return False, f"non-energy id {cid} has {n} copies (>4)"
    return True, "ok"


def main() -> int:
    tarball_v = _load_validator("validate_candidate_tarball.py")
    entry_v = _load_validator("validate_candidate_entrypoint.py")
    all_ids, basic_energy = _load_card_ids()

    reg = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    smoke = _read_json(EXP / "pass30_live_smoke.json") or {}
    smoke_cands = smoke.get("results") or {}

    rows = []
    for fam_key, fam in (reg.get("families") or {}).items():
        for spec in fam.get("candidates", []):
            cid = spec["candidate_id"]
            blocked = bool(spec.get("blocked_from_league"))
            tar = CAND / f"{cid}.tar.gz"
            tb_ok = tar.exists() and tarball_v.validate(str(tar)) == 0
            ep_ok = tar.exists() and entry_v.validate(str(tar)) == 0
            legal, legal_reason = _deck_legal(tar, all_ids, basic_energy)

            sm = smoke_cands.get(cid, {})
            smoke_clean = bool(sm.get("clean"))
            smoke_bad = sm.get("all_bad_statuses") or []

            eligible = tb_ok and ep_ok and legal and smoke_clean
            tournament_eligible = eligible and not blocked
            rows.append({
                "candidate_id": cid,
                "family": fam.get("family_id", fam_key),
                "role": spec.get("role"),
                "tarball": str(tar.relative_to(REPO)),
                "tarball_valid": tb_ok,
                "entrypoint_valid": ep_ok,
                "deck_legal": legal,
                "deck_legal_reason": legal_reason,
                "smoke_clean": smoke_clean,
                "smoke_bad_statuses": smoke_bad,
                "blocked_from_league": blocked,
                "block_reason": (spec.get("block_reason") or "").strip() or None,
                "eligible": eligible,
                "tournament_eligible": tournament_eligible,
            })

    non_blocked = [r for r in rows if not r["blocked_from_league"]]
    all_eligible = all(r["eligible"] for r in non_blocked)
    tournament_eligible = [r["candidate_id"] for r in rows if r["tournament_eligible"]]
    report = {
        "pass": "30", "part": "F", "local_only": True, "no_upload": True,
        "upload_performed": False, "is_kaggle_leaderboard": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "eligibility_rule": ("tarball_valid AND entrypoint_valid AND deck_legal "
                             "AND smoke_clean"),
        "tournament_rule": "eligible AND NOT blocked_from_league",
        "note": ("Eligibility is a SAFETY/VALIDITY bar for inclusion in the Part-G "
                 "internal tournament, NOT a promotion or upload decision. All "
                 "numbers local/surrogate; never equal Kaggle."),
        "all_non_blocked_eligible": all_eligible,
        "tournament_eligible": tournament_eligible,
        "league_eligible": tournament_eligible,  # alias for harness reuse
        "candidates": rows,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass30_candidate_validation.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")

    cols = ["tarball_valid", "entrypoint_valid", "deck_legal", "smoke_clean",
            "eligible", "blocked_from_league", "tournament_eligible"]
    L = ["# Pass 30 — Candidate validation / eligibility (Part F)", "",
         "> LOCAL ONLY — eligibility is a validity/safety bar, NOT promotion. "
         "NOT a Kaggle leaderboard.", "",
         f"- generated: {report['generated_at']}",
         f"- eligibility rule: `{report['eligibility_rule']}`",
         f"- tournament rule: `{report['tournament_rule']}`",
         f"- all non-blocked eligible: **{all_eligible}**",
         f"- tournament-eligible: **{tournament_eligible}**", "",
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
    (EXP / "pass30_candidate_validation.md").write_text("\n".join(L), encoding="utf-8")

    for r in rows:
        print(f"{r['candidate_id']:40} eligible={r['eligible']} "
              f"tourn={r['tournament_eligible']} "
              f"(tb={r['tarball_valid']} ep={r['entrypoint_valid']} "
              f"legal={r['deck_legal']} smoke={r['smoke_clean']})")
    print(f"\nall_non_blocked_eligible={all_eligible} "
          f"tournament_eligible={tournament_eligible}")
    return 0 if all_eligible else 1


if __name__ == "__main__":
    raise SystemExit(main())
