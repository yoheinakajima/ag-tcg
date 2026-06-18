"""ActiveGraph Pass 10B — evaluation recovery + replay acquisition tests.

Covers (Part J):
* the live score registry selects the highest *complete non-error* score as the
  dynamic active control, and ignores error/pending submissions;
* the cabt diagnostic / eval-smoke writes a ``blocked`` status when cabt is
  reported unavailable;
* the replay-acquisition doc lists the required raw-replay filenames;
* a missing replay keeps its archetype ``blocked`` in the meta pool;
* the chaos-lane doc exists and carries no queue/upload instruction;
* root ``main.py`` / ``deck.csv`` are unchanged vs the v1 baseline;
* the candidate tarball validator remains mandatory (rejects junk, passes good).

All tests read the lab's own artifacts; none run Kaggle or mutate root files.
"""

from __future__ import annotations

import filecmp
import importlib.util
import json
import sys
import tarfile
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))
V1_BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
META_POOL = REPO / "experiments" / "meta_pool.yaml"
ACQUISITION_DOC = REPO / "data" / "meta_replays" / "REPLAY_ACQUISITION.md"
CHAOS_DOC = REPO / "docs" / "CHAOS_PLAYBOOK_LANE.md"
CANDIDATE_TARBALLS = REPO / "data" / "submissions" / "candidates"


def _load_script(name: str, mod_name: str):
    path = REPO / "scripts" / name
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


@pytest.fixture(scope="module")
def registry_mod():
    return _load_script("build_live_score_registry.py", "_lsr_test")


@pytest.fixture(scope="module")
def smoke_mod():
    return _load_script("pass10b_eval_smoke.py", "_smoke_test")


@pytest.fixture(scope="module")
def vct():
    return _load_script("validate_candidate_tarball.py", "_vct_b_test")


# Synthetic rows exercising every classification path.
_ROWS_CSV = (
    "fileName,date,description,status,publicScore,privateScore\n"
    "combo_lo.tar.gz,2026-06-18 16:00:00,combo low,complete,294.0,\n"
    "broken.tar.gz,2026-06-18 15:00:00,errored,error,,\n"
    "best.tar.gz,2026-06-17 19:00:00,v1 best,complete,363.0,\n"
    "mid.tar.gz,2026-06-17 18:00:00,v2 mid,complete,355.2,\n"
    "pend.tar.gz,2026-06-17 17:00:00,pending one,pending,,\n"
)


def test_registry_selects_highest_complete_non_error(registry_mod):
    rows = registry_mod.parse_submissions_csv(_ROWS_CSV)
    ac = registry_mod.select_active_control(rows)
    assert ac is not None
    assert ac["filename"] == "best.tar.gz"
    assert ac["public_score"] == 363.0


def test_active_control_ignores_error_and_pending(registry_mod):
    # Even though the error/pending rows are present, the active control is the
    # highest *complete* score, and no error/pending row can be selected.
    rows = registry_mod.parse_submissions_csv(_ROWS_CSV)
    reg = registry_mod.build_registry(rows, competition="x")
    ac = reg["active_control"]
    assert ac["status"] == "complete"
    classes = {r["filename"]: r["classification"] for r in reg["submissions"]}
    assert classes["broken.tar.gz"] == "error"
    assert classes["pend.tar.gz"] == "pending"
    assert classes["best.tar.gz"] == "active_control_candidate"


def test_candidate_below_control_is_live_rejected(registry_mod):
    rows = registry_mod.parse_submissions_csv(_ROWS_CSV)
    reg = registry_mod.build_registry(rows, competition="x")
    rejected = {r["filename"] for r in reg["rejected_candidates"]}
    # cand_lo (combo family) scored below the control -> rejected.
    assert "combo_lo.tar.gz" in rejected
    # mid.tar.gz is a complete non-candidate below control -> NOT rejected.
    assert "mid.tar.gz" not in rejected


def test_registry_no_complete_is_ambiguous_not_guessed(registry_mod):
    csv = ("fileName,date,description,status,publicScore,privateScore\n"
           "a.tar.gz,2026-06-18 16:00:00,errored,error,,\n"
           "b.tar.gz,2026-06-18 15:00:00,pending,pending,,\n")
    rows = registry_mod.parse_submissions_csv(csv)
    reg = registry_mod.build_registry(rows, competition="x")
    assert reg["active_control"] is None
    assert any("ambiguous" in n.lower() for n in reg["notes"])


def test_live_registry_artifact_matches_dynamic_rule_or_pinned():
    reg_path = REPO / "data" / "kaggle_uploads" / "live_score_registry.json"
    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    completes = [s for s in reg["submissions"]
                 if s["status"] == "complete" and s["public_score"] is not None]
    best = max(completes, key=lambda s: s["public_score"])
    ac = reg["active_control"]
    pinned = any("pinned" in n.lower() for n in reg.get("notes", []))
    if not pinned:
        # Pure dynamic rule: active control is the highest complete score.
        assert ac["filename"] == best["filename"]
        assert ac["public_score"] == best["public_score"]
    else:
        # Pinned maintained anchor: must still be a real complete+scored row,
        # and the pin (plus the higher raw baseline, if any) must be disclosed.
        assert any(
            s["filename"] == ac["filename"]
            and s["public_score"] == ac["public_score"]
            and s["status"] == "complete"
            for s in reg["submissions"]
        )
        if ac["filename"] != best["filename"]:
            assert any("highest raw live score" in n.lower()
                       for n in reg.get("notes", []))


