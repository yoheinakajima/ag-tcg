#!/usr/bin/env python3
"""Pass 28 (Parts D+E) — cross-deck forensic ACTION-LEVEL trace. LOCAL/READ-ONLY.

Runs small targeted diagnostic games between existing Pass-27 candidates and
records, for EVERY decision both seats make, the full action context: the cabt
select context, all legal options, the chosen indices, and the RESOLVED action
class / card / role / energy color. This is the evidence base that lets Pass 28
attribute each deck's failures to a CAUSE proven from actions, not inferred from
win rate.

How traces are captured (no agent code is modified, root files untouched):
  * each candidate's main.py is exec'd in-process with its real __file__ so its
    own deck.csv loads; the LAST top-level callable (the real cabt entrypoint) is
    wrapped with a recorder.
  * the wrapper calls the real agent to get the action, then resolves the chosen
    option(s) using THAT candidate's own resolve_option_card/build_board/card_id
    and embedded _CP_PLAYBOOK, so resolution matches what the pilot itself sees.
  * card ids -> names / energy colors come from the local card DB (gitignored).

11 targeted pairings, 2 games/seat (seat-swapped). Resumable: each call plays as
many pairings as fit the per-call budget, persisting crash-safe progress. Durant
is run self-only for INVALID/failure diagnosis (never as a league participant).

Outputs (data/experiments/): pass28_action_trace.jsonl,
pass28_diagnostic_trace.{json,jsonl,md}, pass28_action_trace_summary.{json,md},
sentinel pass28_forensic_trace.DONE. No upload, no submission, no GitHub push.
"""
from __future__ import annotations

import csv
import json
import os
import signal
import sys
import tempfile
import time
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

EXP = REPO / "data" / "experiments"
CAND = REPO / "data" / "submissions" / "candidates_pass27"
CARD_DB = REPO / "data" / "cards" / "EN_Card_Data.csv"
PROGRESS = EXP / "pass28_forensic_trace_progress.json"
JSONL = EXP / "pass28_action_trace.jsonl"

GAMES_PER_SEAT = int(os.environ.get("P28_GAMES_PER_SEAT", "2"))
GAME_TIMEOUT_S = int(os.environ.get("P28_GAME_TIMEOUT_S", "60"))
PER_CALL_BUDGET_S = int(os.environ.get("P28_PER_CALL_BUDGET_S", "85"))

# family_id -> tarball stem
DECKS = {
    "water": "league_water_core_reference",
    "raging_bolt": "league_raging_bolt_ogerpon",
    "dragapult": "league_dragapult_spread",
    "gardevoir": "league_mega_gardevoir_psychic_ramp",
    "charizard": "league_mega_charizard_x_burst",
    "venusaur": "league_mega_venusaur_tank",
    "durant": "league_durant_deckout_carousel",
}

# (key, family_a, family_b, mode) — mode: league or failure_diag
PAIRINGS = [
    ("raging_bolt__vs__water", "raging_bolt", "water", "league"),
    ("raging_bolt__self", "raging_bolt", "raging_bolt", "league"),
    ("raging_bolt__vs__dragapult", "raging_bolt", "dragapult", "league"),
    ("gardevoir__vs__water", "gardevoir", "water", "league"),
    ("gardevoir__self", "gardevoir", "gardevoir", "league"),
    ("charizard__vs__water", "charizard", "water", "league"),
    ("charizard__self", "charizard", "charizard", "league"),
    ("venusaur__vs__water", "venusaur", "water", "league"),
    ("dragapult__vs__water", "dragapult", "water", "league"),
    ("dragapult__self", "dragapult", "dragapult", "league"),
    ("durant__self", "durant", "durant", "failure_diag"),
]

DISCLAIMER = (
    "INTERNAL DIAGNOSTIC TRACE — NOT a Kaggle leaderboard and NOT a promotion "
    "signal. Both seats are OUR portfolio decks driven by the same generic core "
    "pilot; these traces measure what ACTIONS the pilot takes with each deck. No "
    "candidate is uploaded or submitted."
)

