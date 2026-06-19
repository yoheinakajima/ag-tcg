"""Pass 25 — Water live-control hardening targeted tests.

READ-ONLY/local pass. These tests assert the Pass-25 artifacts and the two
narrow, evidence-grounded hardening levers are internally consistent and behave
exactly as claimed, without ever touching the immutable root submission:

  * root main.py / deck.csv byte-identical to the v1 baseline,
  * live-score helpers coerce a string ``publicScore`` to float and select the
    active control as the highest complete score (no hardcoded label),
  * the three replay loss-windows are present and cover the attributed episodes,
  * every fixture references only real deck/role card ids (no invented ids),
  * the ctx38 deckout draw-count guard clamps ONLY at low deck and never
    suppresses an attack,
  * the ctx7 prize-liability search pivot fires ONLY when there is no 1-prize
    attacker in play and never broadly redirects/blocks the Mega line,
  * Mega Abomasnow ex is never a benchable Basic,
  * the recovery ids were validated as real yet blocked pre-build,
  * candidate tarballs are top-level main.py+deck.csv only and pass the
    entrypoint validator, with runtime contexts matching the manifest,
  * the no-upload / read-only invariant holds across manifest and events,
  * the report carries the honest surrogate/local caveat.
"""

from __future__ import annotations

import copy
import filecmp
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

try:
    import yaml
except Exception:  # pragma: no cover - yaml is available in the runtime
    yaml = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ptcg_activegraph.pilot.decisions import (  # noqa: E402
    _is_benchable_basic,
    choose_draw_count,
    choose_main_action,
    choose_to_hand,
    decide,
)
from ptcg_activegraph.pilot.roles import load_playbook_roles  # noqa: E402

# Live-score registry helpers (pure functions; module bootstraps src on import).
try:
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_live_score_registry as live_score  # noqa: E402
except Exception:  # pragma: no cover - import guarded so the rest still runs
    live_score = None

EXP = ROOT / "data" / "experiments"
FIXTURE_DIR = ROOT / "data" / "fixtures" / "pass25_water_hardening"
PLAYBOOK_PATH = ROOT / "playbooks" / "pass25_water_hardening.yaml"
CAND_DIR = ROOT / "data" / "submissions" / "candidates_pass25"
MANIFEST = ROOT / "experiments" / "runs_pass25" / "manifest.json"
BASELINE = ROOT / "data" / "baselines" / "v1_kaggle_349_8"
LAB_EVENTS = ROOT / "data" / "activegraph" / "lab_events.jsonl"
REPORT = EXP / "pass25_water_live_control_hardening_report.md"

CANDIDATES = ["deckout_guard_v1", "prize_liability_guard_v1", "hybrid_guard_v1"]
EPISODES = ["80623232", "80622626", "80622745"]

KYOGRE = 721          # primary_basic_attacker (1-prize, benchable)
SNOVER = 722          # setup_basic (benchable)
MEGA_ABOMASNOW = 723  # evolution_payoff (2-prize, NOT benchable)


def _load(path: Path):
    return json.loads(Path(path).read_text())


@pytest.fixture(scope="module")
def playbook():
    assert yaml is not None
    return yaml.safe_load(PLAYBOOK_PATH.read_text())


@pytest.fixture(scope="module")
def prize_on_playbook(playbook):
    """Control playbook with ONLY the prize-liability pivot flag enabled, as the
    build script sets it on prize_liability_guard_v1 / hybrid_guard_v1."""
    pb = copy.deepcopy(playbook)
    pb.setdefault("flags", {})["prize_liability_search_pivot"] = True
    return pb


# -- root immutability -------------------------------------------------------

def test_root_main_and_deck_unchanged_vs_baseline():
    for fname in ("main.py", "deck.csv"):
        root_f = ROOT / fname
        base_f = BASELINE / fname
        assert root_f.exists() and base_f.exists(), f"missing {fname}"
        assert filecmp.cmp(root_f, base_f, shallow=False), f"{fname} drifted from v1 baseline"


