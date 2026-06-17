"""Local cabt evaluation runner for candidate branches.

The real working evaluation path is ``kaggle_environments.make("cabt")`` +
``env.run([agent0, agent1])`` (the same call the smoke test exercises). For each
candidate we:

1. run the package preflight (``verify_submission_inputs``) — a hard gate,
2. run a one-game cabt smoke test — a hard gate,
3. play N games against the immutable v1 control, alternating seats,
   instrumenting attack/pass/decision counts and capturing wins/losses/steps.

A candidate's deck is forced by pre-seeding its module's ``_DECK_IDS`` cache, so
it always plays its own deck regardless of the working directory. One failing
game never crashes the batch — it is recorded as an errored game and the run
continues.

cabt is required for evaluation; without it the runner degrades to a clear
"unavailable" status and records no fake results.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
import traceback
import uuid
from pathlib import Path

from ..graph.event_store import EventStore
from ..graph.events import EventType, new_event

_ATTACK_TYPE = 13
_PASS_TYPE = 14


def cabt_available() -> bool:
    try:
        import kaggle_environments  # noqa: F401
    except Exception:
        return False
    return True


def _load_module(main_path: str | Path):
    """Import a candidate main.py in isolation under a unique module name."""
    main_path = Path(main_path)
    name = f"cand_{uuid.uuid4().hex[:10]}"
    spec = importlib.util.spec_from_file_location(name, main_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module spec for {main_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module, name


def _read_deck(deck_path: str | Path) -> list[int]:
    from ..decks.deck_io import load_deck

    return load_deck(deck_path)


class _InstrumentedAgent:
    """Wrap a module's ``agent`` to force its deck and count decisions."""

    def __init__(self, module, deck_ids: list[int]):
        self.module = module
        # Force this candidate to always use its own deck (bypass cwd lookup).
        try:
            module._DECK_IDS = list(deck_ids)
        except Exception:
            pass
        self.stats = {
            "decisions": 0,
            "attacks": 0,
            "passes": 0,
            "attack_available": 0,
            "option_count_sum": 0,
            "fallbacks": 0,
            "type_counts": {},
        }

    def __call__(self, *args, **kwargs):
        # cabt may call the agent with (observation, configuration); the
        # baseline agent only takes the observation, so forward just that.
        obs = args[0] if args else kwargs.get("observation")
        try:
            out = self.module.agent(obs)
        except Exception:
            # The runtime is designed never to raise; if it did, count it as a
            # degradation and return an empty (engine treats as no-op/invalid).
            self.stats["fallbacks"] += 1
            return []
        try:
            self._record(obs, out)
        except Exception:
            pass
        return out

    def _record(self, obs, out):
        if not isinstance(obs, dict):
            return
        select = obs.get("select")
        if not isinstance(select, dict):
            return
        options = select.get("options") or select.get("option") or select.get("choices")
        if not isinstance(options, list) or not options:
            return
        try:
            max_count = int(select.get("maxCount", 1))
        except (TypeError, ValueError):
            max_count = 1
        if max_count <= 0:
            return
        self.stats["decisions"] += 1
        self.stats["option_count_sum"] += len(options)
        types = [o.get("type") if isinstance(o, dict) else None for o in options]
        if _ATTACK_TYPE in types:
            self.stats["attack_available"] += 1
        chosen = out if isinstance(out, (list, tuple)) else []
        for idx in chosen:
            if not isinstance(idx, int) or isinstance(idx, bool):
                continue
            if 0 <= idx < len(types):
                t = types[idx]
                key = str(t)
                self.stats["type_counts"][key] = self.stats["type_counts"].get(key, 0) + 1
                if t == _ATTACK_TYPE:
                    self.stats["attacks"] += 1
                elif t == _PASS_TYPE:
                    self.stats["passes"] += 1


def _make_cabt(ke, decks: list):
    """Build a cabt env with both seats' decks (mirrors the smoke test)."""
    last = None
    for cfg in ({"decks": list(decks)}, {"deck": decks[0]}, {}):
        try:
            return ke.make("cabt", configuration=cfg, debug=False)
        except Exception as exc:  # noqa: BLE001
            last = exc
            continue
    raise RuntimeError(f"make('cabt', ...) failed: {last!r}")


def _final_rewards(env) -> tuple:
    """Return (reward0, reward1, status0, status1) from the last meaningful step."""
    steps = getattr(env, "steps", None) or []
    for step in reversed(steps):
        if not isinstance(step, list) or len(step) < 2:
            continue
        r0, r1 = step[0].get("reward"), step[1].get("reward")
        s0, s1 = step[0].get("status"), step[1].get("status")
        if r0 is not None or r1 is not None:
            return r0, r1, s0, s1
    return None, None, None, None