# cabt option.type -> coarse action class (confirmed via replays + pass28 probe).
TYPE_CLASS = {
    1: "effect_choice", 2: "effect_choice", 3: "place_card",
    7: "play_from_hand", 8: "attach_energy", 9: "in_play_action",
    10: "in_play_action", 12: "end", 13: "attack", 14: "end",
}


class _Timeout(Exception):
    pass


def _alarm(_s, _f):
    raise _Timeout()


# --------------------------------------------------------------------------- #
# Card DB (id -> name, energy color, basic-energy flag, stage, category).
# --------------------------------------------------------------------------- #
def _load_card_db() -> dict:
    db: dict[int, dict] = {}
    if not CARD_DB.exists():
        return db
    with CARD_DB.open(encoding="utf-8", errors="replace") as fh:
        r = csv.reader(fh)
        next(r, None)
        for row in r:
            if len(row) < 7:
                continue
            try:
                cid = int(row[0])
            except (TypeError, ValueError):
                continue
            name = row[1]
            stage = row[4]
            color = None
            is_basic_energy = stage == "Basic Energy"
            if "Energy" in name and "{" in name and "}" in name:
                color = name.split("{", 1)[1].split("}", 1)[0]
            db[cid] = {"name": name, "stage": stage, "category": row[6],
                       "energy_color": color, "is_basic_energy": is_basic_energy}
    return db


CARD_DB_MAP = _load_card_db()


def _card_name(cid):
    rec = CARD_DB_MAP.get(cid)
    return rec["name"] if rec else None


def _energy_color(cid):
    rec = CARD_DB_MAP.get(cid)
    return rec["energy_color"] if rec else None


# --------------------------------------------------------------------------- #
# Load a candidate as an in-process module and wrap its entrypoint.
# --------------------------------------------------------------------------- #
def _load_candidate_module(main_path: Path) -> types.ModuleType:
    mod = types.ModuleType(f"pass28_cand_{main_path.parent.name}")
    mod.__file__ = str(main_path)
    mod.__dict__["__name__"] = mod.__name__
    code = main_path.read_text(encoding="utf-8")
    exec(compile(code, str(main_path), "exec"), mod.__dict__)  # noqa: S102 (our artifact)
    return mod


def _entrypoint(mod: types.ModuleType):
    """The cabt entrypoint = LAST top-level callable (kaggle convention)."""
    last = None
    for name, val in mod.__dict__.items():
        if name.startswith("__"):
            continue
        if callable(val) and isinstance(val, types.FunctionType):
            last = val
    return last


def _resolver(mod: types.ModuleType):
    """Best-effort handles to a candidate's own resolution helpers."""
    g = mod.__dict__
    return {
        "resolve_option_card": g.get("resolve_option_card"),
        "build_board": g.get("build_board"),
        "card_id": g.get("card_id"),
        "playbook": g.get("_CP_PLAYBOOK") or {},
    }


def _roles_for(cid, playbook) -> list:
    out = []
    for role, ids in (playbook.get("roles") or {}).items():
        try:
            if cid in [int(x) for x in ids]:
                out.append(role)
        except (TypeError, ValueError):
            continue
    return sorted(out)


def _safe(fn, *a):
    if not callable(fn):
        return None
    try:
        return fn(*a)
    except Exception:
        return None


def _resolve_option(obs, opt, res):
    """Resolve a single option dict -> (action_class, card_id, name, roles, extra)."""
    if not isinstance(opt, dict):
        return {"action_class": "unknown", "card_id": None}
    otype = opt.get("type")
    klass = TYPE_CLASS.get(otype, "unknown")
    cid = _safe(res["resolve_option_card"], obs, opt)
    extra: dict = {}
    if otype == 8:  # attach energy: hand[index] is the energy card
        idx = opt.get("index")
        extra["target_in_play_area"] = opt.get("inPlayArea")
        extra["target_in_play_index"] = opt.get("inPlayIndex")
        if cid is not None:
            extra["energy_color"] = _energy_color(cid)
    if otype == 13:
        extra["attackId"] = opt.get("attackId")
    return {"action_class": klass, "type": otype, "card_id": cid,
            "card_name": _card_name(cid) if cid is not None else None,
            "roles": _roles_for(cid, res["playbook"]) if cid is not None else [],
            "extra": extra}


