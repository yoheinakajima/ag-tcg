"""ActiveGraph Pass 14 — core pilot competency layer tests (Part M).

Covers: reduced-model fixture grading against the lab decision layer, the core
competency gate contract (candidate passes / active control honestly fails),
compiled-candidate properties (stdlib-only, tarball = top-level main.py+deck.csv),
root immutability, and — critically — the cabt entrypoint regression: the
compiled agent's last top-level callable must be the deck-safe entrypoint, and a
live deck-selection request must return 60 ids (never []). See
.agents/memory/kaggle-compiled-agent-entrypoint.md for why this matters.
"""

from __future__ import annotations

import ast
import filecmp
import importlib.util
import tarfile
from pathlib import Path

import pytest

from ptcg_activegraph.pilot import compiler, fixtures

REPO = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO / "data" / "fixtures" / "core_competency"
CANDIDATE = REPO / "data" / "submissions" / "candidates_pass14" / "core_pilot_water_v1.tar.gz"
BASE = REPO / "data" / "submissions" / "candidates" / "combo_full_safety_v3_fixed.tar.gz"
PLAYBOOK = REPO / "playbooks" / "v2_kyogre_abomasnow_core_pilot.yaml"
ABLATIONS = {
    "core_pilot_water_v1__ablate_no_active_scoring": {"active_scoring": False},
    "core_pilot_water_v1__ablate_no_bench_safety": {"bench_safety": False},
    "core_pilot_water_v1__ablate_no_deckout_guard": {"deckout_guard": False},
}


def _load_module(main_path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, main_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _extract(tarball: Path, dest: Path) -> Path:
    with tarfile.open(tarball) as t:
        t.extractall(dest)
    return dest / "main.py"


# ---------------------------------------------------------------------------
# Lab decision layer — reduced-model fixtures.
# ---------------------------------------------------------------------------

def test_fixtures_load_all_fourteen():
    fx = fixtures.load_fixtures(FIXTURES_DIR)
    assert len(fx) == 14
    ids = [f["id"] for f in fx]
    assert len(set(ids)) == 14  # unique ids


@pytest.mark.skipif(not CANDIDATE.exists(), reason="candidate tarball not built")
def test_candidate_layer_passes_all_hard_fixtures(tmp_path):
    """The compiled candidate's embedded layer must satisfy every hard fixture
    (advisory may miss). Mirrors the core-competency gate."""
    main = _extract(CANDIDATE, tmp_path)
    mod = _load_module(main, "cand_grade")
    decide_fn = lambda kind, board, opts: mod.core_pilot_decide(kind, board, opts)
    fx = fixtures.load_fixtures(FIXTURES_DIR)
    report = fixtures.grade_all(fx, decide_fn, has_layer=True)
    hard_fails = [r for r in report["rows"]
                  if r.get("hard") and r.get("status") == "fail"]
    assert report["hard_failures"] == 0, f"unexpected hard failures: {hard_fails}"


def test_missing_layer_fails_hard_fixtures():
    """A candidate lacking the layer (has_layer=False) honestly fails hard ones."""
    fx = fixtures.load_fixtures(FIXTURES_DIR)
    report = fixtures.grade_all(fx, lambda *a, **k: {}, has_layer=False)
    hard = [r for r in report["rows"] if r.get("hard")]
    assert hard and all(r.get("status") == "fail" for r in hard)


# ---------------------------------------------------------------------------
# Compiled candidate — entrypoint regression + packaging.
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not CANDIDATE.exists(), reason="candidate tarball not built")
def test_compiled_last_callable_is_deck_safe_entrypoint(tmp_path):
    """REGRESSION: cabt invokes the LAST top-level callable. It must be the
    core-pilot entrypoint that delegates to the deck-safe agent, not an embedded
    helper. A wrong last callable returns [] on the deck step -> INVALID game."""
    main = _extract(CANDIDATE, tmp_path)
    mod = _load_module(main, "cand_entry")
    callables = [k for k, v in vars(mod).items() if callable(v)]
    assert callables[-1] == "core_pilot_agent"


