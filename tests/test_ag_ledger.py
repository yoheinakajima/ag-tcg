"""Tests for the ActiveGraph ledger adapter (Pass 7A, Part D)."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

from ptcg_activegraph.ag import ActiveGraphLedger, FallbackJSONLLedger
from ptcg_activegraph.ag import adapter as adapter_mod


def _ledger(tmp_path: Path) -> ActiveGraphLedger:
    return ActiveGraphLedger(
        events_path=tmp_path / "events.jsonl",
        runs_path=tmp_path / "runs.json",
        artifacts_root=tmp_path / "artifacts",
        warn=False,
    )


def test_create_run(tmp_path):
    led = _ledger(tmp_path)
    led.create_run("r1", {"purpose": "smoke"})
    runs = led.list_runs()
    assert [r["run_id"] for r in runs] == ["r1"]
    assert runs[0]["metadata"] == {"purpose": "smoke"}
    # creating again is idempotent on the index (no duplicate run rows)
    led.create_run("r1", {"purpose": "smoke"})
    assert len(led.list_runs()) == 1


def test_append_event_returns_id_and_persists(tmp_path):
    led = _ledger(tmp_path)
    led.create_run("r1")
    eid = led.append_event("r1", "GamePlanned", {"game_id": "g1"}, tags=["plan"])
    assert eid.startswith("evt_")
    summary = led.inspect_run("r1")
    assert summary["events_by_type"]["GamePlanned"] == 1
    assert summary["game_status"]["g1"] == "planned"


def test_heartbeat_run_and_game(tmp_path):
    led = _ledger(tmp_path)
    led.create_run("r1")
    led.heartbeat("r1")  # run-level
    led.heartbeat("r1", object_id="g1")  # game-level
    summary = led.inspect_run("r1")
    assert summary["events_by_type"]["ExperimentRunHeartbeat"] == 1
    assert summary["events_by_type"]["GameHeartbeat"] == 1
    assert summary["last_heartbeat_at"] is not None


def test_inspect_status_transitions(tmp_path):
    led = _ledger(tmp_path)
    led.create_run("r1")
    assert led.inspect_run("r1")["status"] == "created"
    led.append_event("r1", "ExperimentRunStarted", {})
    assert led.inspect_run("r1")["status"] == "running"
    led.append_event("r1", "ExperimentRunFinished", {})
    assert led.inspect_run("r1")["status"] == "completed"


def test_export_trace_only_this_run(tmp_path):
    led = _ledger(tmp_path)
    led.create_run("r1")
    led.create_run("r2")
    led.append_event("r1", "GamePlanned", {"game_id": "g1"})
    led.append_event("r2", "GamePlanned", {"game_id": "gz"})
    out = led.export_trace("r1", tmp_path / "trace.jsonl")
    assert out.exists()
    lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
    assert {l["run_id"] for l in lines} == {"r1"}
    assert any(l["event_type"] == "GamePlanned" for l in lines)


def test_mark_artifact_records_path(tmp_path):
    led = _ledger(tmp_path)
    led.create_run("r1")
    art = tmp_path / "result.json"
    art.write_text("{}")
    aid = led.mark_artifact("r1", "game_result", art, metadata={"k": "v"})
    assert aid.startswith("art_")
    summary = led.inspect_run("r1")
    assert summary["events_by_type"]["ArtifactRecorded"] == 1
    # the artifact path is captured on the event envelope
    assert any("result.json" in p for p in summary["artifact_paths"])


def test_list_runs_sorted_by_created(tmp_path):
    led = _ledger(tmp_path)
    led.create_run("a")
    led.create_run("b")
    ids = [r["run_id"] for r in led.list_runs()]
    assert ids == ["a", "b"]


def test_fallback_mode_when_activegraph_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter_mod, "real_activegraph_available", lambda: False)
    led = ActiveGraphLedger(
        events_path=tmp_path / "e.jsonl",
        runs_path=tmp_path / "r.json",
        warn=False,
    )
    assert isinstance(led.backend, FallbackJSONLLedger)
    assert led.is_fallback is True
    assert led.backend_name == "fallback_jsonl"


def test_fallback_warning_emitted(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter_mod, "real_activegraph_available", lambda: False)
    monkeypatch.setattr(adapter_mod, "_warned_once", False)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ActiveGraphLedger(events_path=tmp_path / "e.jsonl", runs_path=tmp_path / "r.json")
    assert any("fallback JSONL ledger" in str(w.message) for w in caught)


def test_real_backend_not_bypassed_when_available(tmp_path, monkeypatch):
    """If a real backend is injected, the adapter must route to it, not the fallback."""

    class _RecordingBackend:
        backend_name = "fake_real"
        is_real_activegraph = True

        def __init__(self):
            self.calls = []

        def create_run(self, run_id, metadata=None):
            self.calls.append(("create_run", run_id))

        def append_event(self, run_id, event_type, payload=None, tags=None,
                         artifact_paths=None, parent_event_ids=None):
            self.calls.append(("append_event", run_id, event_type))
            return "evt_fake"

        def heartbeat(self, run_id, object_id=None, payload=None):
            self.calls.append(("heartbeat", run_id))

        def inspect_run(self, run_id):
            return {"run_id": run_id, "via": "fake_real"}

        def export_trace(self, run_id, output_path):
            return Path(output_path)

        def list_runs(self):
            return [{"run_id": "x"}]

        def mark_artifact(self, run_id, artifact_type, path, metadata=None):
            self.calls.append(("mark_artifact", run_id))
            return "art_fake"

    fake = _RecordingBackend()
    led = ActiveGraphLedger(backend=fake)
    assert led.is_fallback is False
    assert led.backend_name == "fake_real"
    led.create_run("r1", {})
    eid = led.append_event("r1", "GamePlanned", {})
    assert eid == "evt_fake"
    assert led.inspect_run("r1")["via"] == "fake_real"
    assert ("create_run", "r1") in fake.calls
    assert ("append_event", "r1", "GamePlanned") in fake.calls


def test_auto_detect_uses_fallback_in_this_env(tmp_path):
    # No real activegraph package is installed in this environment.
    led = ActiveGraphLedger(
        events_path=tmp_path / "e.jsonl", runs_path=tmp_path / "r.json", warn=False
    )
    assert led.is_fallback is True
