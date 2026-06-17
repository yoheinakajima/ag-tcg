"""Tests for the fallback legal policy and selection clamping."""

from ptcg_activegraph.runtime.fallback_policy import clamp_selection, fallback_select


def test_no_options_returns_empty():
    assert fallback_select(0, 0) == []
    assert fallback_select(0, 3) == []
    assert fallback_select(5, 0) == []


def test_max_count_one_returns_first():
    assert fallback_select(5, 1) == [0]
    assert fallback_select(1, 1) == [0]


def test_max_count_n_returns_first_n():
    assert fallback_select(5, 3) == [0, 1, 2]
    assert fallback_select(2, 5) == [0, 1]  # clamped to available


def test_min_count_drives_multiselect():
    # With min_count, take min_count items.
    assert fallback_select(5, 4, min_count=2) == [0, 1]


def test_never_out_of_range():
    for num in range(0, 6):
        for mc in range(0, 8):
            result = fallback_select(num, mc)
            assert all(0 <= i < num for i in result)
            assert len(result) <= max(0, min(mc, num))
            assert len(set(result)) == len(result)  # unique


def test_clamp_drops_invalid_indices():
    assert clamp_selection([0, 9, "x", -1, 2], 3, 3) == [0, 2]


def test_clamp_dedupes_and_truncates():
    assert clamp_selection([0, 0, 1, 2], 5, 2) == [0, 1]


def test_clamp_pads_to_min_count():
    result = clamp_selection([], 5, 4, min_count=2)
    assert len(result) == 2
    assert all(0 <= i < 5 for i in result)


def test_clamp_empty_when_no_choice():
    assert clamp_selection([0, 1], 0, 0) == []
