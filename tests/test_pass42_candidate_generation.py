"""Pass 42 — Candidate Generation v0 (LOCAL-only probation FACTORY) guardrail tests.

These tests assert that the deterministic, stdlib-safe candidate factory built in
Pass 42 stayed inside its hard guardrails:

  * NO Kaggle upload/submit, NO GitHub push, NO promotion/queue.
  * NO root ``main.py`` / ``deck.csv`` mutation (byte-identical to the frozen
    Kaggle baseline).
  * NO public-reference use as a source/parent (references stay benchmark-only and
    absent from the candidate pool).
  * NO invented card IDs — operators only redistribute counts among IDs already in
    the SOURCE deck.
  * Generation is deterministic (seed derived from pass id + catalog version +
    sorted eligible source ids + their tarball/main/deck SHAs, NOT wall-clock) and
    idempotent on rerun (no duplicate events, byte-identical tarballs).
  * Admitted candidates are ``status=probation`` ONLY — never anchor/champion/
    held_probe, never CandidatePromoted / SubmissionQueued / SubmissionUploaded /
    KaggleScoreUpdated.

No network, no Kaggle, no real game runs happen here — these are committed-artifact
+ live-repo integrity checks.

Coverage (28 items):
 1. root main.py/deck.csv byte-identical to baseline
 2. safety preflight artifact is honest + root unchanged
 3. manifest guardrails all true
 4. manifest budgets respected (<=3 new, 1/family, distinct families)
 5. manifest root_safety identical to baseline
 6. generation seed is deterministic (repeatable, not wall-clock)
 7. no public reference used as source / parent / eligible source
 8. exactly three admitted candidates built (distinct families) + tarballs exist
 9. generated tarballs are stdlib-lane shape (main.py + deck.csv only, no cg/)
10. generated deck.csv is 60 whitespace integer lines
11. NO invented IDs — generated deck id-set is a subset of the source deck id-set
12. deck multiset changed but stays legal (same id-set, same 60 total)
13. embedded _EMBEDDED_DECK fallback == deck.csv for each admitted candidate
14. validation: all gates pass for admitted candidates, no rejection reasons
15. regression candidates rejected with honest reasons (not admitted)
16. validation guardrails (no upload/submit/promotion/events) + decision honest
17. admission: exactly the three expected probation ids, within cap
18. admission idempotent on rerun (newly_emitted_this_run == 0)
19. admission emitted NO forbidden events + projection rebuildable from ledger
20. candidate pool holds the three probation candidates (probation only)
21. candidate pool excludes the public references (still benchmark-only)
22. event ledger has the new event types + per-candidate provenance, no forbidden
23. all pass42 generation events carry no_upload=true
24. from_events ignores the new types (no mis-fold as promotion/anchor/champion)
25. scheduler integration proof ok (placement-tier vs anchors, no ref, pool intact)
26. probation eval smoke ok + local-only (not promotion evidence)
27. no tarball deletion / non-identical overwrite
28. new EventType members exist (additive vocabulary)
"""
from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path

import pytest

from ptcg_activegraph.graph.events import Event, EventType
from ptcg_activegraph.tournament import benchmark as B
from ptcg_activegraph.tournament import generation as G
from ptcg_activegraph.tournament.pool import CandidatePool

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
EXP = REPO / "data" / "experiments"
LEDGER = REPO / "data" / "tournament" / "events.jsonl"
GEN_DIR = REPO / "data" / "submissions" / "generated_pass42"

EXPECTED_ADMITTED = {
    "generated_diamond_diamondtoolbox_eratio_v1",
    "generated_dragapult_leaguedragapul_bdens_v1",
    "generated_lightning_monolightningm_dsratio_v1",
}
EXPECTED_FAMILIES = {"diamond", "dragapult", "lightning"}
PUBLIC_REFS = {
    "public_ref_kiyotah_dragapult", "public_ref_kiyotah_iono",
    "public_ref_kiyotah_mega_abomasnow", "public_ref_kiyotah_mega_lucario",
    "public_ref_ryotasueyoshi_alakazam",
}
# Events whose mere presence in the ledger would prove a guardrail breach.
FORBIDDEN_EVENTS = {
    "CandidatePromoted", "SubmissionQueued", "SubmissionUploaded",
    "KaggleScoreUpdated",
}
NON_DESTRUCTIVE_WRITE = {"written_new", "identical_exists", "identical_skip"}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _load(name: str) -> dict:
    return json.loads((EXP / name).read_text(encoding="utf-8"))


