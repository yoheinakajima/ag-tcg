#!/usr/bin/env python3
"""Pass 29 (Parts K & L) — decision replay + focused eval of effect_loop_exit_guard_v1.

Re-runs the looping pairing (Venusaur vs Water) with BOTH the baseline pilot and
the guarded pilot, and measures whether the guard actually breaks the
non-progressing loop and lets the game terminate. We measure, never assume:

  * venusaur-seat decisions per game (loop -> thousands; healthy -> hundreds),
  * the longest non-progressing static-board run (the loop length),
  * whether the game terminated vs hit the engine step cap,
  * the result/reward.

If the guard is inert or harmful, that is reported honestly (-> reject).
Outputs data/experiments/pass29_effect_loop_guard_eval.{json,md}.
"""
from __future__ import annotations

import json
import signal
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))
import run_pass28_forensic_trace as p28  # noqa: E402

CAND27 = REPO / "data" / "submissions" / "candidates_pass27"
CAND29 = REPO / "data" / "submissions" / "candidates_pass29"
OUT_JSON = REPO / "data" / "experiments" / "pass29_effect_loop_guard_eval.json"
OUT_MD = REPO / "data" / "experiments" / "pass29_effect_loop_guard_eval.md"

GAMES_PER_ARM = 3
GAME_TIMEOUT_S = 120


class _GameTimeout(Exception):
    pass


def _load_main_from_tar(tar: Path):
    tmp = Path(tempfile.mkdtemp(prefix="p29eval_"))
    with tarfile.open(tar) as tf:
        tf.extractall(tmp)
    return p28._load_candidate_module(next(tmp.rglob("main.py")))


def _board_sig(b):
    if not isinstance(b, dict):
        return None
    a = b.get("active") or {}
    return (b.get("deck_count"), len(b.get("hand") or []),
            a.get("card_id") if isinstance(a, dict) else None,
            len(b.get("discard") or []), b.get("prize_count"))


def _make_metered(mod):
    entry = p28._entrypoint(mod)
    res = p28._resolver(mod)
    st = {"decisions": 0, "cur_sig": None, "cur_run": 0, "max_run": 0}

    def wrapped(obs, *a, **k):
        action = entry(obs, *a, **k)
        try:
            sel = obs.get("select") if isinstance(obs, dict) else None
            if isinstance(sel, dict) and (sel.get("option") or sel.get("options")):
                st["decisions"] += 1
                sig = _board_sig(p28._board_snapshot(obs, res))
                if sig is not None and sig == st["cur_sig"]:
                    st["cur_run"] += 1
                else:
                    st["cur_sig"] = sig
                    st["cur_run"] = 1
                st["max_run"] = max(st["max_run"], st["cur_run"])
        except Exception:
            pass
        return action

    return wrapped, st


def _alarm(_s, _f):
    raise _GameTimeout()


def _run_arm(label, ven_mod, water_mod):
    from kaggle_environments import make
    games = []
    for g in range(GAMES_PER_ARM):
        ven_agent, ven_st = _make_metered(ven_mod)
        wat_agent, _ = _make_metered(water_mod)
        signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(GAME_TIMEOUT_S)
        hit_cap = False
        n_steps = None
        rewards = None
        try:
            env = make("cabt")
            env.run([ven_agent, wat_agent])
            n_steps = len(env.steps)
            try:
                rewards = [s.get("reward") for s in env.steps[-1]]
            except Exception:
                rewards = None
        except _GameTimeout:
            hit_cap = True
        except Exception as exc:  # noqa: BLE001
            print(f"  {label} game{g} ended: {exc!r}")
        finally:
            signal.alarm(0)
        games.append({
            "game": g, "ven_decisions": ven_st["decisions"],
            "ven_max_static_run": ven_st["max_run"],
            "env_steps": n_steps, "hit_timeout_cap": hit_cap,
            "rewards": rewards,
        })
        print(f"  {label} game{g}: ven_decisions={ven_st['decisions']} "
              f"max_static_run={ven_st['max_run']} steps={n_steps} "
              f"timeout={hit_cap}")
    return games


