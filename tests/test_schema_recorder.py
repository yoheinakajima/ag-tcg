"""Tests for schema recorder pure helpers (no cabt required)."""

from ptcg_activegraph.sim.schema_recorder import (
    recording_agent,
    summarize_observations,
    write_schema_outputs,
)


def test_recording_agent_captures_observations():
    sink = []
    inner = lambda obs: [0]
    wrapped = recording_agent(inner, sink)
    wrapped({"select": {"options": ["a"], "maxCount": 1}})
    wrapped({"select": {"options": ["b", "c"], "maxCount": 1}})
    assert len(sink) == 2
    # Wrapped agent still returns the inner result.
    assert wrapped({"select": {"options": ["x"], "maxCount": 1}}) == [0]


def test_summarize_observations_collects_keys():
    obs = [
        {
            "logs": ["e1"],
            "current": {"turn": 1},
            "select": {
                "type": "play",
                "maxCount": 1,
                "options": [
                    {"action": "attack", "damage": 90},
                    {"action": "end"},
                ],
            },
        },
        {"select": {"maxCount": 2, "options": [{"action": "draw"}]}},
    ]
    summary = summarize_observations(obs)
    assert summary["observation_count"] == 2
    assert "select" in summary["top_level_keys"]
    assert "options" in summary["select_keys"]
    assert "action" in summary["option_keys"]
    assert any("attack" in k for k in summary["option_type_values"])
    assert summary["maxCount_distribution"].get("1") == 1
    assert summary["maxCount_distribution"].get("2") == 1
    assert len(summary["option_examples"]) >= 3


def test_summarize_empty():
    summary = summarize_observations([])
    assert summary["observation_count"] == 0
    assert summary["top_level_keys"] == {}


def test_write_schema_outputs(tmp_path):
    summary = summarize_observations([
        {"select": {"options": [{"action": "draw"}], "maxCount": 1}}
    ])
    paths = write_schema_outputs(summary, matches_dir=tmp_path / "m", docs_dir=tmp_path / "d")
    assert (tmp_path / "m" / "schema_examples.json").exists()
    assert (tmp_path / "m" / "option_examples.jsonl").exists()
    assert (tmp_path / "d" / "CABT_SCHEMA_NOTES.md").exists()