def _deck_ints(b: bytes) -> list[int]:
    return [int(tok) for tok in b.split()]


def _tarball_members(rel_path: str) -> tuple[bytes | None, bytes | None, list[str]]:
    """Resolve a manifest tarball path and read (main_bytes, deck_bytes, names)."""
    resolved = G.resolve_tarball(rel_path)
    assert resolved is not None and resolved.exists(), f"unresolved tarball {rel_path}"
    return G._read_tarball_members(resolved)


def _ledger_events() -> list[dict]:
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _etype(ev: dict) -> str | None:
    return ev.get("event_type") or ev.get("type")


@pytest.fixture(scope="module")
def manifest() -> dict:
    return _load("pass42_generated_candidates_manifest.json")


@pytest.fixture(scope="module")
def validation() -> dict:
    return _load("pass42_generated_candidate_validation.json")


@pytest.fixture(scope="module")
def admission() -> dict:
    return _load("pass42_probation_admission.json")


@pytest.fixture(scope="module")
def events() -> list[dict]:
    return _ledger_events()


def _admitted_candidates(manifest: dict) -> list[dict]:
    return [c for c in manifest["candidates"] if c["admit"]]


# --------------------------------------------------------------------------- #
# 1. root unchanged
# --------------------------------------------------------------------------- #
def test_01_root_main_and_deck_unchanged():
    assert _sha(REPO / "main.py") == _sha(BASE / "main.py")
    assert _sha(REPO / "deck.csv") == _sha(BASE / "deck.csv")


# --------------------------------------------------------------------------- #
# 2. safety preflight honest + root unchanged
# --------------------------------------------------------------------------- #
def test_02_safety_preflight_clean():
    pf = _load("pass42_generation_safety_preflight.json")
    assert pf["root_unchanged"] is True
    assert pf["root_main_py_unchanged"] is True
    assert pf["root_deck_csv_unchanged"] is True
    assert pf["upload_performed"] is False
    assert pf["github_push"] is False
    assert pf["promotion_performed"] is False
    assert pf["generation_preflight_safe"] is True
    assert pf["stop_required"] is False


# --------------------------------------------------------------------------- #
# 3. manifest guardrails all true
# --------------------------------------------------------------------------- #
def test_03_manifest_guardrails_all_true(manifest):
    g = manifest["guardrails"]
    for key in (
        "no_github_push", "no_kaggle_submit", "no_kaggle_upload",
        "no_promotion_here", "no_public_reference_source", "no_root_mutation",
        "no_tarball_deletion", "no_tarball_overwrite_unless_identical",
    ):
        assert g[key] is True, f"manifest guardrail {key} not True"


# --------------------------------------------------------------------------- #
# 4. budgets respected
# --------------------------------------------------------------------------- #
def test_04_manifest_budgets_respected(manifest):
    budgets = manifest["budgets"]
    assert budgets["max_new_candidates_per_run"] == 3
    assert budgets["max_per_family"] == 1
    admitted = _admitted_candidates(manifest)
    assert len(admitted) == 3
    assert manifest["n_admitted_built"] <= 3
    fams = [c["family_id"] for c in admitted]
    assert len(fams) == len(set(fams)), "more than one admit per family"
    assert set(fams) == EXPECTED_FAMILIES


# --------------------------------------------------------------------------- #
# 5. manifest root_safety identical
# --------------------------------------------------------------------------- #
def test_05_manifest_root_safety_identical(manifest):
    rs = manifest["root_safety"]
    assert rs["all_identical"] is True
    assert rs["main.py"]["identical_to_baseline"] is True
    assert rs["deck.csv"]["identical_to_baseline"] is True
    # cross-check the recorded sha against the live baseline file
    assert rs["main.py"]["sha256"] == _sha(BASE / "main.py")
    assert rs["deck.csv"]["sha256"] == _sha(BASE / "deck.csv")


