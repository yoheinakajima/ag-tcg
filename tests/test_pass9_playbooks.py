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
# deck-return safety (packaging fix): embedded deck + robust select=None
# --------------------------------------------------------------------------- #
# The cabt deck-selection step passes an observation whose current/select both
# resolve to None; on Kaggle those keys can be ABSENT (a Struct returns None but
# `"select" in obs` is False). A candidate that only checks key membership
# returns [] and Kaggle rejects it pre-game ("deck does not have 60 cards").
DECK_SELECT_OBS = [
    {"current": None, "select": None, "logs": [], "step": 0},
    {"current": None, "select": None, "logs": [], "remainingOverageTime": 60},
    {"logs": [], "step": 0},                      # Kaggle key-absent shape
    {"logs": [], "remainingOverageTime": 60},     # Kaggle key-absent shape
]


def test_generated_main_embeds_deck_constant(compiled_candidate):
    src = (compiled_candidate / "main.py").read_text(encoding="utf-8")
    assert "_EMBEDDED_DECK = [" in src, "candidate must embed a deck constant"
    assert "# === DECK-RETURN SAFETY" in src
    mod = _load_agent(compiled_candidate / "main.py")
    embedded = getattr(mod, "_EMBEDDED_DECK", None)
    assert isinstance(embedded, list) and len(embedded) == 60
    assert all(isinstance(c, int) and not isinstance(c, bool) for c in embedded)
    deck_rows = _load_deck_ids(compiled_candidate / "deck.csv")
    assert sorted(embedded) == sorted(deck_rows)


def test_generated_agent_returns_deck_on_select_none(compiled_candidate):
    mod = _load_agent(compiled_candidate / "main.py")
    deck_rows = _load_deck_ids(compiled_candidate / "deck.csv")
    for obs in DECK_SELECT_OBS:
        out = mod.agent(obs)
        assert isinstance(out, list), f"non-list for {obs}"
        assert len(out) == 60, f"expected 60 cards on deck step, got {len(out)} for {obs}"
        assert all(isinstance(c, int) and not isinstance(c, bool) for c in out)
        assert sorted(out) == sorted(deck_rows)


def test_generated_agent_returns_deck_on_struct_like_obs(compiled_candidate):
    """Kaggle's production deck-selection obs can arrive as an attribute-style
    object (not a dict). The candidate must still return its 60-card deck."""
    mod = _load_agent(compiled_candidate / "main.py")
    deck_rows = _load_deck_ids(compiled_candidate / "deck.csv")

    class _StructLike:
        def __init__(self):
            self.current = None
            self.select = None
            self.logs = []
            self.step = 0

    out = mod.agent(_StructLike())
    assert isinstance(out, list) and len(out) == 60
    assert sorted(out) == sorted(deck_rows)