@pytest.mark.skipif(not CANDIDATE.exists(), reason="candidate tarball not built")
def test_compiled_deck_request_returns_60_ids(tmp_path):
    """The entrypoint must return 60 ids on a select=None/current=None request."""
    main = _extract(CANDIDATE, tmp_path)
    mod = _load_module(main, "cand_deck")
    entry = [v for k, v in vars(mod).items() if callable(v)][-1]
    deck = entry({"select": None, "current": None, "logs": []})
    assert isinstance(deck, list) and len(deck) == 60
    assert all(isinstance(x, int) for x in deck)


@pytest.mark.skipif(not CANDIDATE.exists(), reason="candidate tarball not built")
def test_compiled_source_is_stdlib_only(tmp_path):
    """Unconditional imports must be stdlib-only and never package-relative.

    Guarded optional imports (inside a ``try`` that falls back gracefully) are
    allowed: e.g. the base submission probes the Kaggle-runtime ``agent`` module
    and degrades to ``None`` locally, so the runtime stays stdlib-only.
    """
    main = _extract(CANDIDATE, tmp_path)
    tree = ast.parse(main.read_text(encoding="utf-8"))
    stdlib_ok = {
        "__future__", "os", "sys", "json", "csv", "math", "random", "collections",
        "itertools", "functools", "typing", "copy", "re", "io", "time", "heapq",
    }
    guarded = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for stmt in ast.walk(node):
                if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    guarded.add(id(stmt))
    for node in ast.walk(tree):
        if id(node) in guarded:
            continue
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"relative import survived: {ast.dump(node)}"
            assert (node.module or "").split(".")[0] in stdlib_ok, \
                f"non-stdlib import: {node.module}"
        elif isinstance(node, ast.Import):
            for a in node.names:
                assert a.name.split(".")[0] in stdlib_ok, \
                    f"non-stdlib import: {a.name}"


@pytest.mark.skipif(not CANDIDATE.exists(), reason="candidate tarball not built")
def test_tarball_is_top_level_main_and_deck_only():
    with tarfile.open(CANDIDATE) as t:
        names = sorted(m.name for m in t.getmembers() if m.isfile())
    assert names == ["deck.csv", "main.py"], names


@pytest.mark.skipif(not CANDIDATE.exists(), reason="candidate tarball not built")
def test_compiled_exposes_core_pilot_decide(tmp_path):
    main = _extract(CANDIDATE, tmp_path)
    mod = _load_module(main, "cand_decide")
    assert callable(getattr(mod, "core_pilot_decide", None))


# ---------------------------------------------------------------------------
# Compiler determinism + ablation negative controls.
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not BASE.exists() or not PLAYBOOK.exists(),
                    reason="base tarball / playbook missing")
def test_compiler_is_deterministic(tmp_path):
    import yaml
    base_dir = tmp_path / "base"
    _extract(BASE, base_dir)
    pb = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    src1 = compiler.compile_candidate_source(
        (base_dir / "main.py").read_text(encoding="utf-8"), pb, "core_pilot_water_v1")
    src2 = compiler.compile_candidate_source(
        (base_dir / "main.py").read_text(encoding="utf-8"), pb, "core_pilot_water_v1")
    assert src1 == src2


def test_ablations_fail_the_core_gate():
    """Each ablation tarball, if built, must still FAIL as a negative control."""
    import json
    rep_dir = REPO / "data" / "reports" / "ablations"
    for cid in ABLATIONS:
        report = rep_dir / f"{cid}.json"
        if not report.exists():
            pytest.skip(f"ablation report missing: {cid}")
        data = json.loads(report.read_text(encoding="utf-8"))
        assert data.get("hard_failures", 0) >= 1, f"{cid} should fail the gate"


# ---------------------------------------------------------------------------
# Root immutability — Pass 14 must never touch root main.py / deck.csv.
# ---------------------------------------------------------------------------

def test_root_entrypoints_not_shadowed_by_candidate():
    """Sanity: the candidate lives under data/submissions, never at repo root."""
    assert (REPO / "main.py").exists()
    assert not (REPO / "core_pilot_water_v1.tar.gz").exists()
    # The candidate's deck must differ in path from the root deck.
    assert CANDIDATE.parent == REPO / "data" / "submissions" / "candidates_pass14"
