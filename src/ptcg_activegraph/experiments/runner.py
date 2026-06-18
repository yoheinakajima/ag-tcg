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
import os
import signal
import subprocess
import sys
import tempfile
import traceback
import uuid
from pathlib import Path

from ..graph.event_store import EventStore
from ..graph.events import EventType, new_event

# Hard wall-clock budget for a single cabt game. Once cabt is warm a normal
# game finishes in well under a second (the cold OpenSpiel registration cost is
# paid once per process, on the first game). A *warm* game that exceeds this
# generous budget is a degenerate/non-terminating one (e.g. a combined policy
# that never advances the match toward a knockout); it is recorded as a timeout
# (a hard-reject) instead of hanging the whole batch.
GAME_TIMEOUT_SECONDS = 20


class _GameTimeout(Exception):
    """Raised by the per-game SIGALRM watchdog when a game runs too long."""


def _game_timeout_handler(signum, frame):  # noqa: ARG001
    raise _GameTimeout()

_ATTACK_TYPE = 13
_PASS_TYPE = 14
# select.context codes (search-to-hand / discard) used for effect-resolution
# telemetry. Mirrors the values used by the analyzer/generator.
_CTX_SEARCH_TO_HAND = 7
_CTX_DISCARD = 8


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
            # --- Pass 5 chaos / deckout telemetry (own-observation only) ---
            # Every field below is derived strictly from the candidate's own
            # observation (current.players[yourIndex] + select.context). Nothing
            # here peeks at the opponent's hidden hand/deck. Fields stay None /
            # 0 honestly when the observation does not expose them.
            "telemetry": {
                "min_deck_count": None,
                "deck_count_last": None,
                "low_deck_decisions": 0,
                "search_decisions": 0,
                "discard_decisions": 0,
                "max_bench_seen": 0,
                "max_hand_seen": 0,
                "context_counts": {},
            },
        }
        # Decision index at/below which the deck is treated as "low" (deckout
        # proximity). Conservative; matches deckout-awareness seam intent.
        self._low_deck_threshold = 6

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

        # --- Pass 5 chaos / deckout telemetry (own observation only) ---
        try:
            self._record_telemetry(obs, select)
        except Exception:
            pass
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

    def _record_telemetry(self, obs, select):
        """Capture deckout / board telemetry from the candidate's OWN view.

        Strictly own-observation: reads current.players[yourIndex] and the
        select.context. Never inspects the opponent's hidden hand/deck. Any
        field that the observation does not expose is left unchanged (None / 0),
        not guessed.
        """
        tel = self.stats["telemetry"]

        # Effect-resolution context tallies (search-to-hand / discard prompts).
        ctx = select.get("context")
        if ctx is not None:
            ckey = str(ctx)
            tel["context_counts"][ckey] = tel["context_counts"].get(ckey, 0) + 1
            if ctx == _CTX_SEARCH_TO_HAND:
                tel["search_decisions"] += 1
            elif ctx == _CTX_DISCARD:
                tel["discard_decisions"] += 1

        # Own board state: deck proximity + bench/hand pressure.
        cur = obs.get("current")
        if not isinstance(cur, dict):
            return
        me = cur.get("yourIndex")
        players = cur.get("players")
        if not isinstance(players, list) or not isinstance(me, int):
            return
        if not (0 <= me < len(players)):
            return
        mine = players[me]
        if not isinstance(mine, dict):
            return

        deck_count = mine.get("deckCount")
        if isinstance(deck_count, int) and not isinstance(deck_count, bool):
            tel["deck_count_last"] = deck_count
            if tel["min_deck_count"] is None or deck_count < tel["min_deck_count"]:
                tel["min_deck_count"] = deck_count
            if deck_count <= self._low_deck_threshold:
                tel["low_deck_decisions"] += 1

        bench = mine.get("bench")
        if isinstance(bench, list):
            tel["max_bench_seen"] = max(tel["max_bench_seen"], len(bench))
        hand = mine.get("hand")
        if isinstance(hand, list):
            tel["max_hand_seen"] = max(tel["max_hand_seen"], len(hand))


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
        # Watchdog: abort a degenerate/non-terminating game instead of hanging
        # the whole batch. Only arms on the main thread (the batch is single
        # threaded); on other threads we fall back to no watchdog.
        armed = False
        prev_handler = None
        try:
            prev_handler = signal.signal(signal.SIGALRM, _game_timeout_handler)
            signal.alarm(GAME_TIMEOUT_SECONDS)
            armed = True
        except (ValueError, AttributeError):
            armed = False
        try:
            env.run(agents)
        finally:
            if armed:
                signal.alarm(0)
                if prev_handler is not None:
                    signal.signal(signal.SIGALRM, prev_handler)

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
    except _GameTimeout:
        # Watchdog fired: a degenerate/non-terminating game. Record it as an
        # explicit timeout (a hard-reject downstream), not a generic crash.
        result["timeout"] = True
        result["error"] = f"game watchdog timeout (>{GAME_TIMEOUT_SECONDS}s)"
    except Exception as exc:  # noqa: BLE001 - one bad game must not kill the batch
        result["error"] = repr(exc)
        result["trace"] = traceback.format_exc()
    return result