# --------------------------------------------------------------------------- #
# 6. deterministic seed (not wall-clock)
# --------------------------------------------------------------------------- #
def test_06_generation_seed_deterministic(manifest, validation):
    pool = CandidatePool.load()
    sources = G.eligible_sources(pool)
    seed_a = G.generation_seed(sources)
    seed_b = G.generation_seed(sources)
    assert seed_a == seed_b, "seed not deterministic across repeated calls"
    assert len(seed_a) == 64 and all(ch in "0123456789abcdef" for ch in seed_a)
    # the persisted artifacts agree on the same seed
    assert manifest["seed"] == validation["seed"]
    # and the live recomputation reproduces the committed seed
    assert manifest["seed"] == seed_a


# --------------------------------------------------------------------------- #
# 7. no public reference as source / parent / eligible
# --------------------------------------------------------------------------- #
def test_07_no_public_reference_source(manifest):
    assert not (set(manifest["eligible_source_ids"]) & PUBLIC_REFS)
    for c in manifest["candidates"]:
        assert c["source_candidate_id"] not in PUBLIC_REFS
        assert c["parent_candidate_id"] not in PUBLIC_REFS


# --------------------------------------------------------------------------- #
# 8. three admitted candidates built + tarballs exist
# --------------------------------------------------------------------------- #
def test_08_three_admitted_built_with_tarballs(manifest):
    admitted = _admitted_candidates(manifest)
    ids = {c["generated_candidate_id"] for c in admitted}
    assert ids == EXPECTED_ADMITTED
    for c in admitted:
        resolved = G.resolve_tarball(c["generated_tarball_path"])
        assert resolved is not None and resolved.exists()
        # recorded sha matches the bytes on disk
        assert _sha(resolved) == c["generated_tarball_sha256"]


# --------------------------------------------------------------------------- #
# 9. generated tarballs are stdlib-lane shape (no cg/)
# --------------------------------------------------------------------------- #
def test_09_generated_tarballs_stdlib_shape(manifest):
    for c in _admitted_candidates(manifest):
        main_b, deck_b, names = _tarball_members(c["generated_tarball_path"])
        assert main_b is not None and deck_b is not None
        base = {Path(n).name for n in names}
        assert base == {"main.py", "deck.csv"}, f"unexpected members {names}"
        assert not any("cg" in Path(n).parts for n in names), "stdlib lane must not ship cg/"
        resolved = G.resolve_tarball(c["generated_tarball_path"])
        assert G.is_stdlib_lane_tarball(resolved) is True


# --------------------------------------------------------------------------- #
# 10. generated deck is 60 integer lines
# --------------------------------------------------------------------------- #
def test_10_generated_deck_60_ints(manifest):
    for c in _admitted_candidates(manifest):
        _, deck_b, _ = _tarball_members(c["generated_tarball_path"])
        ids = _deck_ints(deck_b)
        assert len(ids) == 60, f"{c['generated_candidate_id']} deck != 60"
        assert all(isinstance(i, int) for i in ids)


# --------------------------------------------------------------------------- #
# 11. NO invented IDs — generated id-set subset of source id-set
# --------------------------------------------------------------------------- #
def test_11_no_invented_ids(manifest):
    for c in _admitted_candidates(manifest):
        _, src_deck, _ = _tarball_members(c["source_tarball_path"])
        _, gen_deck, _ = _tarball_members(c["generated_tarball_path"])
        src_ids = set(_deck_ints(src_deck))
        gen_ids = set(_deck_ints(gen_deck))
        invented = gen_ids - src_ids
        assert not invented, f"{c['generated_candidate_id']} invented ids {invented}"


# --------------------------------------------------------------------------- #
# 12. deck multiset changed but still legal
# --------------------------------------------------------------------------- #
def test_12_deck_multiset_changed_legal(manifest):
    for c in _admitted_candidates(manifest):
        assert c["deck_changing"] is True
        _, src_deck, _ = _tarball_members(c["source_tarball_path"])
        _, gen_deck, _ = _tarball_members(c["generated_tarball_path"])
        src = sorted(_deck_ints(src_deck))
        gen = sorted(_deck_ints(gen_deck))
        assert src != gen, "deck-changing operator left the multiset unchanged"
        assert len(src) == len(gen) == 60