def run_one_game(
    control_main: str | Path,
    control_deck: list[int],
    cand_main: str | Path,
    cand_deck: list[int],
    candidate_seat: int = 0,
) -> dict:
    """Play one cabt game: candidate vs control. Never raises."""
    result = {
        "candidate_seat": candidate_seat,
        "completed": False,
        "candidate_won": None,
        "draw": False,
        "steps": 0,
        "error": None,
        "timeout": False,
    }
    try:
        import kaggle_environments as ke
    except Exception as exc:
        result["error"] = f"kaggle_environments unavailable: {exc!r}"
        return result

    try:
        cand_mod, cand_name = _load_module(cand_main)
        ctrl_mod, ctrl_name = _load_module(control_main)
        cand_agent = _InstrumentedAgent(cand_mod, cand_deck)
        ctrl_agent = _InstrumentedAgent(ctrl_mod, control_deck)

        if candidate_seat == 0:
            agents = [cand_agent, ctrl_agent]
            decks = [list(cand_deck), list(control_deck)]
        else:
            agents = [ctrl_agent, cand_agent]
            decks = [list(control_deck), list(cand_deck)]

        env = _make_cabt(ke, decks)
        env.run(agents)

        r0, r1, s0, s1 = _final_rewards(env)
        steps = len(getattr(env, "steps", []) or [])
        result["steps"] = steps
        result["status"] = [s0, s1]

        cand_reward = r0 if candidate_seat == 0 else r1
        opp_reward = r1 if candidate_seat == 0 else r0
        statuses = [s0, s1]
        if any(s in ("TIMEOUT", "ERROR") for s in statuses if s):
            result["timeout"] = any(s == "TIMEOUT" for s in statuses if s)
            result["error"] = f"non-DONE status: {statuses}"
            # still record stats below
        else:
            result["completed"] = True
            if cand_reward is None or opp_reward is None:
                result["candidate_won"] = None
            elif cand_reward > opp_reward:
                result["candidate_won"] = True
            elif cand_reward < opp_reward:
                result["candidate_won"] = False
            else:
                result["candidate_won"] = None
                result["draw"] = True

        # Attach candidate decision instrumentation.
        for k, v in cand_agent.stats.items():
            result[k] = v

        sys.modules.pop(cand_name, None)
        sys.modules.pop(ctrl_name, None)
    except Exception as exc:  # noqa: BLE001 - one bad game must not kill the batch
        result["error"] = repr(exc)
        result["trace"] = traceback.format_exc()
    return result


def _run_candidate_gates(run_dir: Path, card_db) -> dict:
    """Run package verify + one-game smoke for a candidate. Returns gate dict."""
    from ..packaging.make_submission import SubmissionError, verify_submission_inputs
    from ..sim.kaggle_smoke import run_smoke_test

    gates = {
        "package_ok": False,
        "package_error": None,
        "smoke_ok": False,
        "smoke_status": None,
    }
    main_py = run_dir / "main.py"
    deck_csv = run_dir / "deck.csv"
    try:
        verify_submission_inputs(main_py, deck_csv, card_db=card_db)
        gates["package_ok"] = True
    except SubmissionError as exc:
        gates["package_error"] = str(exc)
        return gates

    # Smoke: load the candidate's own agent + deck and run one self-play game.
    try:
        mod, name = _load_module(main_py)
        deck_ids = _read_deck(deck_csv)
        agent = _InstrumentedAgent(mod, deck_ids)
        res = run_smoke_test(agent, deck_ids, games=1, out_dir=str(run_dir))
        gates["smoke_ok"] = bool(res.passed)
        gates["smoke_status"] = res.status
        sys.modules.pop(name, None)
    except Exception as exc:  # noqa: BLE001
        gates["smoke_status"] = f"FAIL: {exc!r}"
    return gates


def evaluate_candidate(
    branch,
    control_main: str | Path,
    control_deck: str | Path,
    n_games: int = 5,
    card_db=None,
    event_store: EventStore | None = None,
) -> dict:
    """Gate, then evaluate one candidate branch vs the control. Returns metrics."""
    from .metrics import compute_metrics

    logging.disable(logging.WARNING)  # quiet OpenSpiel/cabt import chatter
    store = event_store or EventStore()
    run_dir = Path(branch.run_dir)
    control_deck_ids = _read_deck(control_deck)
    cand_deck_ids = _read_deck(run_dir / "deck.csv")

    store.append(new_event(
        EventType.LocalEvaluationStarted,
        payload={"branch_id": branch.branch_id, "n_games": n_games,
                 "seam_id": branch.seam_id},
        tags=["experiment", branch.kind],
    ))

    gates = _run_candidate_gates(run_dir, card_db)

    results: list[dict] = []
    if gates["package_ok"] and gates["smoke_ok"]:
        store.append(new_event(
            EventType.MatchBatchStarted,
            payload={"branch_id": branch.branch_id, "games": n_games},
            tags=["experiment"],
        ))
        for i in range(max(1, n_games)):
            seat = i % 2
            r = run_one_game(
                control_main, control_deck_ids,
                run_dir / "main.py", cand_deck_ids, candidate_seat=seat,
            )
            results.append(r)
        store.append(new_event(
            EventType.MatchBatchFinished,
            payload={"branch_id": branch.branch_id,
                     "games": len(results),
                     "errors": sum(1 for r in results if r.get("error"))},
            tags=["experiment"],
        ))

    metrics = compute_metrics(results)
    metrics.update(gates)
    metrics["branch_id"] = branch.branch_id
    metrics["seam_id"] = branch.seam_id
    metrics["kind"] = branch.kind

    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, default=str), encoding="utf-8"
    )

    store.append(new_event(
        EventType.MetricsComputed,
        payload={"branch_id": branch.branch_id,
                 "win_rate": metrics.get("win_rate"),
                 "games_completed": metrics.get("games_completed"),
                 "package_ok": gates["package_ok"],
                 "smoke_ok": gates["smoke_ok"]},
        tags=["experiment", branch.kind],
    ))
    store.append(new_event(
        EventType.LocalEvaluationFinished,
        payload={"branch_id": branch.branch_id,
                 "games_completed": metrics.get("games_completed"),
                 "crashes": metrics.get("crashes"),
                 "timeouts": metrics.get("timeouts")},
        tags=["experiment", branch.kind],
    ))
    logging.disable(logging.NOTSET)
    return metrics