def _board_snapshot(obs, res) -> dict:
    board = _safe(res["build_board"], obs) or {}
    if not isinstance(board, dict):
        board = {}

    def _ids(zone):
        out = []
        for c in zone or []:
            cid = c.get("card_id") if isinstance(c, dict) else None
            out.append({"card_id": cid, "name": _card_name(cid)})
        return out

    active = board.get("active")
    active_cid = active.get("card_id") if isinstance(active, dict) else None
    return {
        "active": {"card_id": active_cid, "name": _card_name(active_cid)}
        if active_cid is not None else None,
        "bench": _ids(board.get("bench")),
        "hand": _ids(board.get("hand")),
        "deck_count": board.get("deck_count"),
        "discard": _ids(board.get("discard")),
        "prize_count": board.get("prize_count"),
        "opponent_active": (board.get("opponent_active") or {}).get("card_id")
        if isinstance(board.get("opponent_active"), dict) else None,
    }


def _make_recorder(mod, candidate_id, family_id, sink: list):
    entry = _entrypoint(mod)
    res = _resolver(mod)
    state = {"opponent_id": None, "seat": None, "run_id": None, "game_id": None,
             "step": 0}

    def wrapped(obs, *args, **kwargs):
        action = entry(obs, *args, **kwargs)
        try:
            sel = obs.get("select") if isinstance(obs, dict) else None
            if isinstance(sel, dict):
                opts = sel.get("option") or sel.get("options") or sel.get("choices") or []
                if isinstance(opts, list) and opts:
                    chosen_idx = [i for i in (action or [])
                                  if isinstance(i, int) and 0 <= i < len(opts)]
                    resolved = [_resolve_option(obs, opts[i], res) for i in chosen_idx]
                    all_opts = [_resolve_option(obs, o, res) for o in opts]
                    classes = {o["action_class"] for o in all_opts}
                    board = _board_snapshot(obs, res)
                    rec = {
                        "run_id": state["run_id"], "game_id": state["game_id"],
                        "candidate_id": candidate_id, "family_id": family_id,
                        "opponent_id": state["opponent_id"], "seat": state["seat"],
                        "step": state["step"],
                        "turn": (obs.get("current") or {}).get("turn")
                        if isinstance(obs.get("current"), dict) else None,
                        "select_context": sel.get("context"),
                        "select_type": sel.get("type"),
                        "min_count": sel.get("minCount"), "max_count": sel.get("maxCount"),
                        "n_options": len(opts),
                        "selected_indices": chosen_idx,
                        "selected_resolved": resolved,
                        "option_classes_present": sorted(classes),
                        "attack_option_present": "attack" in classes,
                        "attach_option_present": "attach_energy" in classes,
                        "play_from_hand_present": "play_from_hand" in classes,
                        "attach_colors_available": sorted(
                            {o["extra"].get("energy_color") for o in all_opts
                             if o.get("type") == 8 and o["extra"].get("energy_color")}),
                        "board": board,
                    }
                    sink.append(rec)
                    state["step"] += 1
        except Exception as exc:  # never break a game over tracing
            sink.append({"trace_error": repr(exc), "candidate_id": candidate_id,
                         "seat": state["seat"]})
        return action

    wrapped._p28_state = state  # type: ignore[attr-defined]
    return wrapped


# --------------------------------------------------------------------------- #
# Game running.
# --------------------------------------------------------------------------- #
def _run_game(rec_a, rec_b, run_id, game_id, a_family, b_family) -> dict:
    from kaggle_environments import make
    rec_a._p28_state.update({"opponent_id": b_family, "seat": 0,
                             "run_id": run_id, "game_id": game_id, "step": 0})
    rec_b._p28_state.update({"opponent_id": a_family, "seat": 1,
                             "run_id": run_id, "game_id": game_id, "step": 0})
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(GAME_TIMEOUT_S)
    try:
        env = make("cabt")
        env.run([rec_a, rec_b])
        statuses = [s.get("status") for s in env.state]
        last = env.steps[-1]
        rewards = [s.get("reward") for s in last]
        legal = all(st in ("ACTIVE", "INACTIVE", "DONE") for st in statuses)
        return {"ok": legal, "steps": len(env.steps), "rewards": rewards,
                "statuses": statuses, "invalid": not legal, "timeout": False,
                "decisions": [rec_a._p28_state["step"], rec_b._p28_state["step"]]}
    except _Timeout:
        return {"ok": False, "timeout": True, "invalid": False, "error": "watchdog"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "timeout": False, "invalid": False, "error": repr(exc)}
    finally:
        signal.alarm(0)


