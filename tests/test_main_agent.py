"""Tests directly against main.agent and its helpers (Kaggle runtime safety)."""

import importlib.util
from pathlib import Path

import pytest

MAIN_PATH = Path(__file__).resolve().parent.parent / "main.py"


@pytest.fixture(scope="module")
def main_mod():
    spec = importlib.util.spec_from_file_location("ptcg_main_under_test", MAIN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MALFORMED = [
    None,
    {},
    42,
    "string",
    [1, 2, 3],
    {"select": None},
    {"select": {}},
    {"select": {"options": None}},
    {"select": {"options": []}},
    {"select": {"options": "notalist", "maxCount": 2}},
    {"select": {"options": [{"x": 1}], "maxCount": "bad"}},
    {"select": {"options": [1, 2], "maxCount": 99}},
    {"current": None, "logs": None, "select": None},
]


def test_agent_always_returns_list_of_int(main_mod):
    for obs in MALFORMED:
        out = main_mod.agent(obs)
        assert isinstance(out, list)
        assert all(isinstance(i, int) for i in out)


def test_agent_indices_in_range(main_mod):
    obs = {"select": {"options": ["a", "b", "c"], "maxCount": 5}}
    out = main_mod.agent(obs)
    assert all(0 <= i < 3 for i in out)
    assert len(set(out)) == len(out)


def test_agent_respects_max_count(main_mod):
    obs = {"select": {"options": ["a", "b", "c", "d"], "maxCount": 2}}
    out = main_mod.agent(obs)
    assert len(out) <= 2


def test_agent_respects_min_count(main_mod):
    obs = {"select": {"options": ["a", "b", "c", "d"], "maxCount": 4, "minCount": 2}}
    out = main_mod.agent(obs)
    assert len(out) >= 2


def test_agent_empty_when_no_options(main_mod):
    assert main_mod.agent({"select": {"options": [], "maxCount": 0}}) == []
    assert main_mod.agent(None) == []
    assert main_mod.agent({}) == []


def test_agent_prefers_attack_over_end(main_mod):
    obs = {"select": {"options": ["End turn", "Attack 90 damage"], "maxCount": 1}}
    assert main_mod.agent(obs) == [1]


def test_agent_tolerates_option_singular_key(main_mod):
    # Some schemas may use "option" instead of "options".
    obs = {"select": {"option": ["End turn", "Knockout the active"], "maxCount": 1}}
    out = main_mod.agent(obs)
    assert out == [1]


def test_helpers_min_max(main_mod):
    select = {"options": ["a", "b", "c"], "maxCount": 10, "minCount": 1}
    options = main_mod._get_options(select)
    mn, mx = main_mod._get_min_max_count(select, len(options))
    assert mx == 3            # clamped to option count
    assert 0 <= mn <= mx


def test_validate_action_dedupes_and_clamps(main_mod):
    assert main_mod._validate_action([0, 0, 9, "x", 1], 3, 0, 2) == [0, 1]


def test_fallback_action(main_mod):
    assert main_mod._fallback_action(0, 0, 0) == []
    assert main_mod._fallback_action(5, 0, 1) == [0]
    assert main_mod._fallback_action(5, 0, 3) == [0, 1, 2]
