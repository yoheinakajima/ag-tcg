"""Tests for the append-only JSONL event store and event model."""

from ptcg_activegraph.graph.event_store import EventStore
from ptcg_activegraph.graph.events import Event, EventType, new_event


def test_append_and_load(tmp_path):
    store = EventStore(tmp_path / "events.jsonl")
    ev = new_event(EventType.MatchStarted, match_id="m1", payload={"x": 1})
    store.append(ev)
    loaded = store.load()
    assert len(loaded) == 1
    assert loaded[0].event_type == "MatchStarted"
    assert loaded[0].match_id == "m1"
    assert loaded[0].payload == {"x": 1}


def test_append_many_and_count(tmp_path):
    store = EventStore(tmp_path / "events.jsonl")
    events = [new_event(EventType.TurnEnded, match_id="m1", turn=i) for i in range(5)]
    n = store.append_many(events)
    assert n == 5
    assert store.count() == 5


def test_filter_by_event_type(tmp_path):
    store = EventStore(tmp_path / "events.jsonl")
    store.append(new_event(EventType.MatchStarted, match_id="m1"))
    store.append(new_event(EventType.GameEnded, match_id="m1", payload={"result": "win"}))
    store.append(new_event(EventType.GameEnded, match_id="m2", payload={"result": "loss"}))

    ended = store.query(event_type=EventType.GameEnded.value)
    assert len(ended) == 2
    assert all(e.event_type == "GameEnded" for e in ended)


def test_filter_by_match_id(tmp_path):
    store = EventStore(tmp_path / "events.jsonl")
    store.append(new_event(EventType.MatchStarted, match_id="m1"))
    store.append(new_event(EventType.MatchStarted, match_id="m2"))
    assert len(store.load(match_id="m1")) == 1


def test_query_by_tags(tmp_path):
    store = EventStore(tmp_path / "events.jsonl")
    store.append(new_event(EventType.FailureTagged, match_id="m1", tags=["exception"]))
    store.append(new_event(EventType.FailureTagged, match_id="m1", tags=["timeout"]))
    tagged = store.query(tags=["exception"])
    assert len(tagged) == 1


def test_latest(tmp_path):
    store = EventStore(tmp_path / "events.jsonl")
    store.append(new_event(EventType.TurnEnded, match_id="m1", turn=0))
    store.append(new_event(EventType.TurnEnded, match_id="m1", turn=1))
    assert store.latest(EventType.TurnEnded.value).turn == 1


def test_event_roundtrip():
    ev = new_event(EventType.ActionChosen, match_id="m1", payload={"selection": [0]})
    d = ev.to_dict()
    back = Event.from_dict(d)
    assert back.event_type == ev.event_type
    assert back.payload == ev.payload


def test_corrupt_line_skipped(tmp_path):
    path = tmp_path / "events.jsonl"
    store = EventStore(path)
    store.append(new_event(EventType.MatchStarted, match_id="m1"))
    with open(path, "a") as f:
        f.write("not json\n")
    # Should not raise; corrupt line is skipped.
    assert len(store.load()) == 1