# --------------------------------------------------------------------------- #
# 13. embedded fallback == deck.csv
# --------------------------------------------------------------------------- #
def test_13_embedded_deck_equals_deckcsv(manifest):
    for c in _admitted_candidates(manifest):
        main_b, deck_b, _ = _tarball_members(c["generated_tarball_path"])
        embedded = G.extract_embedded_deck(main_b.decode("utf-8"))
        assert sorted(embedded) == sorted(_deck_ints(deck_b)), (
            f"{c['generated_candidate_id']} embedded deck != deck.csv")


# --------------------------------------------------------------------------- #
# 14. validation: admitted candidates pass every gate
# --------------------------------------------------------------------------- #
def test_14_validation_admitted_pass_all_gates(validation):
    admitted = [r for r in validation["results"] if r["admitted"]]
    assert {r["generated_candidate_id"] for r in admitted} == EXPECTED_ADMITTED
    for r in admitted:
        assert r["intended_admit"] is True
        assert r["rejection_reasons"] == []
        assert all(bool(v) for v in r["gates"].values()), r["generated_candidate_id"]


# --------------------------------------------------------------------------- #
# 15. regression candidates rejected with honest reasons
# --------------------------------------------------------------------------- #
def test_15_regression_candidates_rejected(validation):
    rejected = [r for r in validation["results"] if not r["admitted"]]
    assert len(rejected) >= 2, "expected at least the no-op + policy regression cases"
    for r in rejected:
        assert r["intended_admit"] is False
        assert r["rejection_reasons"], f"{r['generated_candidate_id']} lacks a reason"


# --------------------------------------------------------------------------- #
# 16. validation guardrails + honest decision
# --------------------------------------------------------------------------- #
def test_16_validation_guardrails(validation):
    g = validation["guardrails"]
    for key in ("no_events_emitted_by_validation", "no_promotion", "no_submit",
                "no_upload"):
        assert g[key] is True
    assert validation["gate_manifest_consistency_ok"] is True
    assert validation["n_admitted"] == 3
    assert validation["decision"] in {
        "candidate_generation_v0_enabled",
        "generation_infrastructure_ready_no_admissions",
    }


# --------------------------------------------------------------------------- #
# 17. admission: exactly three probation ids, within cap
# --------------------------------------------------------------------------- #
def test_17_admission_three_probation(admission):
    assert set(admission["admitted_ids"]) == EXPECTED_ADMITTED
    assert admission["n_admitted"] <= admission["max_admit_cap"] <= 3
    assert admission["guardrails"]["all_admitted_are_probation"] is True
    assert admission["no_upload"] is True
    assert admission["local_only"] is True


# --------------------------------------------------------------------------- #
# 18. admission idempotent on rerun
# --------------------------------------------------------------------------- #
def test_18_admission_idempotent(admission):
    assert admission["newly_emitted_this_run"] == 0, (
        "rerun must not re-emit provenance events")
    for chk in admission["per_candidate_checks"]:
        assert chk["in_ledger_projection"] is True
        assert chk["in_pool_json"] is True
        assert chk["status_probation_both"] is True
        assert chk["ledger_pool_snapshot_match"] is True


# --------------------------------------------------------------------------- #
# 19. admission emitted no forbidden events + rebuildable
# --------------------------------------------------------------------------- #
def test_19_admission_no_forbidden_events(admission):
    g = admission["guardrails"]
    assert g["no_forbidden_events_emitted"] is True
    assert g["forbidden_event_types_in_ledger"] == []
    assert g["no_protected_status_created"] is True
    assert g["projection_rebuildable_from_ledger"] is True


# --------------------------------------------------------------------------- #
# 20. pool holds the three probation candidates (probation only)
# --------------------------------------------------------------------------- #
def test_20_pool_has_three_probation():
    pool = CandidatePool.load()
    by_id = {c.candidate_id: c for c in pool.candidates}
    for cid in EXPECTED_ADMITTED:
        assert cid in by_id, f"{cid} missing from pool"
        assert by_id[cid].status == "probation"
    # no generated candidate slipped into a protected status
    for c in pool.candidates:
        if c.candidate_id.startswith("generated_"):
            assert c.status == "probation"