# -- Mega is never a benchable Basic -----------------------------------------

def test_benchable_basic_excludes_mega(playbook):
    ri = load_playbook_roles(playbook)
    assert _is_benchable_basic(KYOGRE, ri) is True
    assert _is_benchable_basic(SNOVER, ri) is True
    assert _is_benchable_basic(MEGA_ABOMASNOW, ri) is False


# -- ctx38 deckout draw-count guard: clamp only at low deck ------------------

def test_drawcount_guard_clamps_only_at_low_deck(playbook):
    # Healthy deck -> take the maximum offered (never throttle tempo).
    r = choose_draw_count([{"number": 1}, {"number": 5}, {"number": 7}],
                          {"deck_count": 40}, playbook)
    assert r["action_kind"] == "draw_count" and r["chosen_number"] == 7

    # Low deck -> clamp to the largest draw that keeps >= 1 card in deck.
    r = choose_draw_count([{"number": 1}, {"number": 2}, {"number": 5}],
                          {"deck_count": 3}, playbook)
    assert r["chosen_number"] == 2

    # Critically low -> minimal draw when nothing keeps the deck non-empty.
    r = choose_draw_count([{"number": 1}, {"number": 2}, {"number": 3}],
                          {"deck_count": 1}, playbook)
    assert r["chosen_number"] == 1

    # Unknown deck size -> default to the maximum offered (no over-clamping).
    r = choose_draw_count([{"number": 2}, {"number": 5}], {}, playbook)
    assert r["chosen_number"] == 5


def test_deckout_guard_does_not_suppress_attack(playbook):
    # dko_05: even at a low deck a Main action with an attack must still attack.
    board = {"active": {"card_id": KYOGRE, "hp": 200},
             "bench": [{"card_id": SNOVER, "hp": 90}], "deck_count": 6}
    options = [{"card_id": KYOGRE, "is_attack": True},
               {"card_id": 1219}]  # generic optional trainer
    r = choose_main_action(options, board, playbook)
    assert r["action_kind"] == "attack"


# -- ctx7 prize-liability pivot: fires only without a 1-prize attacker -------

def test_prize_pivot_fetches_backup_attacker_when_lone_mega(prize_on_playbook):
    # Bench is non-empty (a second Mega), so the bench-empty anti-disruption
    # pivot stays inert and THIS lever is the one under test (mirrors plv_01).
    board = {"active": {"card_id": MEGA_ABOMASNOW},
             "bench": [{"card_id": MEGA_ABOMASNOW}]}
    options = [{"card_id": KYOGRE}, {"card_id": SNOVER}]
    r = choose_to_hand(options, board, prize_on_playbook)
    assert r.get("chosen_card_id") == KYOGRE
    assert "prize-liability" in (r.get("rationale") or "")


def test_prize_pivot_does_not_redirect_when_primary_in_play(prize_on_playbook):
    # A 1-prize Kyogre is already in play -> the guard must NOT redirect; it
    # never broadly blocks/avoids the Mega line.
    board = {"active": {"card_id": KYOGRE}, "bench": [{"card_id": MEGA_ABOMASNOW}]}
    options = [{"card_id": SNOVER}, {"card_id": MEGA_ABOMASNOW}]
    r = choose_to_hand(options, board, prize_on_playbook)
    assert "prize-liability" not in (r.get("rationale") or "")


def test_prize_pivot_inert_when_flag_off(playbook):
    # Non-empty bench (so anti-disruption stays inert too): with the flag OFF the
    # prize-liability lever must never engage.
    board = {"active": {"card_id": MEGA_ABOMASNOW},
             "bench": [{"card_id": MEGA_ABOMASNOW}]}
    options = [{"card_id": KYOGRE}, {"card_id": SNOVER}]
    r = choose_to_hand(options, board, playbook)
    assert "prize-liability" not in (r.get("rationale") or "")


