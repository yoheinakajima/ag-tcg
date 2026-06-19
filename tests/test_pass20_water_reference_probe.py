"""Pass 20 — targeted tests for the human-approved Water-reference Kaggle probe.

These are cheap, offline checks of the durable Pass-20 invariants:
- root main.py / deck.csv unchanged vs the v1 baseline (immutability guard);
- the probed candidate tarball contains exactly top-level main.py + deck.csv;
- the candidate deck is 60 rows / all-integer ids / legal non-energy counts and
  matches the Pass-17 manifest card ids;
- the preflight + live-smoke artifacts record PASS with no blockers;
- the ActiveGraph event chain for the probe exists, is framed as a calibration
  probe (NOT a promotion claim), and exactly ONE SubmissionUploaded for the
  candidate exists;
- reports/site carry the required disclaimers and the probe is not called
  "strictly better".
"""
from __future__ import annotations

import filecmp
import io
import json
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "data/submissions/candidates_pass17/league_water_core_reference.tar.gz"
V1_DIR = ROOT / "data/baselines/v1_kaggle_349_8"
LAB_EVENTS = ROOT / "data/activegraph/lab_events.jsonl"

PASS17_MANIFEST_IDS = {3, 721, 722, 723, 1092, 1121, 1145, 1163, 1219, 1227, 1262}


def _tar_members(path: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    with tarfile.open(path, "r:gz") as tf:
        for m in tf.getmembers():
            if m.isfile():
                out[m.name] = tf.extractfile(m).read()
    return out


def test_root_unchanged_vs_v1():
    assert filecmp.cmp(ROOT / "main.py", V1_DIR / "main.py", shallow=False)
    assert filecmp.cmp(ROOT / "deck.csv", V1_DIR / "deck.csv", shallow=False)


def test_candidate_tarball_top_level_only():
    members = _tar_members(CANDIDATE)
    assert set(members) == {"main.py", "deck.csv"}, members.keys()


def test_candidate_deck_shape_and_manifest():
    members = _tar_members(CANDIDATE)
    rows = [r.strip() for r in members["deck.csv"].decode().splitlines() if r.strip()]
    assert len(rows) == 60
    ids = [int(r) for r in rows]  # raises if any row is non-integer
    counts: dict[int, int] = {}
    for cid in ids:
        counts[cid] = counts.get(cid, 0) + 1
    assert set(counts) == PASS17_MANIFEST_IDS
    # non-energy (anything other than basic energy id 3) capped at 4 copies
    for cid, n in counts.items():
        if cid != 3:
            assert n <= 4, (cid, n)


def test_preflight_and_smoke_artifacts_pass():
    pf = json.loads((ROOT / "data/experiments/pass20_candidate_preflight.json").read_text())
    assert pf["preflight_passed"] is True
    assert pf["blockers"] == []
    assert pf["deck"]["card_ids_match_pass17_manifest"] is True
    sm = json.loads((ROOT / "data/experiments/pass20_live_smoke.json").read_text())
    assert sm["all_gates_passed"] is True
    assert sm["core_competency_gate"]["hard_failures"] == 0
    assert sm["live_smoke_selfplay"]["status"] == "PASS"


def _events() -> list[dict]:
    return [json.loads(l) for l in LAB_EVENTS.read_text().splitlines() if l.strip()]


def _pass20_probe_events(evs: list[dict]) -> list[dict]:
    return [e for e in evs if "live_calibration_probe" in (e.get("tags") or [])]


def test_event_chain_is_calibration_probe_not_promotion():
    probe = _pass20_probe_events(_events())
    promo = [e for e in probe if e["event_type"] == "StrategyPromotionDecision"]
    assert promo, "missing StrategyPromotionDecision for the probe"
    p = promo[-1]["payload"]
    assert p.get("promotion_claimed") is False
    assert p.get("human_approved") is True
    assert p.get("kind") == "human_approved_live_calibration_probe"


def test_exactly_one_submission_uploaded_for_candidate():
    evs = _events()
    uploaded = [
        e for e in evs
        if e["event_type"] == "SubmissionUploaded"
        and (e.get("payload") or {}).get("candidate_id") == "league_water_core_reference"
    ]
    assert len(uploaded) == 1, f"expected exactly one upload, got {len(uploaded)}"
    assert uploaded[0]["payload"].get("upload_performed") is True


def test_probe_event_full_chain_present():
    probe = _pass20_probe_events(_events())
    types = {e["event_type"] for e in probe}
    for required in {
        "StrategyPromotionDecision", "SubmissionQueued",
        "SubmissionUploaded", "KaggleScoreUpdated",
    }:
        assert required in types, f"missing {required} in probe event chain"


def test_reports_carry_disclaimers_and_no_strictly_better():
    report = (ROOT / "data/reports/pass20_water_reference_kaggle_probe_report.md").read_text()
    assert "NOT a promotion claim" in report
    assert "INTERNAL LEAGUE" in report
    # every mention of "strictly better" must be in a negating context (it is NOT
    # strictly better) -- never an unqualified claim that the candidate is better.
    low = report.lower()
    idx = 0
    while True:
        idx = low.find("strictly better", idx)
        if idx == -1:
            break
        window = low[max(0, idx - 60):idx]
        assert "not" in window, f"unqualified 'strictly better' near: {report[max(0,idx-40):idx+20]!r}"
        idx += len("strictly better")
    site = (ROOT / "data/site/index.html").read_text()
    assert "not a promotion claim" in site.lower()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
