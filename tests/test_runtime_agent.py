"""End-to-end safety tests for the runtime decision cascade and main.py."""

import importlib.util
from pathlib import Path

from ptcg_activegraph.runtime.agent_core import choose, make_agent


def test_choose_returns_legal_for_simple_obs():
    obs = {"select": {"options": ["End turn", "Attack 90 damage"], "maxCount": 1}}
    result = choose(obs)
    assert result == [1]  # the attack


def test_choose_empty_when_no_options():
    assert choose({"select": {"options": [], "maxCount": 0}}) == []
    assert choose({}) == []
    assert choose(None) == []


def test_make_agent_never_raises_on_garbage():
    agent = make_agent()
    for garbage in [None, 42, "x", {"select": 1}, {"select": {"options": 3}},
                    {"select": {"options": ["a"], "maxCount": "bad"}}]:
        result = agent(garbage)
        assert isinstance(result, list)
        assert all(isinstance(i, int) for i in result)


def test_choose_respects_max_count():
    obs = {"select": {"options": ["a", "b", "c", "d"], "maxCount": 2}}
    result = choose(obs)
    assert len(result) <= 2
    assert all(0 <= i < 4 for i in result)


def test_main_module_agent_is_safe():
    # Load main.py directly and exercise its agent().
    main_path = Path(__file__).resolve().parent.parent / "main.py"
    spec = importlib.util.spec_from_file_location("ptcg_main", main_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.agent(None) == []
    assert module.agent({}) == []
    result = module.agent(
        {"select": {"options": ["End turn", "Knock out active"], "maxCount": 1}}
    )
    assert result == [1]
    # Garbage never crashes.
    for g in [42, "x", {"select": {"options": ["a"], "maxCount": "bad"}}]:
        assert isinstance(module.agent(g), list)