# Default hard wall-clock budget for a SUBPROCESS game. More generous than the
# in-process SIGALRM budget because the child pays cold cabt/OpenSpiel
# registration on every spawn; a child exceeding this is killed by the parent.
SUBPROCESS_GAME_TIMEOUT_SECONDS = 90
# Grace period between SIGTERM and the un-ignorable SIGKILL when killing a hung
# child's process group. Small constant so a wedged C-level game is reaped fast.
_KILL_GRACE_SECONDS = 5

_CHILD_SCRIPT = str(Path(__file__).with_name("_game_subprocess.py"))


def _kill_process_group(proc: subprocess.Popen) -> None:
    """SIGTERM the child's process group, then SIGKILL if it ignores it.

    Uses the process *group* (the child is started in a new session) so any cabt
    worker threads/children die with it. A game wedged inside cabt's C code that
    swallows SIGTERM is still reaped by the un-ignorable SIGKILL.
    """
    def _signal_group(sig):
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except Exception:  # noqa: BLE001 - process may already be gone
            try:
                proc.send_signal(sig)
            except Exception:  # noqa: BLE001
                pass

    _signal_group(signal.SIGTERM)
    try:
        proc.wait(timeout=_KILL_GRACE_SECONDS)
        return
    except Exception:  # noqa: BLE001 - still alive: escalate
        pass
    _signal_group(signal.SIGKILL)
    try:
        proc.wait(timeout=_KILL_GRACE_SECONDS)
    except Exception:  # noqa: BLE001
        pass


