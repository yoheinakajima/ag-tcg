"""Tests for defensive observation parsing."""

from ptcg_activegraph.runtime.observation import parse_observation


def test_handles_none():
    p = parse_observation(None)
    assert p.options == []
    assert p.max_count == 0
    assert p.has_choice is False
    assert p.legal_indices == []


def test_handles_non_dict():
    p = parse_observation(42)
    assert p.num_options == 0


def test_missing_current_ok():
    p = parse_observation({"select": {"options": ["a", "b"], "maxCount": 1}})
    assert p.current is None
    assert p.num_options == 2
    assert p.has_choice is True


def test_missing_select_ok():
    p = parse_observation({"current": {"foo": 1}})
    assert p.select is None
    assert p.num_options == 0
    assert p.has_choice is False


def test_malformed_options():
    p = parse_observation({"select": {"options": "not a list", "maxCount": 2}})
    assert p.options == []
    assert p.max_count == 0


def test_default_maxcount_is_one_when_options_present():
    p = parse_observation({"select": {"options": ["a", "b"]}})
    assert p.max_count == 1


def test_maxcount_clamped_to_options():
    p = parse_observation({"select": {"options": ["a", "b"], "maxCount": 10}})
    assert p.max_count == 2


def test_mincount_not_above_maxcount():
    p = parse_observation(
        {"select": {"options": ["a", "b", "c"], "maxCount": 1, "minCount": 3}}
    )
    assert p.min_count <= p.max_count


def test_legal_indices():
    p = parse_observation({"select": {"options": ["a", "b", "c"], "maxCount": 2}})
    assert p.legal_indices == [0, 1, 2]