def test_eval_smoke_blocked_when_cabt_unavailable(smoke_mod, tmp_path, monkeypatch):
    fake_diag = tmp_path / "diag.json"
    fake_diag.write_text(json.dumps({"cabt_available": False}), encoding="utf-8")
    monkeypatch.setattr(smoke_mod, "DIAG", fake_diag)
    rep = smoke_mod.run_smoke()
    assert rep["status"] == "blocked"
    assert rep["reason"] == "cabt_unavailable"
    assert rep["smoke_attempted"] is False
    assert rep["can_run_future_meta_eval"] is False


def test_cabt_diagnostic_artifact_has_status_and_reason():
    diag = REPO / "data" / "experiments" / "cabt_diagnostic.json"
    d = json.loads(diag.read_text(encoding="utf-8"))
    assert d["status"] in {"available", "blocked"}
    # invariant: blocked <=> reason set; available <=> no reason
    assert (d["status"] == "blocked") == (d["reason"] == "cabt_unavailable")


def test_acquisition_doc_lists_required_replay_files():
    text = ACQUISITION_DOC.read_text(encoding="utf-8")
    for fname in (
        "data/meta_replays/raw/80503804_tellurium_metal_ex.json",
        "data/meta_replays/raw/tymu_water_maxbelt.json",
        "data/meta_replays/raw/other_loss_*.json",
        "data/meta_replays/raw/other_win_*.json",
    ):
        assert fname in text, f"missing required filename in acquisition doc: {fname}"


def test_acquired_replay_confirms_archetype_with_surrogate():
    """Pass 11B acquired the metal + maxbelt replays. Each archetype is now
    CONFIRMED from a real extracted replay, carries a surrogate deck + episode,
    and is no longer in the blocked list. (Pass-10B kept these blocked while the
    replays were missing; the gate flips only once the real payload arrives.)"""
    pool = yaml.safe_load(META_POOL.read_text(encoding="utf-8"))
    by_key = {a["key"]: a for a in pool["archetypes"]}
    for key in ("metal_ex_zacian_ramp", "water_kyogre_abomasnow_maxbelt"):
        a = by_key[key]
        assert a["status"] == "confirmed_from_replay"
        assert a["confidence"] == "confirmed"
        assert a["surrogate_deck"] is not None
        assert (REPO / a["surrogate_deck"]).exists()
        assert a["replay_episode"] is not None
        assert key not in pool["coverage"]["blocked_archetypes"]
    assert pool["coverage"]["blocked_archetypes"] == []


def test_chaos_doc_exists_with_no_queue_or_upload_instruction():
    assert CHAOS_DOC.exists()
    text = CHAOS_DOC.read_text(encoding="utf-8")
    low = text.lower()
    assert "research lane" in low
    # No affirmative upload/submit instruction.
    assert "kaggle competitions submit" not in low
    # The hard gate must be present.
    assert "no chaos candidate may be queued" in low


def test_root_files_unchanged_vs_v1_baseline():
    assert filecmp.cmp(REPO / "main.py", V1_BASELINE / "main.py", shallow=False)
    assert filecmp.cmp(REPO / "deck.csv", V1_BASELINE / "deck.csv", shallow=False)


def test_pass10_section_resolves_scores_by_identity_not_role():
    """Pass 10B updates meta_pool.yaml so the dynamic active control is v1.

    The historical Pass 10 section must still report v1/v2 by *identity*, never by
    the (now changed) active_control role, so it cannot mislabel v1's score as v2.
    """
    from ptcg_activegraph.experiments import report

    pool = yaml.safe_load(META_POOL.read_text(encoding="utf-8"))
    sc = report._pass10_control_scores(pool)
    assert sc["v1"] == 363.0
    assert sc["v2"] == 355.2
    assert sc["rejected"] == 294.0
    # The v2 control entry is no longer the active control, but its identity score
    # must remain attached to v2 (not silently swapped to v1's 363.0).
    assert sc["v2"] != sc["v1"]


def test_report_has_no_unlabeled_cabt_contradiction():
    """If the strategy report says cabt is available (Pass 10B), any 'cabt absent'
    statement elsewhere must be explicitly marked historical/superseded."""
    md = REPO / "data" / "reports" / "activegraph_strategy_report.md"
    if not md.exists():
        pytest.skip("strategy report not built yet")
    low = md.read_text(encoding="utf-8").lower()
    if "cabt available: **true**" not in low:
        pytest.skip("report does not assert cabt availability")
    # Walk every line that claims cabt is absent/assumed-absent and require a
    # qualifier on that same line that marks it historical OR explicitly refutes
    # it (a correction line that quotes the old wrong claim is not a contradiction).
    qualifiers = ("superseded", "pass 10-era", "historical", "correction",
                  "wrong", "assumed absent")
    for line in low.splitlines():
        if "cabt" in line and ("absent" in line or "not runnable" in line):
            assert any(q in line for q in qualifiers), (
                f"unlabeled cabt-absent contradiction: {line!r}"
            )


def test_tarball_validator_is_mandatory(vct, tmp_path):
    junk = tmp_path / "junk.tar.gz"
    with tarfile.open(junk, "w:gz") as tar:
        p = tmp_path / "notes.txt"
        p.write_text("not a submission", encoding="utf-8")
        tar.add(p, arcname="notes.txt")
    assert vct.validate(str(junk)) == 1
    assert vct.validate(str(tmp_path / "does_not_exist.tar.gz")) == 1
    good = CANDIDATE_TARBALLS / "combo_full_safety_v3_fixed.tar.gz"
    if good.exists():
        assert vct.validate(str(good)) == 0
