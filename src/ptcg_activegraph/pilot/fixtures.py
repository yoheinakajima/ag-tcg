"""Core-competency fixture loading + deterministic grading.

Fixtures are **reduced-model**: each carries a normalized ``board``, an ``options``
list, a decision ``kind`` and an ``expect`` spec. A fixture is graded by calling a
decision function (the candidate's embedded ``core_pilot_decide`` or the lab
``decide``) and comparing the returned result against ``expect``.

Grading statuses:
  * ``pass``     — hard fixture met its expectation.
  * ``fail``     — hard fixture violated its expectation (blocks eval + queue).
  * ``advisory`` — non-hard fixture; reported with met/not-met, never blocks.
  * ``na``       — not applicable (e.g. candidate exposes no core-pilot layer).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


def load_index(fixtures_dir: Any) -> list:
    """Return the ordered list of fixture file names from index.yaml."""
    d = Path(fixtures_dir)
    idx = d / "index.yaml"
    if idx.exists() and yaml is not None:
        data = yaml.safe_load(idx.read_text(encoding="utf-8")) or {}
        files = data.get("fixtures") or []
        if files:
            return [str(f) for f in files]
    return sorted(p.name for p in d.glob("*.json"))


def load_fixtures(fixtures_dir: Any) -> list:
    d = Path(fixtures_dir)
    out = []
    for name in load_index(d):
        p = d / name
        if p.exists():
            out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


def _check_expect(expect: dict, result: dict) -> tuple:
    """Return (met: bool, detail: str) of ``result`` against ``expect``."""
    cid = result.get("chosen_card_id")
    cids = result.get("chosen_card_ids") or []
    action = result.get("action_kind")

    if "chosen_card_id" in expect:
        want = expect["chosen_card_id"]
        return cid == want, "chosen=%r want=%r" % (cid, want)
    if "chosen_card_id_in" in expect:
        want = expect["chosen_card_id_in"]
        return cid in want, "chosen=%r want_in=%r" % (cid, want)
    if "chosen_card_id_not" in expect:
        want = expect["chosen_card_id_not"]
        return cid != want, "chosen=%r want_not=%r" % (cid, want)
    if "chosen_card_ids_include" in expect:
        want = expect["chosen_card_ids_include"]
        return all(w in cids for w in want), "chosen_ids=%r include=%r" % (cids, want)
    if "chosen_card_ids_exclude" in expect:
        want = expect["chosen_card_ids_exclude"]
        return all(w not in cids for w in want), "chosen_ids=%r exclude=%r" % (cids, want)
    if "action_kind" in expect:
        want = expect["action_kind"]
        return action == want, "action=%r want=%r" % (action, want)
    if "action_kind_not" in expect:
        want = expect["action_kind_not"]
        return action != want, "action=%r want_not=%r" % (action, want)
    if "chosen_number" in expect:
        want = expect["chosen_number"]
        got = result.get("chosen_number")
        return got == want, "chosen_number=%r want=%r" % (got, want)
    if "chosen_number_max" in expect:
        want = expect["chosen_number_max"]
        got = result.get("chosen_number")
        ok = isinstance(got, int) and not isinstance(got, bool) and got <= want
        return ok, "chosen_number=%r want_max=%r" % (got, want)
    return False, "no recognized expect key: %r" % (sorted(expect),)


def grade_fixture(fixture: dict, decide_fn: Callable, has_layer: bool = True) -> dict:
    """Grade one fixture. ``decide_fn(kind, board, options)`` -> result dict."""
    fid = fixture.get("id", "?")
    kind = fixture.get("kind")
    hard = bool(fixture.get("hard", True))
    expect = fixture.get("expect") or {}
    advisory = bool(fixture.get("advisory")) or expect.get("advisory") is True

    if not has_layer:
        # A candidate with no core-pilot decision layer provably lacks the
        # competence: hard fixtures fail (informative), advisory ones are NA.
        status = "na" if advisory else "fail"
        return {"id": fid, "kind": kind, "status": status, "hard": hard,
                "met": False, "detail": "candidate exposes no core_pilot_decide layer"}

    try:
        result = decide_fn(kind, fixture.get("board") or {}, fixture.get("options") or [])
    except Exception as exc:
        return {"id": fid, "kind": kind, "status": "fail" if hard else "advisory",
                "hard": hard, "met": False, "detail": "decide raised: %r" % (exc,)}

    if advisory:
        met, detail = _check_expect(expect, result) if expect and "advisory" not in expect else (True, "advisory")
        return {"id": fid, "kind": kind, "status": "advisory", "hard": False,
                "met": met, "detail": detail}

    met, detail = _check_expect(expect, result)
    return {"id": fid, "kind": kind, "status": "pass" if met else "fail",
            "hard": hard, "met": met, "detail": detail}


def grade_all(fixtures: list, decide_fn: Callable, has_layer: bool = True) -> dict:
    rows = [grade_fixture(f, decide_fn, has_layer=has_layer) for f in fixtures]
    hard_fail = [r for r in rows if r["hard"] and r["status"] == "fail"]
    return {
        "rows": rows,
        "total": len(rows),
        "passed": sum(1 for r in rows if r["status"] == "pass"),
        "failed": sum(1 for r in rows if r["status"] == "fail"),
        "advisory": sum(1 for r in rows if r["status"] == "advisory"),
        "na": sum(1 for r in rows if r["status"] == "na"),
        "hard_failures": len(hard_fail),
        "ok": len(hard_fail) == 0,
    }