def _outcome(game, seat):
    if not game.get("ok"):
        return None
    rewards = game.get("rewards") or [None, None]
    r = rewards[seat] if seat < len(rewards) else None
    if r is None:
        return None
    return "win" if r > 0 else ("loss" if r < 0 else "draw")


def _play_pairing(key, fam_a, fam_b, mode, modules, sink) -> dict:
    games = []
    seat_specs = [(fam_a, fam_b, 0)] if fam_a == fam_b else \
        [(fam_a, fam_b, 0), (fam_b, fam_a, 1)]
    # always seat-swap; for self pairings seat-swap is symmetric so do both too
    seat_specs = [(fam_a, fam_b, 0), (fam_b, fam_a, 1)]
    gi = 0
    for (first_fam, second_fam, a_seat) in seat_specs:
        for _ in range(GAMES_PER_SEAT):
            rec_first = _make_recorder(modules[first_fam][1], modules[first_fam][2],
                                       first_fam, sink)
            rec_second = _make_recorder(modules[second_fam][1], modules[second_fam][2],
                                        second_fam, sink)
            g = _run_game(rec_first, rec_second, key, f"{key}#{gi}",
                          first_fam, second_fam)
            g["a_seat"] = a_seat
            g["first_family"] = first_fam
            g["second_family"] = second_fam
            g["a_outcome"] = _outcome(g, 0)  # outcome for the FIRST listed (seat 0)
            games.append(g)
            gi += 1
    inv = sum(1 for g in games if g.get("invalid"))
    to = sum(1 for g in games if g.get("timeout"))
    crash = sum(1 for g in games if not g.get("ok") and not g.get("invalid")
                and not g.get("timeout"))
    ok = [g for g in games if g.get("ok")]
    return {
        "key": key, "family_a": fam_a, "family_b": fam_b, "mode": mode,
        "n_games": len(games), "invalids": inv, "timeouts": to, "crashes": crash,
        "errors": sorted({g.get("error") for g in games if g.get("error")}),
        "avg_steps": round(sum(g.get("steps", 0) for g in ok) / len(ok), 1)
        if ok else None,
        "games": [{"game_id": g.get("game_id"), "first_family": g["first_family"],
                   "second_family": g["second_family"], "ok": g.get("ok"),
                   "invalid": g.get("invalid"), "timeout": g.get("timeout"),
                   "steps": g.get("steps"), "rewards": g.get("rewards"),
                   "statuses": g.get("statuses"), "decisions": g.get("decisions"),
                   "first_outcome": _outcome(g, 0), "second_outcome": _outcome(g, 1)}
                  for g in games],
    }


# --------------------------------------------------------------------------- #
# Aggregation / summaries.
# --------------------------------------------------------------------------- #
def _summarize(records: list) -> dict:
    per: dict[str, dict] = {}
    for r in records:
        if "trace_error" in r:
            continue
        cid = r["candidate_id"]
        d = per.setdefault(cid, {
            "candidate_id": cid, "family_id": r["family_id"], "decisions": 0,
            "attacks_taken": 0, "attack_available_not_taken": 0,
            "attach_taken": 0, "attach_colors": {}, "attach_targets_attacker": 0,
            "attach_targets_other": 0, "plays_from_hand": 0, "evolutions": 0,
            "contexts": {}, "selected_classes": {}, "first_attack_step": None,
            "turns_with_attack_option": 0, "turns_attacked": 0,
        })
        d["decisions"] += 1
        ctx = r.get("select_context")
        d["contexts"][str(ctx)] = d["contexts"].get(str(ctx), 0) + 1
        for o in r.get("selected_resolved", []):
            kls = o.get("action_class")
            d["selected_classes"][kls] = d["selected_classes"].get(kls, 0) + 1
            if kls == "attack":
                d["attacks_taken"] += 1
                if d["first_attack_step"] is None:
                    d["first_attack_step"] = r.get("step")
            if kls == "attach_energy":
                d["attach_taken"] += 1
                col = o.get("extra", {}).get("energy_color")
                if col:
                    d["attach_colors"][col] = d["attach_colors"].get(col, 0) + 1
                tgt_area = o.get("extra", {}).get("target_in_play_area")
                # area 4 == active; treat attach to active attacker vs other
                if tgt_area == 4:
                    d["attach_targets_attacker"] += 1
                else:
                    d["attach_targets_other"] += 1
            if kls == "play_from_hand":
                d["plays_from_hand"] += 1
        if r.get("attack_option_present"):
            d["turns_with_attack_option"] += 1
            took = any(o.get("action_class") == "attack"
                       for o in r.get("selected_resolved", []))
            if took:
                d["turns_attacked"] += 1
            else:
                d["attack_available_not_taken"] += 1
    return per


