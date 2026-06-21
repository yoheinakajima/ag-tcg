"""PASS 46E — cg Search Outcome Oracle (pure / never-raise / subprocess-isolated).

A reusable wrapper around the bundled cg Search API
(``data/reference_agents/_sdk/cg``) that evaluates the *immediate* one-step
consequence of legal actions taken from Pass-46C trace/replay decision frames.

Design constraints (enforced):

* **Pure from the repo's perspective** — this module performs NO Object Storage
  writes, NO EventStore writes, NO production ledger access, NO candidate
  generation, NO public-reference policy imports, NO root mutation.
* **No native import at module load** — ``cg`` / ``libcg.so`` is imported ONLY in
  the separate subprocess worker (``_search_worker.py``), never here. Importing
  this module triggers no native code and no I/O.
* **Never-raise public APIs** — every public function returns a structured result
  describing failure rather than raising.
* **Subprocess isolation** — every actual search call runs in a child process
  under a hard wall-clock timeout, because native cg/open_spiel code can hang in
  ways an in-process ``SIGALRM`` cannot interrupt.

Honesty (the whole point of this pass):

The cg Search API requires *predicted* hidden-zone card IDs (opponent deck / hand
/ prize, and your own prize order). Those are unknowable from a masked
observation, so a returned one-step outcome is classified, never overclaimed:

* ``exact_full_state_replay``     — calibrated against a complete trace and the
  predicted post-state matches the actual next frame.
* ``assumption_based_hidden_state`` — produced a result but leaned on fabricated
  hidden-zone IDs; useful, NOT exact.
* ``unsupported_or_failed``       — failed / timed out / mismatched / untrustworthy.

This module NEVER asserts exact damage, lethal, missed-KO, Boss/gust, spread, or a
globally "best action". The one-step ranker is explicitly scoped as
``one_step_score_rank under this scoring function and this search-state
assumption`` — never globally optimal.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

_THIS = Path(__file__).resolve()
_REPO = _THIS.parents[3]
_WORKER = _THIS.parent / "_search_worker.py"
_SDK = _REPO / "data" / "reference_agents" / "_sdk"

# --------------------------------------------------------------------------- claims

UNSUPPORTED_SEARCH_CLAIMS: dict[str, str] = {
    "exact_damage": "search post-state may show an HP delta, but exact damage is "
    "only trustworthy when calibrated to a full-state replay; never assert it "
    "from a masked observation alone.",
    "lethal": "a KO in one branch under fabricated hidden zones is not a lethal "
    "guarantee.",
    "missed_ko": "absence of a KO under assumed hidden state does not prove a "
    "missed KO in the real game.",
    "boss_gust": "gust / forced-switch targeting depends on hidden information and "
    "is not asserted.",
    "spread": "spread-damage distribution is not asserted from one-step search.",
    "best_action": "the ranker reports one_step_score_rank under a specific scoring "
    "function and search-state assumption; it is NOT a globally optimal action.",
    "globally_optimal": "no multi-turn / opponent-response optimality is claimed.",
}

# objective, perspective-independent fields compared in a state signature.
_CORE_FIELDS = ("turn", "result")  # a difference here is always a real mismatch


def unsupported_search_claims() -> dict[str, str]:
    """The fixed set of claims this oracle refuses to assert. Stable contract."""
    return dict(UNSUPPORTED_SEARCH_CLAIMS)


# --------------------------------------------------------------------------- dataclasses


@dataclass
class SearchAssumption:
    """Describes the hidden-state assumption used to seed a search."""

    mode: str = "trace_full_state_if_available"
    hidden_state_source: str = "fabricated_placeholder_basic_ids"
    opponent_hand_strategy: str = "count_only_placeholder_basic_ids"
    opponent_deck_strategy: str = "count_only_placeholder_basic_ids_one_basic_min"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ActionOutcome:
    selected_indices: list[int] = field(default_factory=list)
    legal: Optional[bool] = None
    error: Optional[str] = None
    timed_out: bool = False
    elapsed_s: Optional[float] = None
    pre_signature: Optional[dict] = None
    post_signature: Optional[dict] = None
    prize_delta: Optional[dict] = None
    hp_delta_summary: Optional[dict] = None
    zone_delta_summary: Optional[dict] = None
    log_delta_summary: Optional[dict] = None
    result_delta: Optional[dict] = None
    assumption_mode: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OracleResult:
    ok: bool = False
    supported_level: str = "unsupported_or_failed"
    outcome: Optional[ActionOutcome] = None
    warnings: list[str] = field(default_factory=list)
    unsupported_claims: dict[str, str] = field(default_factory=unsupported_search_claims)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["outcome"] = self.outcome.to_dict() if self.outcome else None
        return d


# --------------------------------------------------------------------------- helpers


def _g(obj: Any, key: str, default: Any = None) -> Any:
    """Attribute- or dict-tolerant getter that never raises."""
    try:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)
    except Exception:  # noqa: BLE001
        return default


def _extract_observation(frame: Any) -> Optional[dict]:
    """Return the raw observation dict (with ``search_begin_input``) from a frame.

    Accepts a Pass-46C step record (dict with ``observation``), a bare
    observation dict (has ``select`` / ``current`` / ``search_begin_input``), or
    anything else (returns ``None``). A bare ``DecisionFrame`` carries no raw
    observation, so it is unsupported for search and returns ``None``.
    """
    if not isinstance(frame, dict):
        return None
    obs = frame.get("observation")
    if isinstance(obs, dict):
        return obs
    if "search_begin_input" in frame or ("select" in frame and "current" in frame):
        return frame
    return None


def _selected_from_frame(frame: Any) -> Optional[list[int]]:
    """Best-effort recovery of the chosen select indices from a trace frame."""
    if not isinstance(frame, dict):
        return None
    act = frame.get("action")
    if isinstance(act, list) and all(isinstance(i, int) for i in act):
        return list(act)
    return None


def _is_index_action(action: Any, n_options: int, min_c: Any, max_c: Any) -> bool:
    """True iff ``action`` is a legal select-index list for this option set.

    Filters out the deck-submission step (a 60-id list against a 2-option YesNo).
    """
    if not isinstance(action, list) or not action:
        return False
    if not all(isinstance(i, int) for i in action):
        return False
    try:
        mn = int(min_c) if min_c is not None else 1
        mx = int(max_c) if max_c is not None else mn
    except Exception:  # noqa: BLE001
        mn, mx = 1, 1
    if not (mn <= len(action) <= max(mx, mn)):
        return False
    if len(set(action)) != len(action):
        return False
    return all(isinstance(i, int) and 0 <= i < n_options for i in action)


def _zone_sig_for_player(player: Any) -> dict:
    actives = _g(player, "active", []) or []
    active_ids: list = []
    active_hp: list = []
    energy_total = 0
    for p in actives:
        if isinstance(p, dict):
            active_ids.append(p.get("id"))
            active_hp.append(p.get("hp"))
            energy_total += len(p.get("energies") or [])
    bench = _g(player, "bench", []) or []
    for p in bench:
        if isinstance(p, dict):
            energy_total += len(p.get("energies") or [])
    discard = _g(player, "discard", []) or []
    prize = _g(player, "prize", []) or []
    return {
        "active_ids": active_ids,
        "active_hp": active_hp,
        "bench_count": len(bench) if isinstance(bench, list) else None,
        "hand_count": _g(player, "handCount"),
        "deck_count": _g(player, "deckCount"),
        "discard_count": len(discard) if isinstance(discard, list) else None,
        "prize_count": len(prize) if isinstance(prize, list) else None,
        "energy_total": energy_total,
    }


def signature_from_current(current: Any, your_index: Optional[int] = None) -> Optional[dict]:
    """Compute an objective, perspective-independent state signature.

    Only visible / objective facts (counts, visible active ids/hp, turn, result,
    stadium count) — NEVER hidden hand/deck contents.
    """
    if not isinstance(current, dict):
        return None
    players = current.get("players")
    if not isinstance(players, list) or len(players) != 2:
        return None
    stadium = current.get("stadium") or []
    yi = current.get("yourIndex") if your_index is None else your_index
    return {
        "turn": current.get("turn"),
        "result": current.get("result"),
        "stadium_count": len(stadium) if isinstance(stadium, list) else None,
        "your_index": yi,
        "players": [_zone_sig_for_player(players[0]), _zone_sig_for_player(players[1])],
    }


def compare_signatures(pred: Any, actual: Any) -> dict:
    """Field-by-field comparison of two state signatures.

    Returns ``{matched:[...], differed:[...], core_differed:[...],
    classification:...}`` where classification is exact_match / partial_match /
    mismatch / uncomparable.
    """
    if not isinstance(pred, dict) or not isinstance(actual, dict):
        return {"classification": "uncomparable", "matched": [], "differed": [],
                "core_differed": []}
    matched: list[str] = []
    differed: list[str] = []
    core_differed: list[str] = []

    def _cmp(name: str, a: Any, b: Any, core: bool) -> None:
        if a == b:
            matched.append(name)
        else:
            differed.append(name)
            if core:
                core_differed.append(name)

    for f in _CORE_FIELDS:
        _cmp(f, pred.get(f), actual.get(f), core=True)
    _cmp("stadium_count", pred.get("stadium_count"), actual.get("stadium_count"), core=False)
    pp = pred.get("players") or []
    ap = actual.get("players") or []
    if len(pp) == 2 and len(ap) == 2:
        for seat in (0, 1):
            for key in ("active_ids", "active_hp", "bench_count", "hand_count",
                        "deck_count", "discard_count", "prize_count", "energy_total"):
                # prize/active hp are decisive-ish but treated non-core except turn/result
                _cmp(f"p{seat}.{key}", pp[seat].get(key), ap[seat].get(key), core=False)
    else:
        differed.append("players_shape")
        core_differed.append("players_shape")

    if not matched and not differed:
        classification = "uncomparable"
    elif not differed:
        classification = "exact_match"
    elif core_differed:
        classification = "mismatch"
    elif not matched:
        classification = "mismatch"
    else:
        classification = "partial_match"
    return {"classification": classification, "matched": matched,
            "differed": differed, "core_differed": core_differed}


def _diff_summary(pre: Optional[dict], post: Optional[dict]) -> dict:
    """Human/aggregation-friendly pre→post deltas (never-raise)."""
    out: dict[str, Any] = {"prize_delta": None, "hp_delta": None,
                           "zone_delta": None, "result_delta": None}
    if not isinstance(pre, dict) or not isinstance(post, dict):
        return out
    out["result_delta"] = {"pre": pre.get("result"), "post": post.get("result"),
                           "changed": pre.get("result") != post.get("result")}
    pp, qp = pre.get("players") or [], post.get("players") or []
    if len(pp) == 2 and len(qp) == 2:
        prize = {}
        zone = {}
        hp = {}
        for seat in (0, 1):
            for key in ("prize_count",):
                a, b = pp[seat].get(key), qp[seat].get(key)
                if isinstance(a, int) and isinstance(b, int):
                    prize[f"p{seat}"] = b - a
            for key in ("hand_count", "deck_count", "discard_count", "bench_count",
                        "energy_total"):
                a, b = pp[seat].get(key), qp[seat].get(key)
                if isinstance(a, int) and isinstance(b, int) and a != b:
                    zone[f"p{seat}.{key}"] = b - a
            ah0, ah1 = pp[seat].get("active_hp") or [], qp[seat].get("active_hp") or []
            if ah0 and ah1 and isinstance(ah0[0], int) and isinstance(ah1[0], int):
                hp[f"p{seat}.active_hp"] = ah1[0] - ah0[0]
        out["prize_delta"] = prize or None
        out["zone_delta"] = zone or None
        out["hp_delta"] = hp or None
    return out


# --------------------------------------------------------------------------- inputs


def build_search_inputs_from_frame(frame: Any,
                                   assumption_mode: str = "trace_full_state_if_available"
                                   ) -> dict:
    """Build the (count-based) inputs needed to seed a search from a frame.

    Returns ``{ok, reason, observation, your_index, deck_needs_fill,
    your_deck_count, your_prize_count, opponent_deck_count, opponent_prize_count,
    opponent_hand_count, opponent_active_facedown, n_options, min_count,
    max_count, assumption}``. Hidden-zone *card IDs* are intentionally NOT
    fabricated here (the module stays pure / cg-free); the subprocess worker fills
    them with valid basic-Pokémon IDs and records the assumption. Never raises.
    """
    assumption = SearchAssumption(mode=assumption_mode)
    base = {
        "ok": False, "reason": None, "observation": None, "your_index": None,
        "deck_needs_fill": False, "your_deck_count": 0, "your_prize_count": 0,
        "opponent_deck_count": 0, "opponent_prize_count": 0, "opponent_hand_count": 0,
        "opponent_active_facedown": False, "n_options": 0, "min_count": None,
        "max_count": None, "assumption": assumption.to_dict(),
    }
    try:
        obs = _extract_observation(frame)
        if not isinstance(obs, dict):
            base["reason"] = "no_observation"
            return base
        if not obs.get("search_begin_input"):
            base["reason"] = "no_search_begin_input"
            return base
        cur = obs.get("current")
        sel = obs.get("select")
        if not isinstance(cur, dict) or not isinstance(sel, dict):
            base["reason"] = "incomplete_state"
            return base
        players = cur.get("players")
        if not isinstance(players, list) or len(players) != 2:
            base["reason"] = "bad_players"
            return base
        yi = cur.get("yourIndex")
        if yi not in (0, 1):
            base["reason"] = "bad_your_index"
            return base
        me, opp = players[yi], players[1 - yi]
        opt = sel.get("option") or []
        oa = opp.get("active") or []
        base.update({
            "ok": True, "reason": "ok", "observation": obs, "your_index": yi,
            "deck_needs_fill": sel.get("deck") is None,
            "your_deck_count": int(me.get("deckCount") or 0),
            "your_prize_count": len(me.get("prize") or []),
            "opponent_deck_count": int(opp.get("deckCount") or 0),
            "opponent_prize_count": len(opp.get("prize") or []),
            "opponent_hand_count": int(opp.get("handCount") or 0),
            "opponent_active_facedown": bool(len(oa) > 0 and oa[0] is None),
            "n_options": len(opt),
            "min_count": sel.get("minCount"),
            "max_count": sel.get("maxCount"),
        })
        return base
    except Exception as exc:  # noqa: BLE001
        base["reason"] = f"build_error:{type(exc).__name__}"
        return base


# --------------------------------------------------------------------------- worker


def _worker_env() -> dict:
    env = dict(os.environ)
    extra = [str(_SDK), str(_REPO / "src")]
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join([p for p in extra + [prev] if p])
    return env


def _run_worker(tasks: list[dict], timeout_s: float) -> dict[str, dict]:
    """Run a worklist of search tasks in ONE hard-timeout subprocess.

    Returns a map ``task_id -> result dict``. Any task without a streamed result
    (e.g. the worker was killed by a native hang) is reported as timed_out.
    Never raises.
    """
    results: dict[str, dict] = {}
    if not tasks:
        return results
    per = max(1.0, float(timeout_s))
    # Tasks are near-instant; ``per`` only bounds the single in-flight native call.
    # Cap the wall so a native hang costs seconds, not minutes (unstarted tasks are
    # then reported timed_out).
    wall = min(60.0, per + 8.0 + 0.3 * len(tasks))
    tmp = Path(tempfile.mkdtemp(prefix="pass46e_oracle_"))
    wl = tmp / "worklist.json"
    out = tmp / "out.jsonl"
    try:
        wl.write_text(json.dumps({"per_task_timeout_s": per, "tasks": tasks}),
                      encoding="utf-8")
        if not _WORKER.exists():
            for t in tasks:
                results[t["id"]] = {"ok": False, "error": "worker_missing",
                                    "timed_out": False}
            return results
        try:
            subprocess.run(
                [sys.executable, str(_WORKER), str(wl), str(out)],
                env=_worker_env(), cwd=str(_REPO), timeout=wall,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
        except subprocess.TimeoutExpired:
            pass
        except Exception:  # noqa: BLE001
            pass
        if out.exists():
            for line in out.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                tid = rec.get("id")
                if tid is not None and rec.get("kind") == "result":
                    results[tid] = rec
        for t in tasks:
            results.setdefault(t["id"], {"ok": False, "error": "no_result_native_hang",
                                         "timed_out": True})
        return results
    finally:
        try:
            for p in (wl, out):
                if p.exists():
                    p.unlink()
            tmp.rmdir()
        except Exception:  # noqa: BLE001
            pass


def _task_from_inputs(task_id: str, inputs: dict, selected: list[int]) -> dict:
    return {
        "id": task_id,
        "observation": inputs["observation"],
        "your_index": inputs["your_index"],
        "deck_needs_fill": inputs["deck_needs_fill"],
        "your_deck_count": inputs["your_deck_count"],
        "your_prize_count": inputs["your_prize_count"],
        "opponent_deck_count": inputs["opponent_deck_count"],
        "opponent_prize_count": inputs["opponent_prize_count"],
        "opponent_hand_count": inputs["opponent_hand_count"],
        "opponent_active_facedown": inputs["opponent_active_facedown"],
        "selected": list(selected),
    }


def _outcome_from_worker(selected: list[int], inputs: dict, rec: dict) -> ActionOutcome:
    pre_sig = signature_from_current(inputs["observation"].get("current"),
                                     inputs["your_index"])
    post_sig = rec.get("post_signature")
    diffs = _diff_summary(pre_sig, post_sig)
    return ActionOutcome(
        selected_indices=list(selected),
        legal=rec.get("legal"),
        error=rec.get("error"),
        timed_out=bool(rec.get("timed_out")),
        elapsed_s=rec.get("elapsed_s"),
        pre_signature=pre_sig,
        post_signature=post_sig,
        prize_delta=diffs["prize_delta"],
        hp_delta_summary=diffs["hp_delta"],
        zone_delta_summary=diffs["zone_delta"],
        log_delta_summary=rec.get("log_delta_summary"),
        result_delta=diffs["result_delta"],
        assumption_mode=inputs["assumption"]["mode"],
    )


# --------------------------------------------------------------------------- public ops


def evaluate_action_once(frame: Any, selected_indices: Any,
                         assumption_mode: str = "trace_full_state_if_available",
                         timeout_s: float = 8.0) -> OracleResult:
    """Evaluate the immediate one-step consequence of ``selected_indices``.

    Subprocess-isolated, hard-timeout, never-raise. ``supported_level`` is at most
    ``assumption_based_hidden_state`` here — only the calibration harness, which
    has the actual next frame, may upgrade an evaluation's evidence to
    ``exact_full_state_replay``.
    """
    res = OracleResult()
    try:
        if not isinstance(selected_indices, list) or \
                not all(isinstance(i, int) for i in selected_indices):
            res.warnings.append("selected_indices must be a list[int]")
            return res
        inputs = build_search_inputs_from_frame(frame, assumption_mode)
        if not inputs["ok"]:
            res.warnings.append(f"inputs_unbuildable:{inputs['reason']}")
            return res
        if not _is_index_action(selected_indices, inputs["n_options"],
                                inputs["min_count"], inputs["max_count"]):
            res.warnings.append("selected_indices illegal for this option set")
            res.outcome = ActionOutcome(selected_indices=list(selected_indices),
                                        legal=False,
                                        assumption_mode=inputs["assumption"]["mode"])
            return res
        task = _task_from_inputs("eval", inputs, selected_indices)
        rec = _run_worker([task], timeout_s).get("eval", {})
        outcome = _outcome_from_worker(selected_indices, inputs, rec)
        res.outcome = outcome
        if rec.get("timed_out"):
            res.supported_level = "unsupported_or_failed"
            res.warnings.append("search timed out")
        elif rec.get("ok") and outcome.post_signature is not None:
            res.ok = True
            res.supported_level = "assumption_based_hidden_state"
        else:
            res.supported_level = "unsupported_or_failed"
            if rec.get("error"):
                res.warnings.append(f"search_error:{rec['error']}")
        return res
    except Exception as exc:  # noqa: BLE001
        res.warnings.append(f"evaluate_error:{type(exc).__name__}")
        return res


def evaluate_actions_batch(items: Any,
                           assumption_mode: str = "trace_full_state_if_available",
                           timeout_s: float = 6.0, chunk_size: int = 20) -> list:
    """Evaluate many ``(frame, selected_indices)`` items efficiently.

    Imports cg ONCE per chunk subprocess (instead of once per item). Returns a list
    of ``OracleResult`` aligned to ``items``. Chunking isolates a native hang to a
    single chunk. Never-raise.
    """
    out_results: list = []
    try:
        items = list(items)
    except Exception:  # noqa: BLE001
        return out_results
    built: list = []  # (orig_index, inputs, selected) or (orig_index, None, reason)
    for idx, pair in enumerate(items):
        try:
            frame, selected = pair
        except Exception:  # noqa: BLE001
            built.append((idx, None, "bad_item"))
            continue
        if not isinstance(selected, list) or not all(isinstance(i, int) for i in selected):
            built.append((idx, None, "bad_selected"))
            continue
        inputs = build_search_inputs_from_frame(frame, assumption_mode)
        if not inputs["ok"]:
            built.append((idx, None, f"inputs_unbuildable:{inputs['reason']}"))
            continue
        if not _is_index_action(selected, inputs["n_options"],
                                inputs["min_count"], inputs["max_count"]):
            built.append((idx, None, "illegal_action"))
            continue
        built.append((idx, inputs, selected))

    by_index: dict[int, OracleResult] = {}
    runnable = [b for b in built if b[1] is not None]
    for start in range(0, len(runnable), max(1, int(chunk_size))):
        chunk = runnable[start:start + max(1, int(chunk_size))]
        tasks = [_task_from_inputs(f"i{b[0]}", b[1], b[2]) for b in chunk]
        recs = _run_worker(tasks, timeout_s)
        for (idx, inputs, selected) in chunk:
            rec = recs.get(f"i{idx}", {})
            outcome = _outcome_from_worker(selected, inputs, rec)
            r = OracleResult(outcome=outcome)
            if rec.get("timed_out"):
                r.supported_level = "unsupported_or_failed"
                r.warnings.append("search timed out")
            elif rec.get("ok") and outcome.post_signature is not None:
                r.ok = True
                r.supported_level = "assumption_based_hidden_state"
            else:
                r.supported_level = "unsupported_or_failed"
                if rec.get("error"):
                    r.warnings.append(f"search_error:{rec['error']}")
            by_index[idx] = r

    for b in built:
        idx = b[0]
        if idx in by_index:
            out_results.append(by_index[idx])
        else:
            r = OracleResult()
            r.warnings.append(b[2] if len(b) > 2 and isinstance(b[2], str) else "unbuilt")
            out_results.append(r)
    # restore original order (built preserves order already)
    return out_results


# transparent one-step scoring: NOT a global optimum, only a heuristic over the
# immediate visible delta under the recorded hidden-state assumption.
_SCORE_WEIGHTS = {
    "win": 1000.0, "loss": -1000.0, "draw": -50.0,
    "prize_taken": 60.0, "prize_conceded": -60.0,
    "opp_active_damage": 1.0, "own_active_damage": -0.5,
    "own_energy_attached": 8.0, "own_deckout": -200.0,
    "invalid": -500.0, "excess_discard": -3.0,
}


def score_outcome_generic_progress_v0(outcome: ActionOutcome,
                                      your_index: Optional[int]) -> dict:
    """Transparent ``generic_progress_v0`` one-step score (never-raise).

    Positive: win/result improvement, prizes taken, opponent active HP reduction,
    your prize-remaining reduction, energy attached to your Pokémon. Negative:
    invalid/error/timeout, prizes conceded, deckout risk, excess discard. Returns
    ``{score, breakdown, label}``. This is ``one_step_score_rank`` under the
    assumption — NOT a best/optimal action.
    """
    bd: dict[str, float] = {}
    try:
        if outcome is None or outcome.timed_out or outcome.legal is False \
                or outcome.error or outcome.post_signature is None:
            bd["invalid"] = _SCORE_WEIGHTS["invalid"]
            return {"score": sum(bd.values()), "breakdown": bd,
                    "label": "one_step_score_rank_under_assumption"}
        yi = your_index if your_index in (0, 1) else \
            (outcome.post_signature.get("your_index") if outcome.post_signature else None)
        rd = outcome.result_delta or {}
        post_result = rd.get("post")
        if isinstance(post_result, int) and post_result in (0, 1, 2):
            if post_result == 2:
                bd["draw"] = _SCORE_WEIGHTS["draw"]
            elif yi in (0, 1):
                bd["win" if post_result == yi else "loss"] = \
                    _SCORE_WEIGHTS["win" if post_result == yi else "loss"]
        prize = outcome.prize_delta or {}
        if yi in (0, 1):
            mine = prize.get(f"p{yi}")
            theirs = prize.get(f"p{1 - yi}")
            if isinstance(mine, int) and mine < 0:
                bd["prize_taken"] = _SCORE_WEIGHTS["prize_taken"] * (-mine)
            if isinstance(theirs, int) and theirs < 0:
                bd["prize_conceded"] = _SCORE_WEIGHTS["prize_conceded"] * (-theirs)
        hp = outcome.hp_delta_summary or {}
        if yi in (0, 1):
            opp_hp = hp.get(f"p{1 - yi}.active_hp")
            own_hp = hp.get(f"p{yi}.active_hp")
            if isinstance(opp_hp, int) and opp_hp < 0:
                bd["opp_active_damage"] = _SCORE_WEIGHTS["opp_active_damage"] * (-opp_hp)
            if isinstance(own_hp, int) and own_hp < 0:
                bd["own_active_damage"] = _SCORE_WEIGHTS["own_active_damage"] * (-own_hp)
        zone = outcome.zone_delta_summary or {}
        if yi in (0, 1):
            e = zone.get(f"p{yi}.energy_total")
            if isinstance(e, int) and e > 0:
                bd["own_energy_attached"] = _SCORE_WEIGHTS["own_energy_attached"] * e
            disc = zone.get(f"p{yi}.discard_count")
            if isinstance(disc, int) and disc > 0:
                bd["excess_discard"] = _SCORE_WEIGHTS["excess_discard"] * disc
        post_players = (outcome.post_signature or {}).get("players") or []
        if yi in (0, 1) and len(post_players) == 2:
            if post_players[yi].get("deck_count") == 0:
                bd["own_deckout"] = _SCORE_WEIGHTS["own_deckout"]
        return {"score": sum(bd.values()), "breakdown": bd,
                "label": "one_step_score_rank_under_assumption"}
    except Exception as exc:  # noqa: BLE001
        bd["error"] = _SCORE_WEIGHTS["invalid"]
        return {"score": sum(bd.values()), "breakdown": bd,
                "label": "one_step_score_rank_under_assumption",
                "warning": f"score_error:{type(exc).__name__}"}


def _candidate_select_lists(inputs: dict, actual: Optional[list[int]],
                            max_actions: int) -> list[list[int]]:
    """Bounded set of legal candidate select-lists. Does NOT explode combinatorially.

    Single-select contexts (maxCount == 1): each legal single index up to
    ``max_actions``. Multi-select contexts: ONLY the actual chosen action (if
    legal) plus, when room remains, a few singletons — never the full product.
    """
    n = inputs["n_options"]
    mn = inputs["min_count"] or 0
    mx = inputs["max_count"] or 0
    cands: list[list[int]] = []
    try:
        mn_i, mx_i = int(mn), int(mx)
    except Exception:  # noqa: BLE001
        mn_i, mx_i = 1, 1
    if actual and _is_index_action(actual, n, mn_i, mx_i):
        cands.append(list(actual))
    if mx_i <= 1 and mn_i <= 1:
        for i in range(n):
            c = [i]
            if c not in cands:
                cands.append(c)
            if len(cands) >= max_actions:
                break
    return cands[:max_actions]


def rank_legal_actions_one_step(frame: Any,
                                scoring_profile: str = "generic_progress_v0",
                                max_actions: int = 8,
                                timeout_s: float = 8.0) -> dict:
    """Rank a bounded set of legal one-step actions by ``generic_progress_v0``.

    Never-raise. Returns ``{ok, supported_level, scoring_profile, n_candidates,
    ranking:[{selected_indices, score, breakdown, supported_level, ...}],
    actual_action, actual_rank, assumption, label, unsupported_claims, warnings}``.
    The label makes explicit this is a one-step score rank under the assumption,
    NOT a best/optimal action.
    """
    out = {
        "ok": False, "supported_level": "unsupported_or_failed",
        "scoring_profile": scoring_profile, "n_candidates": 0, "ranking": [],
        "actual_action": None, "actual_rank": None, "assumption": None,
        "label": "one_step_score_rank_under_assumption_not_best_action",
        "unsupported_claims": unsupported_search_claims(), "warnings": [],
    }
    try:
        inputs = build_search_inputs_from_frame(frame)
        out["assumption"] = inputs["assumption"]
        if not inputs["ok"]:
            out["warnings"].append(f"inputs_unbuildable:{inputs['reason']}")
            return out
        if scoring_profile != "generic_progress_v0":
            out["warnings"].append(f"unknown_scoring_profile:{scoring_profile}; "
                                   "using generic_progress_v0")
        actual = _selected_from_frame(frame)
        actual = actual if (actual and _is_index_action(
            actual, inputs["n_options"], inputs["min_count"], inputs["max_count"])) else None
        out["actual_action"] = actual
        cands = _candidate_select_lists(inputs, actual, max(1, int(max_actions)))
        if not cands:
            out["warnings"].append("no_legal_candidates")
            return out
        tasks = [_task_from_inputs(f"c{idx}", inputs, c) for idx, c in enumerate(cands)]
        recs = _run_worker(tasks, timeout_s)
        scored = []
        any_ok = False
        for idx, c in enumerate(cands):
            rec = recs.get(f"c{idx}", {})
            outcome = _outcome_from_worker(c, inputs, rec)
            if rec.get("ok") and outcome.post_signature is not None and not rec.get("timed_out"):
                sl = "assumption_based_hidden_state"
                any_ok = True
            else:
                sl = "unsupported_or_failed"
            sc = score_outcome_generic_progress_v0(outcome, inputs["your_index"])
            scored.append({
                "selected_indices": c, "score": sc["score"],
                "breakdown": sc["breakdown"], "supported_level": sl,
                "timed_out": bool(rec.get("timed_out")), "error": rec.get("error"),
                "is_actual": (actual is not None and c == actual),
            })
        scored.sort(key=lambda r: (r["supported_level"] == "unsupported_or_failed",
                                   -r["score"]))
        for rank, r in enumerate(scored):
            r["rank"] = rank
            if r["is_actual"]:
                out["actual_rank"] = rank
        out["ranking"] = scored
        out["n_candidates"] = len(scored)
        out["ok"] = any_ok
        out["supported_level"] = "assumption_based_hidden_state" if any_ok \
            else "unsupported_or_failed"
        return out
    except Exception as exc:  # noqa: BLE001
        out["warnings"].append(f"rank_error:{type(exc).__name__}")
        return out
