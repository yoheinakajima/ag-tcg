"""Tests for option parsing, serialization and heuristic ranking."""

from ptcg_activegraph.runtime.action import option_count, parse_select, serialize_option
from ptcg_activegraph.runtime.heuristic_policy import (
    heuristic_select,
    rank_options,
    score_option,
)


def test_option_count():
    assert option_count(["a", "b", "c"]) == 3
    assert option_count("nope") == 0
    assert option_count(None) == 0


def test_serialize_unknown_objects_safely():
    assert serialize_option({"action": "Attack"}) == '{"action": "attack"}'
    assert serialize_option(None) == ""
    assert serialize_option(7) == "7"

    class Weird:
        def __repr__(self):
            return "WeirdThing"

    # Should not raise; falls back to str().
    assert "weird" in serialize_option(Weird())


def test_parse_select_builds_views():
    views = parse_select([{"type": "attack"}, "End turn"])
    assert len(views) == 2
    assert views[0].index == 0
    assert "attack" in views[0].text


def test_score_prefers_attack_over_end():
    attack = score_option(parse_select(["Attack: 90 damage"])[0])
    end = score_option(parse_select(["End turn"])[0])
    assert attack > end


def test_knockout_outranks_plain_attack():
    ranked = rank_options(["End turn", "Attack the opponent", "Knock out the active"])
    assert ranked[0] == 2  # knockout (knock+active) beats a plain attack


def test_rank_is_deterministic_tiebreak_low_index():
    # Two identical-scoring options -> lower index first.
    ranked = rank_options(["Draw a card", "Draw a card"])
    assert ranked == [0, 1]


def test_end_turn_chosen_only_when_alone():
    assert heuristic_select(["End turn"], 1) == [0]


def test_discard_with_draw_not_penalized_to_bottom():
    # "Draw 2 then discard 1" should beat a plain "End turn".
    ranked = rank_options(["End turn", "Draw 2 cards then discard 1"])
    assert ranked[0] == 1


def test_multiselect_picks_top_n():
    options = ["End turn", "Attack 90 damage", "Attach energy", "Pass"]
    result = heuristic_select(options, max_count=2)
    assert len(result) == 2
    assert result == sorted(result)
    assert 1 in result and 2 in result  # the two positive options