def _md_diag(diag: dict) -> str:
    L = ["# Pass 28 — cross-deck forensic diagnostic trace (Parts D+E)", "",
         f"> {DISCLAIMER}", "",
         f"- status: **{diag['status']}**  pairings: "
         f"{len(diag['pairings'])}/{len(PAIRINGS)}",
         f"- upload_performed: **false**  is_kaggle_leaderboard: **false**",
         f"- games/seat: {GAMES_PER_SEAT} (seat-swapped)  total decisions traced: "
         f"{diag.get('total_decisions')}",
         "", "## Pairings",
         "| key | mode | n | invalid | timeout | crash | avg steps |",
         "|---|---|---|---|---|---|---|"]
    for key, _a, _b, _m in PAIRINGS:
        p = diag["pairings"].get(key)
        if not p:
            L.append(f"| {key} |  | _pending_ |  |  |  |  |")
            continue
        L.append(f"| {key} | {p['mode']} | {p['n_games']} | {p['invalids']} | "
                 f"{p['timeouts']} | {p['crashes']} | {p['avg_steps']} |")
    L += ["", "## Per-deck action summary (our-seat decisions)",
          "| deck | decisions | attacks taken | atk-avail-not-taken | attach | "
          "attach colors | plays | first atk step |",
          "|---|---|---|---|---|---|---|---|"]
    for cid, d in sorted(diag["per_deck"].items()):
        colors = ",".join(f"{k}:{v}" for k, v in sorted(d["attach_colors"].items()))
        L.append(f"| {cid} | {d['decisions']} | {d['attacks_taken']} | "
                 f"{d['attack_available_not_taken']} | {d['attach_taken']} | "
                 f"{colors or '—'} | {d['plays_from_hand']} | {d['first_attack_step']} |")
    L.append("")
    return "\n".join(L)


def _md_summary(per: dict) -> str:
    L = ["# Pass 28 — action-trace summary (Part E)", "",
         f"> {DISCLAIMER}", "",
         "Per-deck decision-class counts derived from the normalized action trace "
         "(`pass28_action_trace.jsonl`). 'attack-available-not-taken' counts "
         "decisions where an attack option was legal but a non-attack was chosen.", ""]
    for cid, d in sorted(per.items()):
        L += [f"## {cid} ({d['family_id']})",
              f"- decisions: {d['decisions']}",
              f"- attacks taken: {d['attacks_taken']}  (first at step "
              f"{d['first_attack_step']})",
              f"- turns w/ attack option: {d['turns_with_attack_option']}  "
              f"attacked: {d['turns_attacked']}  "
              f"available-not-taken: {d['attack_available_not_taken']}",
              f"- attach energy: {d['attach_taken']}  colors: {d['attach_colors']}  "
              f"to-active: {d['attach_targets_attacker']}  other: "
              f"{d['attach_targets_other']}",
              f"- plays from hand: {d['plays_from_hand']}",
              f"- selected classes: {d['selected_classes']}",
              f"- contexts: {d['contexts']}", ""]
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# Main (resumable).
# --------------------------------------------------------------------------- #
def _load_progress() -> dict:
    if PROGRESS.exists():
        return json.loads(PROGRESS.read_text(encoding="utf-8"))
    return {"pass": "28", "part": "D+E", "upload_performed": False,
            "is_kaggle_leaderboard": False, "disclaimer": DISCLAIMER,
            "games_per_seat": GAMES_PER_SEAT, "pairings": {}}


