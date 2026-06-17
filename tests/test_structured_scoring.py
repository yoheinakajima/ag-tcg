"""Tests for schema-informed structured option scoring in main.py.

These exercise the cabt numeric-field scoring added on top of the string
scorer, plus the safety invariants that must survive any scoring change.
"""

import importlib.util
from pathlib import Path

import pytest

MAIN_PATH = Path(__file__).resolve().parent.parent / "main.py"


@pytest.fixture(scope="module")
def main_mod():
    spec = importlib.util.spec_from_file_location("ptcg_main_structured", MAIN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_attack_type_outranks_pass(main_mod):
    # type 13 = attack, type 14 = observed turn-ending/pass-like.
    obs = {"select": {"option": [{"type": 14}, {"type": 13, "attackId": 7}], "maxCount": 1}}
    assert main_mod.agent(obs) == [1]


def test_attack_type_outranks_common_action(main_mod):
    obs = {
        "select": {
            "option": [
                {"type": 8, "area": 2, "index": 0, "inPlayArea": 4, "inPlayIndex": 0},
                {"type": 13, "attackId": 1},
            ],
            "maxCount": 1,
        }
    }
    assert main_mod.agent(obs) == [1]


def test_attackid_adds_bonus(main_mod):
    with_id = main_mod._structured_score({"type": 13, "attackId": 4})
    without_id = main_mod._structured_score({"type": 13})
    assert with_id > without_id


def test_productive_action_outranks_pass(main_mod):
    # A productive in-play action (type 8) should beat pass-like (type 14).
    obs = {
        "select": {
            "option": [{"type": 14}, {"type": 8, "area": 2, "index": 0}],
            "maxCount": 1,
        }
    }
    assert main_mod.agent(obs) == [1]


def test_all_pass_options_still_returns_one(main_mod):
    # If every option is pass-like we must still pick a legal one.
    obs = {"select": {"option": [{"type": 14}, {"type": 14}], "maxCount": 1}}
    assert main_mod.agent(obs) == [0]


def test_unknown_type_not_overpenalized(main_mod):
    # Unknown type defaults neutral; with no better option it is chosen.
    obs = {"select": {"option": [{"type": 99, "area": 1}], "maxCount": 1}}
    assert main_mod.agent(obs) == [0]


def test_structured_score_never_raises(main_mod):
    for bad in (None, 1, "x", [], {"type": "bad"}, {"type": True}, {}, {"type": None}):
        assert isinstance(main_mod._structured_score(bad), int)


def test_deck_returned_on_select_none(main_mod):
    out = main_mod.agent({"current": None, "logs": [], "select": None})
    assert isinstance(out, list)
    assert len(out) == 60
    assert all(isinstance(i, int) for i in out)


def test_real_option_examples_rank_in_range(main_mod):
    # A realistic mixed option list drawn from recorded examples.
    options = [
        {"type": 8, "area": 2, "index": 2, "inPlayArea": 4, "inPlayIndex": 0},
        {"type": 7, "index": 1},
        {"type": 14},
        {"type": 3, "area": 2, "index": 0, "playerIndex": 1},
    ]
    obs = {"select": {"option": options, "maxCount": 1}}
    out = main_mod.agent(obs)
    assert len(out) == 1
    assert 0 <= out[0] < len(options)
    # type 14 (pass) should not be the pick when productive actions exist.
    assert out[0] != 2


def test_respects_max_and_min_count_with_dicts(main_mod):
    options = [
        {"type": 8, "area": 2, "index": i, "inPlayArea": 4, "inPlayIndex": 0}
        for i in range(5)
    ]
    obs = {"select": {"option": options, "maxCount": 2, "minCount": 1}}
    out = main_mod.agent(obs)
    assert 1 <= len(out) <= 2
    assert all(0 <= i < 5 for i in out)
    assert len(set(out)) == len(out)