# --------------------------------------------------------------------------- #
# 21. pool excludes public references (benchmark-only)
# --------------------------------------------------------------------------- #
def test_21_pool_excludes_public_refs():
    pool = CandidatePool.load()
    pool_ids = {c.candidate_id for c in pool.candidates}
    assert not (pool_ids & PUBLIC_REFS)
    opps = B.load_opponents(include_optional=True)
    assert {o.agent_id for o in opps} >= PUBLIC_REFS
    assert all(o.usage == "benchmark_opponent_only" for o in opps)


# --------------------------------------------------------------------------- #
# 22. event ledger: new types + provenance, no forbidden
# --------------------------------------------------------------------------- #
def test_22_event_ledger_provenance(events):
    assert events, "expected a populated tournament event ledger"
    types = [_etype(e) for e in events]
    assert types.count("CandidateGenerated") >= 3
    assert types.count("CandidateValidationFinished") >= 3
    assert not (set(types) & FORBIDDEN_EVENTS), "forbidden event in ledger"
    # each admitted id has a probation registration
    reg_probation = {
        e["payload"].get("candidate_id")
        for e in events
        if _etype(e) == "TournamentParticipantRegistered"
        and e["payload"].get("status") == "probation"
    }
    assert EXPECTED_ADMITTED <= reg_probation


# --------------------------------------------------------------------------- #
# 23. all pass42 generation events are no_upload=true
# --------------------------------------------------------------------------- #
def test_23_pass42_events_no_upload(events):
    pass42 = [
        e for e in events
        if "pass42" in (e.get("tags") or [])
        and _etype(e) in {"CandidateGenerated", "CandidateValidationFinished",
                           "TournamentParticipantRegistered"}
    ]
    assert pass42, "expected pass42-tagged generation events"
    for e in pass42:
        assert e["payload"].get("no_upload") is True, _etype(e)


# --------------------------------------------------------------------------- #
# 24. from_events ignores the new types (no mis-fold as promotion)
# --------------------------------------------------------------------------- #
def test_24_from_events_ignores_new_types(events):
    objs = [Event.from_dict(e) for e in events]
    rebuilt = CandidatePool.from_events(objs)
    by_id = {c.candidate_id: c for c in rebuilt.candidates}
    for cid in EXPECTED_ADMITTED:
        assert cid in by_id, f"{cid} not folded from ledger"
        # folded ONLY via the registration event -> stays probation, never promoted
        assert by_id[cid].status == "probation"
    for c in rebuilt.candidates:
        if c.candidate_id.startswith("generated_"):
            assert c.status not in {"champion", "anchor", "family_champion"}


# --------------------------------------------------------------------------- #
# 25. scheduler integration proof
# --------------------------------------------------------------------------- #
def test_25_scheduler_integration_ok():
    s = _load("pass42_scheduler_generation_integration.json")
    assert s["ok"] is True
    assert s["n_probation"] == 3
    for v in s["checks"].values():
        assert v is True
    assert set(s["probation_ids"]) == EXPECTED_ADMITTED
    assert not (set(s["protected_candidates"]) & EXPECTED_ADMITTED)


# --------------------------------------------------------------------------- #
# 26. probation eval smoke ok + local-only
# --------------------------------------------------------------------------- #
def test_26_eval_smoke_local_only():
    e = _load("pass42_probation_eval_smoke.json")
    assert e["ok"] is True
    assert e["promotion_evidence"] is False
    assert e["local_only"] is True
    assert e["no_upload"] is True
    for v in e["guardrails"].values():
        assert v is True
    assert all(c["liveness_ok"] for c in e["per_candidate"])


# --------------------------------------------------------------------------- #
# 27. no tarball deletion / non-identical overwrite
# --------------------------------------------------------------------------- #
def test_27_no_tarball_destruction(manifest):
    assert manifest["refused_overwrites"] == []
    for c in manifest["candidates"]:
        assert c["write_status"] in NON_DESTRUCTIVE_WRITE, c["write_status"]
    # every generated tarball lives ONLY under the dedicated pass42 dir
    for c in _admitted_candidates(manifest):
        assert c["generated_tarball_path"].startswith(
            "data/submissions/generated_pass42/")


# --------------------------------------------------------------------------- #
# 28. new EventType members exist (additive vocabulary)
# --------------------------------------------------------------------------- #
def test_28_new_event_types_exist():
    assert EventType.CandidateGenerated.value == "CandidateGenerated"
    assert EventType.CandidateValidationFinished.value == "CandidateValidationFinished"