def _save(diag: dict, records_all: list, done: bool) -> None:
    EXP.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps(diag, indent=2, default=str), encoding="utf-8")
    per = _summarize(records_all)
    out = {**diag, "status": "complete" if done else "in_progress",
           "per_deck": per, "total_decisions": len(records_all),
           "pairings": diag["pairings"]}
    (EXP / "pass28_diagnostic_trace.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8")
    (EXP / "pass28_diagnostic_trace.md").write_text(_md_diag(out), encoding="utf-8")
    # per-pairing jsonl mirror
    with (EXP / "pass28_diagnostic_trace.jsonl").open("w", encoding="utf-8") as fh:
        for p in diag["pairings"].values():
            fh.write(json.dumps(p, default=str) + "\n")
    (EXP / "pass28_action_trace_summary.json").write_text(
        json.dumps({"disclaimer": DISCLAIMER, "upload_performed": False,
                    "per_deck": per}, indent=2, default=str), encoding="utf-8")
    (EXP / "pass28_action_trace_summary.md").write_text(
        _md_summary(per), encoding="utf-8")


def _read_all_records() -> list:
    if not JSONL.exists():
        return []
    out = []
    for line in JSONL.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    diag = _load_progress()
    sentinel = EXP / "pass28_forensic_trace.DONE"
    if sentinel.exists():
        sentinel.unlink()

    pending = [p for p in PAIRINGS if p[0] not in diag["pairings"]]
    if not pending:
        records_all = _read_all_records()
        _save(diag, records_all, done=True)
        sentinel.write_text(json.dumps({"status": "complete",
                            "pairings": len(diag["pairings"])}, indent=2),
                            encoding="utf-8")
        print(f"forensic trace COMPLETE: pairings={len(diag['pairings'])} "
              f"decisions={len(records_all)} remaining=0")
        return 0

    # On the FIRST call (no pairings done yet) truncate the jsonl fresh.
    if not diag["pairings"]:
        JSONL.write_text("", encoding="utf-8")

    needed_fams = {f for p in pending for f in (p[1], p[2])}
    start = time.time()
    played = 0
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        import run_meta_pool_eval as MEV
        modules: dict[str, tuple] = {}
        for fam in needed_fams:
            tar = CAND / f"{DECKS[fam]}.tar.gz"
            if not (tar.exists() and MEV._validate_tarball(tar)):
                diag.setdefault("notes", []).append(f"{fam}: tarball missing/invalid")
                continue
            main_path = Path(MEV._extract_agent(tar, tmp / fam))
            mod = _load_candidate_module(main_path)
            modules[fam] = (main_path, mod, DECKS[fam])
        per_pairing_games = 2 * GAMES_PER_SEAT
        for (key, fam_a, fam_b, mode) in pending:
            if time.time() - start + per_pairing_games * 1.6 > PER_CALL_BUDGET_S \
                    and played > 0:
                break
            if fam_a not in modules or fam_b not in modules:
                diag.setdefault("notes", []).append(f"{key}: module missing -> skipped")
                continue
            sink: list = []
            result = _play_pairing(key, fam_a, fam_b, mode, modules, sink)
            diag["pairings"][key] = result
            with JSONL.open("a", encoding="utf-8") as fh:
                for rec in sink:
                    fh.write(json.dumps(rec, default=str) + "\n")
            played += 1
            _save(diag, _read_all_records(), done=False)

    remaining = len([p for p in PAIRINGS if p[0] not in diag["pairings"]])
    done = remaining == 0
    records_all = _read_all_records()
    _save(diag, records_all, done=done)
    if done:
        sentinel.write_text(json.dumps({"status": "complete",
                            "pairings": len(diag["pairings"])}, indent=2),
                            encoding="utf-8")
    print(f"forensic trace: played_this_call={played} "
          f"done_total={len(diag['pairings'])}/{len(PAIRINGS)} remaining={remaining} "
          f"decisions={len(records_all)} elapsed={round(time.time() - start, 1)}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