# -- fixtures: real ids + grade exactly as authored -------------------------

def _iter_card_ids(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "card_id" and isinstance(v, int) and not isinstance(v, bool):
                yield v
            else:
                yield from _iter_card_ids(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from _iter_card_ids(x)


def _fixture_names():
    assert yaml is not None
    index = yaml.safe_load((FIXTURE_DIR / "index.yaml").read_text())
    return list(index["fixtures"])


def test_fixtures_reference_only_real_card_ids(playbook):
    known = set(int(k) for k in playbook["cards"].keys())
    seen = set()
    for name in _fixture_names():
        fx = _load(FIXTURE_DIR / name)
        for cid in _iter_card_ids(fx):
            assert cid in known, f"{name}: invented/unknown card id {cid}"
            seen.add(cid)
    assert seen, "expected at least one card id across fixtures"


@pytest.mark.parametrize("name", _fixture_names() if yaml is not None else [])
def test_fixture_grades_as_expected(name, playbook, prize_on_playbook):
    fx = _load(FIXTURE_DIR / name)
    pb = (prize_on_playbook
          if fx.get("requires_flag") == "prize_liability_search_pivot"
          else playbook)
    r = decide(fx["kind"], fx["board"], fx["options"], pb)
    for key, want in fx["expect"].items():
        if key == "chosen_card_ids":
            assert (r.get("chosen_card_ids") or []) == want, f"{name}: {key}"
        else:
            assert r.get(key) == want, f"{name}: {key} -> {r.get(key)} != {want}"


# -- replay loss-windows present + cover the attributed episodes -------------

def test_loss_windows_present_and_cover_episodes():
    lines = [ln for ln in (EXP / "pass25_loss_windows.jsonl").read_text().splitlines()
             if ln.strip()]
    assert len(lines) == 3
    recs = [json.loads(ln) for ln in lines]
    assert {r["episode_id"] for r in recs} == set(EPISODES)
    assert {"prize_liability", "deckout", "positive_control"} <= {r["seam"] for r in recs}


# -- live-score helpers: string coercion + active-control selection ----------

_SUBS_CSV = (
    "fileName,date,description,status,publicScore,privateScore\n"
    "submission.tar.gz,2026-06-17 19:37:48,x,complete,363.0,\n"
    "league_water_anti_disruption_pivot_v1.tar.gz,2026-06-19 07:22:39,x,complete,358.7,\n"
    "broken.tar.gz,2026-06-10 00:00:00,x,error,,\n"
    "pending.tar.gz,2026-06-10 00:00:00,x,pending,,\n"
)


@pytest.mark.skipif(live_score is None, reason="live-score registry helpers unavailable")
def test_string_public_score_coerced_to_float():
    rows = {r["filename"]: r for r in live_score.parse_submissions_csv(_SUBS_CSV)}
    top = rows["submission.tar.gz"]["public_score"]
    assert isinstance(top, float) and top == 363.0
    # An empty/non-numeric score coerces to None instead of raising.
    assert rows["broken.tar.gz"]["public_score"] is None


@pytest.mark.skipif(live_score is None, reason="live-score registry helpers unavailable")
def test_active_control_is_highest_complete_score():
    active = live_score.select_active_control(live_score.parse_submissions_csv(_SUBS_CSV))
    assert active is not None
    assert active["filename"] == "submission.tar.gz"
    assert active["public_score"] == 363.0


def test_live_status_active_control_matches_highest_rule():
    st = _load(EXP / "pass25_live_score_status.json")
    ranked = st["complete_submissions_ranked"]
    top = max(ranked, key=lambda e: float(e["publicScore"]))
    acr = st["active_control_live_rule"]
    assert acr["fileName"] == top["fileName"]
    assert float(acr["publicScore"]) == max(float(e["publicScore"]) for e in ranked)
    assert st.get("upload_performed") is False and st.get("read_only") is True


# -- recovery ids validated yet blocked pre-build ---------------------------

def test_recovery_ids_validated_real_and_blocked():
    rec = _load(EXP / "pass25_recovery_evaluation.json")
    assert rec["all_ids_real"] is True
    assert rec["ids_validated"], "expected validated ids"
    for item in rec["ids_validated"]:
        assert item["found"] is True and item["real_id"] is True
    assert rec["decision"] == "blocked_pre_build"
    assert rec.get("no_upload") is True
    # No recovery angle leaked into a built candidate.
    for cand in CANDIDATES:
        assert "recover" not in cand


# -- candidate tarballs: top-level only + entrypoint + runtime contexts ------

@pytest.mark.parametrize("cand", CANDIDATES)
def test_tarball_top_level_only(cand):
    tb = CAND_DIR / f"{cand}.tar.gz"
    assert tb.exists(), f"missing tarball {tb}"
    with tarfile.open(tb, "r:gz") as t:
        names = [m.name for m in t.getmembers() if m.isfile()]
    tops = sorted(n.lstrip("./") for n in names)
    assert tops == ["deck.csv", "main.py"], f"{cand}: unexpected members {tops}"


@pytest.mark.parametrize("cand", CANDIDATES)
def test_entrypoint_validator_passes(cand):
    res = subprocess.run(
        [sys.executable, "scripts/validate_candidate_entrypoint.py",
         "--smoke", str(CAND_DIR / f"{cand}.tar.gz")],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert res.returncode == 0, f"{cand} entrypoint validator failed: {res.stderr[-800:]}"


def _runtime_contexts(tarball: Path):
    import re
    with tarfile.open(tarball, "r:gz") as t:
        member = next(m for m in t.getmembers() if m.name.endswith("main.py"))
        src = t.extractfile(member).read().decode()
    m = re.search(r"_CP_RUNTIME_CONTEXTS\s*=\s*\(([^)]*)\)", src)
    assert m, f"_CP_RUNTIME_CONTEXTS not found in {tarball.name}"
    return set(int(x) for x in m.group(1).replace(" ", "").split(",") if x != "")


def test_runtime_contexts_match_manifest_and_ctx38_wiring():
    by_id = {c["candidate_id"]: c for c in _load(MANIFEST)["candidates"]}
    for cand in CANDIDATES:
        ctxs = _runtime_contexts(CAND_DIR / f"{cand}.tar.gz")
        assert ctxs == set(by_id[cand]["runtime_contexts"]), f"{cand}: ctx drift"
    # The ctx38 draw-count clamp is wired on deckout + hybrid only.
    assert 38 in _runtime_contexts(CAND_DIR / "deckout_guard_v1.tar.gz")
    assert 38 in _runtime_contexts(CAND_DIR / "hybrid_guard_v1.tar.gz")
    assert 38 not in _runtime_contexts(CAND_DIR / "prize_liability_guard_v1.tar.gz")


# -- no upload / read-only across manifest + events -------------------------

def test_manifest_and_pass25_events_no_upload():
    manifest = _load(MANIFEST)
    assert manifest.get("no_upload") is True
    assert manifest.get("upload_performed") is False
    assert manifest.get("github_push_performed") is False

    pass25_events = 0
    for line in LAB_EVENTS.read_text().splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        payload = ev.get("payload", {})
        if "pass25" in (ev.get("tags") or []) or payload.get("pass") in (25, "25"):
            pass25_events += 1
            nu = payload.get("no_upload")
            if nu is None:
                nu = ev.get("no_upload")
            assert nu is True, f"event {ev.get('event_type')} has no_upload != true"
    assert pass25_events >= 1, "expected at least one Pass 25 event"


# -- honest surrogate / local caveat in the report --------------------------

def test_report_includes_surrogate_and_no_upload_caveat():
    report = REPORT.read_text().lower()
    assert "surrogate" in report
    assert "directional" in report or "do not" in report or "does not" in report
    assert "no upload" in report or "no-upload" in report or "no_upload" in report