def test_embedded_deck_used_when_deckcsv_missing(tmp_path):
    """With no deck.csv reachable, the agent still returns 60 via the embedded
    fallback (proves the return never depends on file I/O)."""
    from ptcg_activegraph.experiments.generator import inject_deck_safety
    root_src = (REPO / "main.py").read_text(encoding="utf-8")
    deck_rows = _load_deck_ids(V2_CONTROL / "deck.csv")
    fixed = inject_deck_safety(root_src, deck_rows)
    main_path = tmp_path / "main.py"  # deliberately NO deck.csv beside it
    main_path.write_text(fixed, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("embed_only_main", main_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = mod.agent({"logs": [], "step": 0})
    assert isinstance(out, list) and len(out) == 60
    assert sorted(out) == sorted(deck_rows)


def test_inject_deck_safety_is_idempotent():
    from ptcg_activegraph.experiments.generator import inject_deck_safety
    root_src = (REPO / "main.py").read_text(encoding="utf-8")
    deck_rows = _load_deck_ids(V2_CONTROL / "deck.csv")
    once = inject_deck_safety(root_src, deck_rows)
    twice = inject_deck_safety(once, deck_rows)
    assert once == twice
    assert once.count("# === DECK-RETURN SAFETY") == 1


# --------------------------------------------------------------------------- #
# hard candidate tarball validator gate
# --------------------------------------------------------------------------- #
def _build_tarball(tmp_path, main_text: str, deck_rows: list[int]):
    cand = tmp_path / "cand"
    cand.mkdir()
    (cand / "main.py").write_text(main_text, encoding="utf-8")
    (cand / "deck.csv").write_text(
        "\n".join(str(c) for c in deck_rows) + "\n", encoding="utf-8")
    tgz = tmp_path / "cand.tar.gz"
    with tarfile.open(tgz, "w:gz") as tar:
        tar.add(cand / "main.py", arcname="main.py")
        tar.add(cand / "deck.csv", arcname="deck.csv")
    return tgz


def _run_validator(tgz: Path) -> int:
    spec = importlib.util.spec_from_file_location(
        "vct", REPO / "scripts" / "validate_candidate_tarball.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.validate(str(tgz))


def test_validator_passes_fixed_candidate(tmp_path):
    from ptcg_activegraph.experiments.generator import inject_deck_safety
    root_src = (REPO / "main.py").read_text(encoding="utf-8")
    deck_rows = _load_deck_ids(V2_CONTROL / "deck.csv")
    tgz = _build_tarball(tmp_path, inject_deck_safety(root_src, deck_rows),
                         deck_rows)
    assert _run_validator(tgz) == 0


def test_validator_catches_empty_deck_return(tmp_path):
    """A candidate whose main.py returns [] on the Kaggle key-absent deck step
    must be FAILED by the validator (this is the exact bug that broke v3)."""
    bad_main = (
        "def agent(obs):\n"
        "    if isinstance(obs, dict) and 'select' in obs and obs['select'] is None:\n"
        "        return [1]*60\n"
        "    return []\n"
    )
    deck_rows = _load_deck_ids(V2_CONTROL / "deck.csv")
    tgz = _build_tarball(tmp_path, bad_main, deck_rows)
    assert _run_validator(tgz) == 1


def test_validator_rejects_extra_tarball_members(tmp_path):
    cand = tmp_path / "cand"
    cand.mkdir()
    (cand / "main.py").write_text("def agent(o):\n    return [1]*60\n",
                                  encoding="utf-8")
    (cand / "deck.csv").write_text("\n".join(["1"] * 60) + "\n", encoding="utf-8")
    (cand / "extra.txt").write_text("nope", encoding="utf-8")
    tgz = tmp_path / "cand.tar.gz"
    with tarfile.open(tgz, "w:gz") as tar:
        for n in ("main.py", "deck.csv", "extra.txt"):
            tar.add(cand / n, arcname=n)
    assert _run_validator(tgz) == 1


def test_candidate_smoke_imports_tarball_main_not_root():
    """The candidate smoke must operate on the extracted tarball's main.py,
    never the repo root runtime agent."""
    src = (REPO / "scripts" / "kaggle_candidate_smoke_test.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "main":
            raise AssertionError("candidate smoke must not import root main")
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "main", "candidate smoke must not import root main"
    assert "extractall" in src and "candidate_smoke_main" in src


# --------------------------------------------------------------------------- #
# fixed candidate tarball artifact (built this pass)
# --------------------------------------------------------------------------- #
def test_fixed_candidate_tarball_is_main_and_deck_only():
    tgz = REPO / "data" / "submissions" / "candidates" / \
        "combo_full_safety_v3_fixed.tar.gz"
    if not tgz.exists():
        pytest.skip("fixed candidate tarball not built")
    with tarfile.open(tgz, "r:gz") as tf:
        names = sorted(Path(n).name for n in tf.getnames() if not n.endswith("/"))
    assert names == ["deck.csv", "main.py"], f"must be main+deck only: {names}"


# --------------------------------------------------------------------------- #
# dry-run queue policy
# --------------------------------------------------------------------------- #
def test_dry_run_queue_respects_no_more_submissions_today(tmp_path):
    """Hermetic: the builder holds the queue EMPTY when no submissions remain
    today, even when an otherwise-eligible candidate exists in the ranking.

    This exercises ``build_dry_run_queue`` directly against a temp queue path and
    an explicit flag, so it never reads or clobbers the live
    ``data/submission_queue.json`` (which is written by a different generator
    with its own contract).
    """
    from ptcg_activegraph.experiments.dry_run_queue import build_dry_run_queue

    # A ranking that WOULD yield an eligible candidate if submissions remained.
    rank = {
        "stage": "test_stage",
        "control": "test_control",
        "candidates": [
            {"candidate_id": "would_be_eligible", "role": "candidate",
             "fixture_gate_status": "PASS", "promotion_label": "scout_promising",
             "adjusted_win_rate": 0.7, "games_completed": 40,
             "crashes": 0, "timeouts": 0, "stale": 0},
        ],
    }
    qp = tmp_path / "queue.json"

    # no_more_submissions_today=True -> queue held empty regardless of eligibility.
    doc = build_dry_run_queue("test_run", rank, queue_path=qp,
                              no_more_submissions_today=True)
    assert doc["upload_performed"] is False
    assert doc["auto_submit_enabled"] is False
    assert doc["require_manual_approval_for_submit"] is True
    assert doc["no_more_submissions_today"] is True
    assert doc["queued_candidate_count"] == 0
    assert doc["queue"] == []
    assert qp.exists()  # wrote to the temp path, not the live queue
    # The live queue file must be untouched by this test.
    assert qp != REPO / "data" / "submission_queue.json"


def test_dry_run_queue_empty_when_no_eligible_candidates(tmp_path):
    """Hermetic: with submissions allowed but no eligible candidates, the queue
    is empty with a recorded reason and never uploads."""
    from ptcg_activegraph.experiments.dry_run_queue import build_dry_run_queue

    rank = {"stage": "test_stage", "control": "test_control", "candidates": []}
    qp = tmp_path / "queue.json"
    doc = build_dry_run_queue("test_run", rank, queue_path=qp,
                              no_more_submissions_today=False)
    assert doc["upload_performed"] is False
    assert doc["queued_candidate_count"] == 0
    assert doc["queue"] == []
    assert "no candidates" in doc["selection_reason"]
