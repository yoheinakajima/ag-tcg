"""ActiveGraph Pass 9 — declarative playbook architecture tests (Part L).

Covers: schema, loader, compiler, stdlib-only generated output, select=None
safety, the hard fixture gate, tarball-only packaging, report summary, chaos
skeletons carrying no invented ids, root immutability, and dry-run queue policy.
"""

from __future__ import annotations

import ast
import filecmp
import importlib.util
import json
import tarfile
from pathlib import Path

import pytest

from ptcg_activegraph.playbooks import (
    CONFIRMED_CARDS,
    REQUIRED_FIELDS,
    compile_playbook,
    compile_rules,
    load_playbook,
    playbook_report_summary,
    validate_playbook,
)
from ptcg_activegraph.playbooks.compiler import _load_deck_ids

REPO = Path(__file__).resolve().parent.parent
BASE_PLAYBOOK = REPO / "playbooks" / "v2_kyogre_abomasnow.yaml"
V2_CONTROL = REPO / "data" / "baselines" / "v2_kaggle_479_1_deck_energy_trim_light"
V1_BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
CHAOS = [
    REPO / "playbooks" / "chaos_hand_avalanche_froslass.yaml",
    REPO / "playbooks" / "chaos_bench_bloat_punisher.yaml",
]


# --------------------------------------------------------------------------- #
# schema
# --------------------------------------------------------------------------- #
def test_schema_required_fields_and_confirmed_cards():
    assert REQUIRED_FIELDS, "schema must declare required playbook fields"
    assert CONFIRMED_CARDS, "schema must declare a confirmed-card whitelist"
    # Confirmed cards map name -> int id, never invented strings.
    for name, cid in CONFIRMED_CARDS.items():
        assert isinstance(name, str) and name
        assert isinstance(cid, int)


# --------------------------------------------------------------------------- #
# loader + validator
# --------------------------------------------------------------------------- #
def test_loader_reads_base_playbook():
    pb = load_playbook(BASE_PLAYBOOK)
    assert isinstance(pb, dict)
    for field in REQUIRED_FIELDS:
        assert field in pb, f"missing required field {field!r}"


def test_validator_passes_on_base_playbook():
    pb = load_playbook(BASE_PLAYBOOK)
    deck_ids = _load_deck_ids(V2_CONTROL / "deck.csv")
    result = validate_playbook(pb, deck_ids=deck_ids)
    assert result.valid, f"base playbook should validate; errors={result.errors}"


def test_validator_rejects_invented_card_id():
    pb = load_playbook(BASE_PLAYBOOK)
    # Inject an obviously-invented id into a scanned card-bearing section.
    pb = json.loads(json.dumps(pb))  # deep copy
    pb.setdefault("cards", {})["fake_card"] = 99999999
    result = validate_playbook(pb)
    assert not result.valid
    assert any("99999999" in e or "invent" in e.lower() for e in result.errors)


# --------------------------------------------------------------------------- #
# compiler -> rules
# --------------------------------------------------------------------------- #
def test_compile_rules_matches_full_safety_combo():
    rules = compile_rules(load_playbook(BASE_PLAYBOOK))
    assert rules.get("discard_protect_setup") is True
    assert rules.get("search_avoid_orphan_evolution") is True
    assert rules.get("search_avoid_orphan_mega_signal") is True
    assert rules.get("decline_mega_signal_no_snover") is True
    assert int(rules.get("deckout_decline_threshold")) == 8


# --------------------------------------------------------------------------- #
# compiler -> candidate dir (stdlib-only, select=None safety)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def compiled_candidate(tmp_path_factory):
    runs_root = tmp_path_factory.mktemp("runs_pass9_test")
    run_dir = compile_playbook(
        str(BASE_PLAYBOOK),
        "playbook_v2_test_candidate",
        runs_root=str(runs_root),
        baseline_dir=str(V2_CONTROL),
    )
    return Path(run_dir)


def test_candidate_dir_has_expected_files(compiled_candidate):
    for name in ("main.py", "deck.csv", "playbook.yaml", "branch.yaml", "report.md"):
        assert (compiled_candidate / name).exists(), f"missing {name}"