def run_one_game_subprocess(
    control_main: str | Path,
    control_deck: list[int],
    cand_main: str | Path,
    cand_deck: list[int],
    candidate_seat: int = 0,
    timeout_seconds: int | None = None,
    child_script: str | None = None,
) -> dict:
    """Play one game in a killable child process. Never raises.

    The child plays exactly one game and writes the structured result (including
    the candidate's decision telemetry) to a temp file. If the child exceeds
    ``timeout_seconds`` it is killed (SIGTERM -> SIGKILL on its process group)
    and the game is recorded as a ``timeout`` (a hard-reject downstream) — the
    batch is never hung by a single degenerate game.
    """
    timeout_seconds = timeout_seconds or SUBPROCESS_GAME_TIMEOUT_SECONDS
    result = {
        "candidate_seat": candidate_seat,
        "completed": False,
        "candidate_won": None,
        "draw": False,
        "steps": 0,
        "error": None,
        "timeout": False,
        "subprocess": True,
    }
    child = child_script or _CHILD_SCRIPT
    spec = {
        "control_main": str(control_main),
        "control_deck": list(control_deck),
        "cand_main": str(cand_main),
        "cand_deck": list(cand_deck),
        "candidate_seat": candidate_seat,
    }
    with tempfile.TemporaryDirectory(prefix="cabt_game_") as td:
        spec_path = Path(td) / "spec.json"
        out_path = Path(td) / "out.json"
        spec_path.write_text(json.dumps(spec, default=str), encoding="utf-8")
        cmd = [sys.executable, child, str(spec_path), str(out_path)]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as exc:  # noqa: BLE001
            result["error"] = f"subprocess spawn failed: {exc!r}"
            return result

        try:
            proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            _kill_process_group(proc)
            result["timeout"] = True
            result["error"] = (
                f"subprocess game timeout (>{timeout_seconds}s; child killed)"
            )
            return result

        if proc.returncode != 0:
            result["error"] = (
                f"subprocess game exited with code {proc.returncode}"
            )
            return result

        try:
            parsed = json.loads(out_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                parsed.setdefault("subprocess", True)
                return parsed
            result["error"] = "subprocess result was not a JSON object"
        except Exception as exc:  # noqa: BLE001
            result["error"] = f"subprocess produced no parseable result: {exc!r}"
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


def _seat_schedule(n_games: int, games_per_seat: int | None, seat_swap: bool) -> list[int]:
    """Return the ordered list of candidate seats to play.

    With ``games_per_seat`` set (seat-swap), play exactly that many games as
    player 0 then the same number as player 1, so any first-/second-player
    advantage is balanced out. Otherwise fall back to the legacy alternating
    schedule of ``n_games`` games (seat = i % 2).
    """
    if games_per_seat and games_per_seat > 0:
        g = int(games_per_seat)
        return [0] * g + [1] * g
    if seat_swap:
        half = max(1, n_games) // 2 or 1
        return [0] * half + [1] * half
    return [i % 2 for i in range(max(1, n_games))]


def _write_branch_report(run_dir: Path, branch, metrics: dict) -> None:
    """Write a per-branch human summary (hypothesis + gate + match results)."""
    def fmt(v, nd=2):
        return "-" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))

    lines = [
        f"# {branch.branch_id}",
        "",
        f"- **Seam:** {branch.seam_id}",
        f"- **Kind:** {branch.kind}    **Archetype:** {getattr(branch, 'archetype', '')}",
        f"- **Parent:** {getattr(branch, 'parent', '')}",
        f"- **Stage:** {metrics.get('stage') or 'broad'}",
        "",
        "## Hypothesis",
        getattr(branch, "hypothesis", "") or "(none)",
        "",
        "## Gates",
        f"- package verify: {'PASS' if metrics.get('package_ok') else 'FAIL'}"
        + (f" ({metrics.get('package_error')})" if metrics.get('package_error') else ""),
        f"- one-game smoke: {'PASS' if metrics.get('smoke_ok') else 'FAIL'}"
        + (f" ({metrics.get('smoke_status')})" if metrics.get('smoke_status') else ""),
        "",
        "## Match results (vs immutable v1 control)",
        f"- games completed: {metrics.get('games_completed', 0)} "
        f"(seat-swap: {metrics.get('seat_swap')})",
        f"- wins / losses / draws: {metrics.get('wins', 0)} / "
        f"{metrics.get('losses', 0)} / {metrics.get('draws', 0)}",
        f"- raw win rate: {fmt(metrics.get('win_rate'))}    "
        f"adjusted win rate: {fmt(metrics.get('adjusted_win_rate'))}",
        f"- as P0: {metrics.get('candidate_as_p0_wins', 0)}/"
        f"{metrics.get('candidate_as_p0_games', 0)} "
        f"(rate {fmt(metrics.get('candidate_p0_win_rate'))}); "
        f"as P1: {metrics.get('candidate_as_p1_wins', 0)}/"
        f"{metrics.get('candidate_as_p1_games', 0)} "
        f"(rate {fmt(metrics.get('candidate_p1_win_rate'))})",
        f"- seat balance delta (P0-P1): {fmt(metrics.get('seat_balance_delta'))}",
        f"- attack rate: {fmt(metrics.get('attack_rate'))}    "
        f"pass rate: {fmt(metrics.get('pass_rate'))}",
        f"- crashes / timeouts / fallbacks: {metrics.get('crashes', 0)} / "
        f"{metrics.get('timeouts', 0)} / {metrics.get('fallbacks', 0)}",
        "",
    ]
    (run_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def evaluate_candidate(
    branch,
    control_main: str | Path,
    control_deck: str | Path,
    n_games: int = 5,
    card_db=None,
    event_store: EventStore | None = None,
    games_per_seat: int | None = None,
    seat_swap: bool = False,
    stage: str | None = None,
    use_subprocess: bool = False,
    game_timeout_seconds: int | None = None,
) -> dict:
    """Gate, then evaluate one candidate branch vs the control. Returns metrics.

    With ``use_subprocess=True`` each game runs in a killable child process so a
    game that hangs inside cabt's C-level ``env.run`` is reaped by a parent
    wall-clock timeout (``game_timeout_seconds``) instead of wedging the batch.
    """
    from .metrics import compute_metrics

    logging.disable(logging.WARNING)  # quiet OpenSpiel/cabt import chatter
    store = event_store or EventStore()
    run_dir = Path(branch.run_dir)
    control_deck_ids = _read_deck(control_deck)
    cand_deck_ids = _read_deck(run_dir / "deck.csv")

    seats = _seat_schedule(n_games, games_per_seat, seat_swap)
    total_games = len(seats)

    store.append(new_event(
        EventType.LocalEvaluationStarted,
        payload={"branch_id": branch.branch_id, "n_games": total_games,
                 "games_per_seat": games_per_seat, "seat_swap": seat_swap,
                 "stage": stage, "seam_id": branch.seam_id},
        tags=["experiment", branch.kind],
    ))

    gates = _run_candidate_gates(run_dir, card_db)

    results: list[dict] = []
    if gates["package_ok"] and gates["smoke_ok"]:
        store.append(new_event(
            EventType.MatchBatchStarted,
            payload={"branch_id": branch.branch_id, "games": total_games,
                     "stage": stage},
            tags=["experiment"],
        ))
        for seat in seats:
            if use_subprocess:
                r = run_one_game_subprocess(
                    control_main, control_deck_ids,
                    run_dir / "main.py", cand_deck_ids, candidate_seat=seat,
                    timeout_seconds=game_timeout_seconds,
                )
            else:
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
    metrics["stage"] = stage
    metrics["games_per_seat"] = games_per_seat
    metrics["seat_swap"] = bool(games_per_seat) or seat_swap
    metrics["hypothesis"] = getattr(branch, "hypothesis", "")

    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, default=str), encoding="utf-8"
    )
    try:
        _write_branch_report(run_dir, branch, metrics)
    except Exception:  # noqa: BLE001 - reporting must never fail an eval
        pass

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
