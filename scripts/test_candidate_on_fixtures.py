#!/usr/bin/env python3
"""Grade a candidate ``main.py`` against the replay-derived decision fixtures.

This is the Pass-6 *Stage 0* gate: before any (slow, hang-prone) cabt game, a
candidate is fed each frozen decision prompt from ``data/replay_fixtures/`` and
graded on two independent axes:

* **legality** (hard gate): the returned action must be a list of unique,
  in-range option indices that respects the prompt's ``minCount``/``maxCount``,
  and the agent must not raise. A candidate that fails legality on any fixture
  is unsafe to run.
* **preference** (advisory): an honest, per-fixture strategy check
  (decline / avoid_cards / prefer_cards / forced_all). ``forced_all`` fixtures
  have no avoidable choice, so their preference result is ``na``. Preferences
  are *recorded*, not required — v2 (the active control) is expected to fail
  some of them; a v3 policy aims to pass them.

The candidate is loaded exactly the way the batch runner loads it
(``runner._load_module``) so the gate reflects real candidate behaviour. Every
``agent(obs)`` call is sandboxed in try/except: a crashing fixture is recorded
as a legality failure for that fixture and never aborts the run.

Usage:
    python scripts/test_candidate_on_fixtures.py --run-dir data/baselines/v2_kaggle_479_1_deck_energy_trim_light
    python scripts/test_candidate_on_fixtures.py --run-dir experiments/runs/<id> --json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from ptcg_activegraph.experiments.runner import _load_module

DEFAULT_FIXTURES_DIR = "data/replay_fixtures"


# ---------------------------------------------------------------------------
# Pure graders (no I/O) — easy to unit test.
# ---------------------------------------------------------------------------

def check_legality(action: Any, n_options: int, min_count: int | None,
                   max_count: int | None) -> tuple[bool, str]:
    """Honest, candidate-independent legality check for a selection."""
    if not isinstance(action, list):
        return False, "action is not a list"
    for i in action:
        if isinstance(i, bool) or not isinstance(i, int):
            return False, f"non-integer index {i!r}"
    if len(set(action)) != len(action):
        return False, "duplicate indices"
    for i in action:
        if i < 0 or i >= n_options:
            return False, f"index {i} out of range [0,{n_options})"
    mx = max_count if isinstance(max_count, int) else (1 if n_options else 0)
    mn = min_count if isinstance(min_count, int) else 0
    if n_options <= 0 or mx <= 0:
        return (len(action) == 0), ("empty required when nothing to pick"
                                    if action else "ok")
    if len(action) > mx:
        return False, f"selected {len(action)} > maxCount {mx}"
    if len(action) < mn:
        return False, f"selected {len(action)} < minCount {mn}"
    return True, "ok"


def chosen_card_ids(action: list[int], option_cards: list[Any]) -> list[int]:
    out: list[int] = []
    for i in action:
        if isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(option_cards):
            cid = option_cards[i]
            if isinstance(cid, int) and not isinstance(cid, bool):
                out.append(cid)
    return out


def evaluate_preference(action: list[int], fixture: dict) -> dict:
    """Grade the advisory preference. Returns {result, detail}.

    result is one of: "pass", "fail", "na".
    """
    pref = fixture.get("check", {}).get("preference", {})
    kind = pref.get("kind")
    option_cards = fixture.get("option_cards", [])
    chosen = chosen_card_ids(action, option_cards)
    min_count = fixture.get("min_count")

    if kind == "forced_all":
        # No avoidable choice; the legality gate is the whole story here.
        return {"result": "na", "kind": kind,
                "detail": "forced selection; no preference to satisfy",
                "chosen_cards": chosen}

    if kind == "decline":
        # Declining is only a legal option when minCount allows an empty pick.
        if isinstance(min_count, int) and min_count > 0:
            return {"result": "na", "kind": kind,
                    "detail": f"cannot decline: minCount {min_count} > 0",
                    "chosen_cards": chosen}
        passed = len(action) == 0
        return {"result": "pass" if passed else "fail", "kind": kind,
                "detail": ("declined" if passed
                           else f"selected {chosen} instead of declining"),
                "chosen_cards": chosen}

    if kind == "avoid_cards":
        avoid = set(pref.get("cards", []))
        hit = sorted(set(chosen) & avoid)
        passed = not hit
        return {"result": "pass" if passed else "fail", "kind": kind,
                "detail": ("avoided all flagged cards" if passed
                           else f"selected flagged card(s) {hit}"),
                "chosen_cards": chosen}

    if kind == "prefer_cards":
        prefer = set(pref.get("cards", []))
        passed = any(c in prefer for c in chosen)
        return {"result": "pass" if passed else "fail", "kind": kind,
                "detail": ("picked a preferred card" if passed
                           else f"picked {chosen}, none in preferred {sorted(prefer)}"),
                "chosen_cards": chosen}

    return {"result": "na", "kind": kind,
            "detail": "no recognized preference check", "chosen_cards": chosen}


# ---------------------------------------------------------------------------
# Fixture loading + candidate evaluation.
# ---------------------------------------------------------------------------

def load_fixtures(fixtures_dir: str | Path) -> list[dict]:
    """Load gradeable fixtures from either a directory of per-fixture JSON files
    (legacy ``data/replay_fixtures/``) or a single combined JSON file
    (Pass 8 ``{"fixtures": [...]}``). Non-gradeable / observation-less entries
    are skipped so a candidate ``agent`` is only ever fed real prompts.
    """
    p = Path(fixtures_dir)
    fixtures: list[dict] = []

    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return fixtures
        if isinstance(data, dict) and isinstance(data.get("fixtures"), list):
            items = data["fixtures"]
        elif isinstance(data, list):
            items = data
        elif isinstance(data, dict) and "observation" in data:
            items = [data]
        else:
            items = []
        for fx in items:
            if (isinstance(fx, dict) and fx.get("gradeable", True)
                    and fx.get("observation") is not None):
                fixtures.append(fx)
        return fixtures

    for path in sorted(p.glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and "observation" in data:
            fixtures.append(data)
    return fixtures


def evaluate_candidate_on_fixtures(run_dir: str | Path,
                                   fixtures_dir: str | Path = DEFAULT_FIXTURES_DIR
                                   ) -> dict:
    """Load ``run_dir/main.py`` and grade it against every fixture.

    Never raises for candidate problems: a missing main.py is reported in the
    result; a crashing ``agent`` call is recorded as a per-fixture legality
    failure. The hard gate (``legality_gate``) is True only when every fixture
    is legal and no agent call raised.
    """
    run_dir = Path(run_dir)
    main_path = run_dir / "main.py"
    fixtures = load_fixtures(fixtures_dir)
    result: dict[str, Any] = {
        "run_dir": str(run_dir),
        "fixtures_dir": str(fixtures_dir),
        "n_fixtures": len(fixtures),
        "loaded": False,
        "load_error": None,
        "fixtures": [],
        "legality_gate": False,
        "preference_pass": 0,
        "preference_fail": 0,
        "preference_na": 0,
    }
    if not main_path.exists():
        result["load_error"] = f"no main.py at {main_path}"
        return result

    try:
        module, _name = _load_module(main_path)
        agent = getattr(module, "agent", None)
        if not callable(agent):
            result["load_error"] = "module has no callable 'agent'"
            return result
        result["loaded"] = True
    except Exception as exc:  # candidate import must never crash the gate
        result["load_error"] = f"{type(exc).__name__}: {exc}"
        return result

    all_legal = True
    for fx in fixtures:
        obs = fx.get("observation")
        n_options = fx.get("n_options", 0)
        min_count = fx.get("min_count")
        max_count = fx.get("max_count")
        rec: dict[str, Any] = {
            "id": fx.get("id"),
            "context_name": fx.get("context_name"),
            "effect_card_id": fx.get("effect_card_id"),
            "error": None,
            "action": None,
        }
        try:
            action = agent(obs)
        except Exception as exc:
            rec["error"] = f"{type(exc).__name__}: {exc}"
            rec["legal"] = False
            rec["legal_reason"] = "agent raised"
            rec["preference"] = {"result": "na", "detail": "agent raised"}
            result["preference_na"] += 1
            result["fixtures"].append(rec)
            all_legal = False
            continue

        rec["action"] = action
        legal, reason = check_legality(action, n_options, min_count, max_count)
        rec["legal"] = legal
        rec["legal_reason"] = reason
        if not legal:
            all_legal = False
        pref = evaluate_preference(action if isinstance(action, list) else [], fx)
        rec["preference"] = pref
        result[f"preference_{pref['result']}"] += 1
        result["fixtures"].append(rec)

    result["legality_gate"] = all_legal and result["loaded"]
    return result


def _format_report(result: dict) -> str:
    lines: list[str] = []
    lines.append(f"Candidate: {result['run_dir']}")
    if result.get("load_error"):
        lines.append(f"  LOAD ERROR: {result['load_error']}")
        return "\n".join(lines)
    lines.append(
        f"  legality_gate={'PASS' if result['legality_gate'] else 'FAIL'}  "
        f"preferences: {result['preference_pass']} pass / "
        f"{result['preference_fail']} fail / {result['preference_na']} na"
    )
    for fx in result["fixtures"]:
        legal = "legal" if fx.get("legal") else "ILLEGAL"
        pref = fx.get("preference", {})
        err = f" ERROR={fx['error']}" if fx.get("error") else ""
        lines.append(
            f"  - {fx['id']:<28} action={fx.get('action')!s:<14} "
            f"{legal:<8} pref={pref.get('result','?'):<4} "
            f"({pref.get('detail','')}){err}"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--run-dir", required=True,
                        help="candidate directory containing main.py")
    parser.add_argument("--fixtures-dir", default=DEFAULT_FIXTURES_DIR,
                        help=f"fixtures directory (default {DEFAULT_FIXTURES_DIR})")
    parser.add_argument("--json", action="store_true",
                        help="emit the full result as JSON")
    args = parser.parse_args()

    result = evaluate_candidate_on_fixtures(args.run_dir, args.fixtures_dir)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(_format_report(result))
    # Exit non-zero only on the hard legality gate (advisory prefs never fail CI).
    return 0 if result["legality_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