def test_generated_main_is_stdlib_only(compiled_candidate):
    src = (compiled_candidate / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(src)  # must parse
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert not mod.startswith("ptcg_activegraph"), f"src import: {mod}"
            assert mod != "src" and not mod.startswith("src."), f"src import: {mod}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("ptcg_activegraph")
                assert alias.name != "src" and not alias.name.startswith("src.")


def _load_agent(main_path: Path):
    spec = importlib.util.spec_from_file_location("pass9_cand_main", main_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generated_agent_returns_list_and_handles_none(compiled_candidate):
    mod = _load_agent(compiled_candidate / "main.py")
    assert hasattr(mod, "agent")
    # Empty / None observation must not raise and must return a list.
    for obs in ({}, {"legal_moves": []}, {"select": None}):
        out = mod.agent(obs)
        assert isinstance(out, list)


def test_generated_deck_matches_baseline(compiled_candidate):
    assert filecmp.cmp(compiled_candidate / "deck.csv", V2_CONTROL / "deck.csv",
                       shallow=False), "candidate deck.csv must equal baseline deck"


# --------------------------------------------------------------------------- #
# report summary
# --------------------------------------------------------------------------- #
def test_report_summary_serializable():
    summary = playbook_report_summary(load_playbook(BASE_PLAYBOOK))
    json.dumps(summary)  # must be JSON-serializable
    assert summary


# --------------------------------------------------------------------------- #
# hard fixture gate artifact
# --------------------------------------------------------------------------- #
def test_hard_fixture_gate_results_present_and_consistent():
    gate = REPO / "data" / "experiments" / "pass9_fixture_gate.json"
    if not gate.exists():
        pytest.skip("fixture gate not yet produced")
    data = json.loads(gate.read_text(encoding="utf-8"))
    rows = data.get("results") or data.get("candidates") or []
    assert rows, "gate must grade candidates"
    for row in rows:
        # promotable iff loaded and no hard failures.
        if "promotable_gate" in row:
            expected = bool(row.get("loaded", True)) and not row.get("hard_failures")
            assert bool(row["promotable_gate"]) == expected


# --------------------------------------------------------------------------- #
# tarball-only packaging
# --------------------------------------------------------------------------- #
def test_v2_control_tarball_contains_only_main_and_deck():
    tgz = V2_CONTROL / "submission.tar.gz"
    if not tgz.exists():
        pytest.skip("control tarball not present")
    with tarfile.open(tgz, "r:gz") as tf:
        names = sorted(Path(n).name for n in tf.getnames()
                       if not n.endswith("/"))
    assert names == ["deck.csv", "main.py"], f"tarball must be main+deck only: {names}"


# --------------------------------------------------------------------------- #
# chaos skeletons carry no invented ids
# --------------------------------------------------------------------------- #
def test_chaos_skeletons_blocked_and_no_invented_ids():
    confirmed = {103, 104, 861} | set(CONFIRMED_CARDS.values())
    for path in CHAOS:
        assert path.exists(), f"missing chaos skeleton {path}"
        pb = load_playbook(path)
        status = str(pb.get("status", "")).lower()
        assert status in {"blocked", "not_ready", "draft"}, \
            f"{path.name} must declare a blocked/not-ready status"

        def _walk_ids(obj):
            if isinstance(obj, dict):
                for v in obj.values():
                    yield from _walk_ids(v)
            elif isinstance(obj, list):
                for v in obj:
                    yield from _walk_ids(v)
            elif isinstance(obj, int) and not isinstance(obj, bool):
                yield obj

        for cid in _walk_ids(pb):
            # Thresholds/counts are small; card-scale ids must be confirmed.
            if cid >= 100:
                assert cid in confirmed, f"{path.name}: unconfirmed id {cid}"


# --------------------------------------------------------------------------- #
# root immutability
# --------------------------------------------------------------------------- #
def test_root_main_and_deck_unchanged_vs_v1_baseline():
    if not V1_BASELINE.exists():
        pytest.skip("v1 baseline snapshot not present")
    assert filecmp.cmp(REPO / "main.py", V1_BASELINE / "main.py", shallow=False)
    assert filecmp.cmp(REPO / "deck.csv", V1_BASELINE / "deck.csv", shallow=False)


# --------------------------------------------------------------------------- #
# dry-run queue policy
# --------------------------------------------------------------------------- #
def test_dry_run_queue_respects_no_more_submissions_today():
    q = REPO / "data" / "submission_queue.json"
    if not q.exists():
        pytest.skip("queue not produced")
    doc = json.loads(q.read_text(encoding="utf-8"))
    assert doc.get("upload_performed") is False
    if doc.get("no_more_submissions_today") is True:
        assert doc.get("queued_candidate_count", 0) == 0
        assert doc.get("queue") == []
