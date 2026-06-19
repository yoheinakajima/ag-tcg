"""ActiveGraph Pass 17 — internal deck league + strategy canvas tests.

Covers (spec Part L):
* deck-idea validator catches missing card ids and >4 copies of a non-basic-energy
  card, and accepts a legal 60-card deck,
* every built candidate deck is exactly 60 integer card ids,
* candidate tarballs contain ONLY top-level main.py + deck.csv,
* every candidate passes the entrypoint validator (last callable resolves),
* Durant is blocked from the league (its live self-smoke is INVALID),
* the league excludes validator/smoke-failing candidates (eligible == clean only),
* raw card data + raw replays are gitignored (never committed),
* root main.py / deck.csv are byte-identical to the v1 baseline,
* no upload/submit flag is ever set true anywhere in the pass outputs,
* the league + rankings carry the explicit "not a Kaggle leaderboard" disclaimer.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

EXP = REPO / "data" / "experiments"
REPORTS = REPO / "data" / "reports"
CAND_DIR = REPO / "data" / "submissions" / "candidates_pass17"
DECK_IDEAS = REPO / "experiments" / "deck_ideas.yaml"

DV = EXP / "pass17_deck_idea_validation.json"
CV = EXP / "pass17_candidate_validation.json"
LG = EXP / "pass17_internal_league.json"
RK = EXP / "pass17_league_rankings.json"
CO = EXP / "pass17_deck_pilot_compatibility.json"


def _json(p: Path) -> dict:
    assert p.exists(), f"missing evidence file: {p}"
    return json.loads(p.read_text(encoding="utf-8"))


def _load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


# --------------------------------------------------------------- deck validator
def _validator():
    return _load_module("validate_deck_ideas")


def test_validator_catches_missing_card_id():
    v = _validator()
    res = v.validate_deck("probe_missing", {"cards": {"999999": 1}}, v.load_card_db())
    assert not res["valid"]
    assert any("999999" in e and "NOT FOUND" in e for e in res["errors"]), res["errors"]


def test_validator_catches_more_than_four_copies():
    v = _validator()
    db = v.load_card_db()
    # pick a real non-basic-energy id from a built deck and over-stack it
    decks = _json(DV)["decks"]
    sample = next(d for d in decks if d["buildable"])
    real_id = next(c["id"] for c in sample["cards"]
                   if c.get("found") and not c.get("is_basic_energy"))
    res = v.validate_deck("probe_overstack", {"cards": {real_id: 5}}, db)
    assert not res["valid"]
    assert any("copies" in e.lower() for e in res["errors"]), res["errors"]


def test_validator_accepts_legal_decks():
    rep = _json(DV)
    buildable = [d for d in rep["decks"] if d["buildable"]]
    assert buildable, "no buildable decks recorded"
    for d in buildable:
        assert d["valid"], f"{d['candidate_id']} should be valid: {d['errors']}"


# --------------------------------------------------------------- 60-int decks
def test_every_candidate_deck_is_sixty_integer_ids():
    rep = _json(DV)
    for d in rep["decks"]:
        if not d["buildable"]:
            continue
        assert d["total"] == 60, f"{d['candidate_id']} has {d['total']} cards"
        assert sum(c["count"] for c in d["cards"]) == 60, d["candidate_id"]
        for c in d["cards"]:
            assert isinstance(c["id"], int), f"non-int card id {c['id']!r}"


# --------------------------------------------------------------- tarball shape
def test_candidate_tarballs_are_toplevel_main_and_deck_only():
    tars = sorted(CAND_DIR.glob("*.tar.gz"))
    assert tars, "no candidate tarballs built"
    for tar in tars:
        with tarfile.open(tar, "r:gz") as tf:
            names = sorted(m.name for m in tf.getmembers() if m.isfile())
        assert names == ["deck.csv", "main.py"], f"{tar.name} contents: {names}"


# --------------------------------------------------------------- entrypoint gate
def test_every_candidate_passes_entrypoint_validator():
    rep = _json(CV)
    for c in rep["candidates"]:
        assert c["tarball_gate"]["passed"], f"{c['candidate_id']} failed tarball gate"
        assert c["entrypoint_gate"]["passed"], f"{c['candidate_id']} failed entrypoint gate"


# --------------------------------------------------------------- Durant blocked
def test_durant_is_blocked_from_league():
    cv = _json(CV)
    durant = next(c for c in cv["candidates"] if "durant" in c["candidate_id"])
    assert durant["blocked_from_league"] is True
    assert durant["league_eligible"] is False
    # empirical justification: its live self-smoke is INVALID
    assert durant["live_smoke_self"]["ok"] is False
    assert durant["candidate_id"] not in cv["league_eligible"]
    # and it never appears as a league participant
    lg = _json(LG)
    assert all("durant" not in p["id"] for p in lg["participants"])


# --------------------------------------------------------------- league excludes failures
def test_league_includes_only_clean_eligible_candidates():
    cv = _json(CV)
    lg = _json(LG)
    eligible = set(cv["league_eligible"])
    participant_candidates = {
        p["id"] for p in lg["participants"] if p["role"] == "league_candidate"
    }
    # every candidate participant must be eligible
    assert participant_candidates <= eligible
    # eligibility implies gates + smoke clean
    for c in cv["candidates"]:
        if c["candidate_id"] in eligible:
            assert c["gates_pass"] and c["smoke_pass"], c["candidate_id"]
        else:
            assert not (c["gates_pass"] and c["smoke_pass"] and not c["blocked_from_league"]), \
                c["candidate_id"]


# --------------------------------------------------------------- gitignore raw data
def test_raw_card_data_and_replays_are_gitignored():
    gi = (REPO / ".gitignore").read_text(encoding="utf-8")
    patterns = ["EN_Card_Data.csv", "data/cards", "data/replays"]
    matched = [p for p in patterns if p in gi]
    assert matched, f".gitignore must ignore raw card data / replays; has none of {patterns}"
    # and the real card csv is not tracked by git
    out = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "data/cards/EN_Card_Data.csv"],
        cwd=REPO, capture_output=True, text=True)
    assert out.returncode != 0, "raw EN_Card_Data.csv must NOT be tracked by git"


# --------------------------------------------------------------- root immutable
def test_root_entrypoints_unchanged_vs_v1_baseline():
    # package_submission --verify-only is the authoritative root-safety gate
    res = subprocess.run(
        [sys.executable, "scripts/package_submission.py", "--verify-only"],
        cwd=REPO, capture_output=True, text=True, env={**__import__("os").environ,
                                                        "PYTHONPATH": str(REPO / "src")})
    combined = (res.stdout + res.stderr).lower()
    assert res.returncode == 0, f"package --verify-only failed:\n{res.stdout}\n{res.stderr}"
    assert "fail" not in combined or "0 fail" in combined, combined


# --------------------------------------------------------------- no upload
def test_no_upload_or_submission_was_performed():
    for p in (LG, RK, CO, CV):
        rep = _json(p)
        blob = json.dumps(rep).lower()
        assert '"upload_performed": true' not in blob
        assert '"is_kaggle_leaderboard": true' not in blob
    rk = _json(RK)
    assert rk["upload_performed"] is False
    assert rk["is_kaggle_leaderboard"] is False


# --------------------------------------------------------------- disclaimer
def test_league_carries_not_a_kaggle_leaderboard_disclaimer():
    for p in (LG, RK):
        d = _json(p).get("disclaimer", "")
        assert "NOT A KAGGLE LEADERBOARD" in d.upper(), p.name
    # the markdown report + site repeat the caveat
    md = (REPORTS / "pass17_internal_deck_league_report.md").read_text(encoding="utf-8")
    assert "NOT A KAGGLE LEADERBOARD" in md.upper()
    site = (REPO / "data" / "site" / "index.html").read_text(encoding="utf-8")
    assert "NOT A KAGGLE LEADERBOARD" in site.upper()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