def _summary(games):
    runs = [g["ven_max_static_run"] for g in games]
    decs = [g["ven_decisions"] for g in games]
    caps = sum(1 for g in games if g["hit_timeout_cap"])
    return {
        "games": len(games),
        "mean_ven_decisions": round(sum(decs) / len(decs), 1) if decs else None,
        "max_static_run_observed": max(runs) if runs else None,
        "min_static_run_observed": min(runs) if runs else None,
        "games_hit_timeout_cap": caps,
        "detail": games,
    }


def main() -> int:
    base_mod = _load_main_from_tar(CAND27 / "league_mega_venusaur_tank.tar.gz")
    guard_mod = _load_main_from_tar(CAND29 / "effect_loop_exit_guard_v1.tar.gz")
    water_mod = _load_main_from_tar(CAND27 / "league_water_core_reference.tar.gz")

    print("baseline arm:")
    base_games = _run_arm("baseline", base_mod, water_mod)
    print("guard arm:")
    guard_games = _run_arm("guard", guard_mod, water_mod)

    base_s = _summary(base_games)
    guard_s = _summary(guard_games)

    # Verdict logic — measured, not assumed.
    loop_broken = (guard_s["max_static_run_observed"] is not None
                   and base_s["max_static_run_observed"] is not None
                   and guard_s["max_static_run_observed"]
                   < base_s["max_static_run_observed"] * 0.5)
    fewer_timeouts = guard_s["games_hit_timeout_cap"] < base_s["games_hit_timeout_cap"]
    non_inert = (guard_s["max_static_run_observed"]
                 != base_s["max_static_run_observed"]
                 or guard_s["mean_ven_decisions"] != base_s["mean_ven_decisions"])
    if loop_broken or fewer_timeouts:
        verdict = "effect_loop_exit_candidate_built"
        verdict_note = ("the guard measurably shortened the non-progressing loop "
                        "and/or reduced step-cap timeouts vs baseline")
    elif not non_inert:
        verdict = "effect_loop_exit_rejected"
        verdict_note = ("the guard was inert — no measurable difference vs baseline; "
                        "rejected rather than promoted")
    else:
        verdict = "effect_loop_exit_rejected"
        verdict_note = ("the guard changed behaviour but did not break the loop or "
                        "reduce timeouts; rejected pending more observability")

    out = {
        "pass": "29", "parts": ["K", "L"],
        "pairing": "venusaur__vs__water (the looping pairing)",
        "games_per_arm": GAMES_PER_ARM, "game_timeout_s": GAME_TIMEOUT_S,
        "baseline": base_s, "guard": guard_s,
        "loop_broken_vs_baseline": loop_broken,
        "fewer_timeouts_vs_baseline": fewer_timeouts,
        "guard_non_inert": non_inert,
        "verdict": verdict, "verdict_note": verdict_note,
        "no_upload": True, "local_only": True,
    }
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

    L = ["# Pass 29 — Effect-Loop Guard Decision Replay + Eval (Parts K & L)", "",
         f"**Pairing:** {out['pairing']} — {GAMES_PER_ARM} games/arm, "
         f"{GAME_TIMEOUT_S}s cap.", "",
         f"**Verdict: `{verdict}`** — {verdict_note}.", "",
         "## Summary", "",
         "| arm | mean ven decisions | max static run | min static run | "
         "timeouts |", "|---|---|---|---|---|",
         f"| baseline | {base_s['mean_ven_decisions']} | "
         f"{base_s['max_static_run_observed']} | "
         f"{base_s['min_static_run_observed']} | "
         f"{base_s['games_hit_timeout_cap']}/{base_s['games']} |",
         f"| guard | {guard_s['mean_ven_decisions']} | "
         f"{guard_s['max_static_run_observed']} | "
         f"{guard_s['min_static_run_observed']} | "
         f"{guard_s['games_hit_timeout_cap']}/{guard_s['games']} |", "",
         f"- loop_broken_vs_baseline: **{loop_broken}**.",
         f"- fewer_timeouts_vs_baseline: **{fewer_timeouts}**.",
         f"- guard_non_inert: **{non_inert}**.", ""]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")
    print(f"VERDICT: {verdict} ({verdict_note})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
