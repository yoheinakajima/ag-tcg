"""Pass 22 — Water anti-disruption + emergency backup-bench guardrail tests.

Covers the 15 checks in the Pass 22 instructions (Part M, lines 492-507):
analyzer integrity, role correctness (benchable Basic excludes Mega Abomasnow ex),
the three narrow flag-gated runtime hooks (Main emergency bench, ctx7 search pivot,
ctx8 discard preservation), narrowness/legality, candidate packaging, entrypoint
validation, no-upload immutability and root immutability.
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
    choose_discard,
    choose_emergency_backup_bench,
    choose_to_hand,
)
from ptcg_activegraph.pilot.roles import load_playbook_roles  # noqa: E402

EXP = ROOT / "data" / "experiments"
REPORTS = ROOT / "data" / "reports"
FIXTURE_DIR = ROOT / "data" / "fixtures" / "pass22_water_board_safety"
PLAYBOOK = ROOT / "playbooks" / "pass22_water_anti_disruption_pivot.yaml"
TARBALL = (ROOT / "data" / "submissions" / "candidates_pass22"
           / "league_water_anti_disruption_pivot_v1.tar.gz")

KYOGRE = 721      # primary_basic_attacker (benchable)
SNOVER = 722      # setup_basic (benchable)
MEGA_ABOMASNOW = 723  # evolution_payoff (NOT benchable)
PRESENT_LOSS_EPISODE = "80592831"
MISSING_EPISODE = "80594000"


def _load(path: Path):
    return json.loads(path.read_text())


@pytest.fixture(scope="module")
def playbook():
    assert yaml is not None
    return yaml.safe_load(PLAYBOOK.read_text())


@pytest.fixture(scope="module")
def flags_off_playbook(playbook):
    pb = copy.deepcopy(playbook)
    pb["flags"] = {
        "emergency_backup_bench": False,
        "anti_disruption_search_pivot": False,
        "preserve_backup_basic_on_discard": False,
    }
    return pb


# 1. no_pokemon_loss analyzer identifies 80592831 if replay present
def test_analyzer_identifies_present_loss_episode():
    raw = ROOT / "data" / "meta_replays" / "raw" / f"{PRESENT_LOSS_EPISODE}.json"
    analysis = _load(EXP / "pass22_no_pokemon_loss_analysis.json")
    blob = json.dumps(analysis)
    if raw.exists():
        assert PRESENT_LOSS_EPISODE in blob, (
            f"{PRESENT_LOSS_EPISODE} present but missing from analysis"
        )
    windows = (EXP / "pass22_no_pokemon_loss_windows.jsonl").read_text()
    if raw.exists():
        assert PRESENT_LOSS_EPISODE in windows


# 2. analyzer handles missing 80594000 honestly
def test_analyzer_handles_missing_episode_honestly():
    raw = ROOT / "data" / "meta_replays" / "raw" / f"{MISSING_EPISODE}.json"
    assert not raw.exists(), "test assumes 80594000 raw replay is absent"
    status = _load(EXP / "pass22_replay_input_status.json")
    blob = json.dumps(status)
    assert MISSING_EPISODE in blob, "missing episode must be recorded honestly"
    # It must never appear as an analyzed window (no fabrication).
    windows = (EXP / "pass22_no_pokemon_loss_windows.jsonl").read_text()
    assert MISSING_EPISODE not in windows


# 3. benchable Basic excludes Mega Abomasnow ex
def test_benchable_basic_excludes_mega(playbook):
    ri = load_playbook_roles(playbook)
    assert _is_benchable_basic(KYOGRE, ri) is True
    assert _is_benchable_basic(SNOVER, ri) is True
    assert _is_benchable_basic(MEGA_ABOMASNOW, ri) is False


# 4. pass22 fixtures reference real episode IDs
def test_fixtures_reference_real_episodes():
    assert yaml is not None
    index = yaml.safe_load((FIXTURE_DIR / "index.yaml").read_text())
    registry = _load(ROOT / "data" / "meta_replays" / "replay_registry.json")
    known = set()
    for rec in registry.get("records", []):
        for key in ("episode_id", "EpisodeId", "episode", "id"):
            if rec.get(key) is not None:
                known.add(str(rec[key]))
                break
    # plus the no-pokemon-loss windows analysed this pass
    for line in (EXP / "pass22_no_pokemon_loss_windows.jsonl").read_text().splitlines():
        if line.strip():
            known.add(str(json.loads(line)["episode_id"]))

    grounded = 0
    for name in index["fixtures"]:
        fx = _load(FIXTURE_DIR / name)
        src = str(fx.get("source", ""))
        if src.startswith("replay_window:"):
            epid = src.split(":", 1)[1]
            assert epid in known, f"fixture {name} cites unknown episode {epid}"
            grounded += 1
    assert grounded >= 1, "expected at least one replay-grounded fixture"


# 5. main emergency backup hook plays Kyogre/Snover before optional End/tool/search
def test_emergency_backup_hook_benches_basic(playbook):
    board = {"active": {"card_id": KYOGRE, "hp": 200}, "bench": []}
    options = [{"card_id": 1145}, {"card_id": SNOVER}, {"card_id": 723}]
    res = choose_emergency_backup_bench(options, board, playbook)
    assert res.get("chosen_card_id") == SNOVER
    assert res.get("action_kind") == "emergency_backup_bench"

    # Kyogre (primary) preferred over Snover (setup) when both are benchable.
    options2 = [{"card_id": SNOVER}, {"card_id": KYOGRE}, {"card_id": 1145}]
    res2 = choose_emergency_backup_bench(options2, board, playbook)
    assert res2.get("chosen_card_id") == KYOGRE


# 6. hook does not fire when Play option cannot resolve to Basic
def test_emergency_backup_hook_skips_without_basic(playbook):
    board = {"active": {"card_id": KYOGRE, "hp": 200}, "bench": []}
    # Only a tool and the non-benchable Mega are available.
    options = [{"card_id": 1145}, {"card_id": MEGA_ABOMASNOW}, {"card_id": 1163}]
    res = choose_emergency_backup_bench(options, board, playbook)
    assert res.get("chosen_card_id") in (None,)
    assert res.get("action_kind") == "skip"

    # Bench already occupied -> not an emergency.
    board_occ = {"active": {"card_id": KYOGRE}, "bench": [{"card_id": SNOVER}]}
    res2 = choose_emergency_backup_bench(
        [{"card_id": SNOVER}], board_occ, playbook)
    assert res2.get("action_kind") == "skip"


# 7. search pivot chooses backup when bench empty
def test_search_pivot_fetches_backup_when_bench_empty(playbook):
    board = {"active": {"card_id": KYOGRE}, "bench": []}
    options = [{"card_id": 1163}, {"card_id": SNOVER}, {"card_id": 1219}]
    res = choose_to_hand(options, board, playbook)
    assert res.get("chosen_card_id") == SNOVER
    assert res.get("action_kind") == "search_to_hand"


# 8. discard preservation keeps last Kyogre/Snover when alternatives exist
def test_discard_preserves_last_backup_basic(playbook):
    board = {"discard_count": 1}
    options = [{"card_id": SNOVER}, {"card_id": 3}, {"card_id": 3}]
    res = choose_discard(options, board, playbook)
    chosen = res.get("chosen_card_ids") or [res.get("chosen_card_id")]
    assert SNOVER not in chosen, "preservation must not discard the last backup basic"
    assert 3 in chosen


# 9. forced-all discard remains legal
def test_forced_all_discard_remains_legal(playbook):
    # Need == number of options: every card must be discarded, including basics.
    board = {"discard_count": 3}
    options = [{"card_id": SNOVER}, {"card_id": KYOGRE}, {"card_id": 3}]
    res = choose_discard(options, board, playbook)
    chosen = res.get("chosen_card_ids") or [res.get("chosen_card_id")]
    assert len(chosen) == 3
    assert sorted(chosen) == sorted([SNOVER, KYOGRE, 3])


# 10. broad Main remains delegated outside emergency backup hook
def test_broad_main_delegated_when_flag_off(flags_off_playbook):
    board = {"active": {"card_id": KYOGRE}, "bench": []}
    options = [{"card_id": SNOVER}, {"card_id": 1145}]
    res = choose_emergency_backup_bench(options, board, flags_off_playbook)
    assert res.get("action_kind") == "skip", "hook must not fire with flag off"
    assert res.get("chosen_card_id") in (None,)


# 10b. runtime scope is EXACTLY the three Pass-22 hooks (no broad-Main drift)
def test_runtime_contexts_are_exactly_the_three_hooks():
    import re
    with tarfile.open(TARBALL, "r:gz") as t:
        member = next(m for m in t.getmembers() if m.name.endswith("main.py"))
        src = t.extractfile(member).read().decode()
    m = re.search(r"_CP_RUNTIME_CONTEXTS\s*=\s*\(([^)]*)\)", src)
    assert m, "_CP_RUNTIME_CONTEXTS not found in compiled candidate"
    ctxs = tuple(int(x) for x in m.group(1).replace(" ", "").split(",") if x != "")
    assert ctxs == (0, 7, 8), (
        f"runtime contexts {ctxs} drifted from the three Pass-22 hooks (0,7,8); "
        "ctx1/2/38 must fall through to the proven base policy"
    )


# 11. candidate tarball top-level only
def test_tarball_top_level_only():
    assert TARBALL.exists()
    with tarfile.open(TARBALL, "r:gz") as t:
        names = [m.name for m in t.getmembers() if m.isfile()]
    tops = sorted(n.lstrip("./") for n in names)
    assert tops == ["deck.csv", "main.py"], f"unexpected tarball members: {tops}"


# 12. entrypoint validator passes
def test_entrypoint_validator_passes():
    res = subprocess.run(
        [sys.executable, "scripts/validate_candidate_entrypoint.py",
         "--smoke", str(TARBALL)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert res.returncode == 0, f"entrypoint validator failed: {res.stderr[-800:]}"


# 13. no upload flag remains false
def test_no_upload_flag_remains_false():
    manifest = _load(ROOT / "experiments" / "runs_pass22" / "build_manifest.json")
    assert manifest.get("no_upload") is True or manifest.get("uploaded") is False

    events_path = ROOT / "data" / "activegraph" / "lab_events.jsonl"
    pass22_events = 0
    for line in events_path.read_text().splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        payload = ev.get("payload", {})
        if "pass22" in (ev.get("tags") or []) or payload.get("pass") in (22, "22"):
            pass22_events += 1
            assert payload.get("no_upload") is True, (
                f"event {ev.get('event_type')} has no_upload != true"
            )
    assert pass22_events >= 1, "expected at least one Pass 22 event"


# 14. root files unchanged
def test_root_files_unchanged():
    baseline = ROOT / "data" / "baselines" / "v1_kaggle_349_8"
    assert filecmp.cmp(ROOT / "main.py", baseline / "main.py", shallow=False), \
        "root main.py drifted"
    assert filecmp.cmp(ROOT / "deck.csv", baseline / "deck.csv", shallow=False), \
        "root deck.csv drifted"


# 15. report includes replay-derived evidence caveat
def test_report_includes_replay_evidence_caveat():
    report = (REPORTS / "pass22_water_anti_disruption_report.md").read_text().lower()
    assert "surrogate" in report, "must caveat surrogate eval is directional only"
    assert "directional" in report or "do not" in report or "does not" in report
    assert "no-upload" in report or "no upload" in report or "no_upload" in report
