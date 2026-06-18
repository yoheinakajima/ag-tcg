#!/usr/bin/env python3
"""Pass 11B Part H -- small replay-informed local evaluation.

Surrogate-based and DIRECTIONAL ONLY. Opponent replays give us deck lists, not
policies, so each replay-derived deck is piloted by a stable generic surrogate
(``sim/surrogate_agents.py``). These results never equal Kaggle results and are
never sufficient on their own to promote/upload a candidate.

Gate: runs only if cabt is genuinely available (per cabt_diagnostic.json) AND the
meta pool has >= 2 distinct replay-derived opponent families. With only the
self-mirror present it runs a tiny control regression and marks the external meta
eval incomplete -- and queues nothing.

Candidates evaluated (when their artifacts exist + validate):
  - active_control          (from live_score_registry.json)
  - deck_energy_trim_light  (v2 reference, if different from active control)
  - combo_full_safety_v3_fixed as live-rejected reference (same artifact as the
    active control in this pass; recorded under its historical role)
  - pass-10 tempo candidates if their tarballs exist and validate.

Outputs:
  data/experiments/pass11b_meta_eval.json / .md
  data/experiments/pass11b_ranking.json  / .md

No upload, no submission, no candidate generation.
"""

from __future__ import annotations

import json
import signal
import sys
import tarfile
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

OUT_EVAL_JSON = REPO / "data" / "experiments" / "pass11b_meta_eval.json"
OUT_EVAL_MD = REPO / "data" / "experiments" / "pass11b_meta_eval.md"
OUT_RANK_JSON = REPO / "data" / "experiments" / "pass11b_ranking.json"
OUT_RANK_MD = REPO / "data" / "experiments" / "pass11b_ranking.md"

META_POOL = REPO / "experiments" / "meta_pool.yaml"
REGISTRY = REPO / "data" / "kaggle_uploads" / "live_score_registry.json"
DIAG = REPO / "data" / "experiments" / "cabt_diagnostic.json"
CAND_DIR = REPO / "data" / "submissions" / "candidates"
BASELINES = REPO / "data" / "baselines"

# Watchdog + budget keep the sandbox alive; tune via env if needed.
import os as _os

GAME_TIMEOUT_S = int(_os.environ.get("META_EVAL_GAME_TIMEOUT_S", "60"))
GLOBAL_BUDGET_S = int(_os.environ.get("META_EVAL_GLOBAL_BUDGET_S", "900"))
GAMES_PER_SEAT = int(_os.environ.get("META_EVAL_GAMES_PER_SEAT", "3"))

# Evolution stages of our confirmed Abomasnow line (721 Snover basic -> 722/723).
# Used only as an evolution proxy; these ids come from real replays, not invented.
EVOLUTION_CARD_IDS = {722, 723}
ATTACK_LOG_TYPE = 15  # log entries carrying an attackId are attacks (unambiguous).

PASS10_TEMPO_CANDIDATES = [
    "playbook_kyogre_tempo", "playbook_fast_evolution", "playbook_hybrid_tempo",
    "playbook_bench_safety", "playbook_attack_deadline", "deck_no_secret_box",
    "deck_less_draw_more_attack",
]


class _Timeout(Exception):
    pass


def _alarm(_s, _f):
    raise _Timeout()


def _cabt_available() -> bool:
    if not DIAG.exists():
        return False
    return bool(json.loads(DIAG.read_text(encoding="utf-8")).get("cabt_available"))


def _validate_tarball(tarball: Path) -> bool:
    if not tarball.exists():
        return False
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "validate_candidate_tarball",
            REPO / "scripts" / "validate_candidate_tarball.py")
        mod = importlib.util.module_from_spec(spec)  # type: ignore
        spec.loader.exec_module(mod)  # type: ignore
        return mod.validate(str(tarball)) == 0
    except Exception:
        return False


def _extract_agent(tarball: Path, dest: Path) -> str:
    with tarfile.open(tarball, "r:gz") as tar:
        tar.extractall(dest)  # noqa: S202 (our own build artifact)
    main = dest / "main.py"
    if main.exists():
        return str(main)
    for p in dest.rglob("main.py"):
        return str(p)
    raise FileNotFoundError(f"no main.py inside {tarball.name}")


def _active_control_name() -> str:
    if not REGISTRY.exists():
        return "combo_full_safety_v3_fixed"
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    fn = (reg.get("active_control") or {}).get("filename") or ""
    return fn.replace(".tar.gz", "") or "combo_full_safety_v3_fixed"


def _resolve_candidates(tmp: Path) -> tuple[list[dict], list[str]]:
    """Return (candidate agent dicts, notes). Each dict: id, role, agent path."""
    cands: list[dict] = []
    notes: list[str] = []
    ac_name = _active_control_name()

    # active control (tarball preferred, else baseline dir fallback).
    ac_tar = CAND_DIR / f"{ac_name}.tar.gz"
    if ac_tar.exists() and _validate_tarball(ac_tar):
        agent = _extract_agent(ac_tar, tmp / "active_control")
        cands.append({"id": ac_name, "role": "active_control", "agent": agent})
    else:
        notes.append(f"active control {ac_name} tarball missing/invalid")

    # v2 reference if distinct from the active control.
    if ac_name != "deck_energy_trim_light":
        v2_dir = BASELINES / "v2_kaggle_479_1_deck_energy_trim_light"
        if (v2_dir / "main.py").exists():
            cands.append({"id": "deck_energy_trim_light", "role": "reference_v2",
                          "agent": str(v2_dir / "main.py")})
        else:
            notes.append("v2 deck_energy_trim_light baseline dir missing")

    # combo as live-rejected reference (same artifact as active control here).
    if ac_name == "combo_full_safety_v3_fixed":
        notes.append("combo_full_safety_v3_fixed is the active control this pass; "
                     "its live-rejected role is historical (see meta_pool).")

    # pass-10 tempo candidates, only if they exist and validate.
    for name in PASS10_TEMPO_CANDIDATES:
        tar = CAND_DIR / f"{name}.tar.gz"
        if tar.exists() and _validate_tarball(tar):
            agent = _extract_agent(tar, tmp / name)
            cands.append({"id": name, "role": "pass10_tempo", "agent": agent})
    return cands, notes


def _load_opponents() -> tuple[list[dict], dict, dict]:
    """Return (opponent archetypes with surrogate decks, weights, full pool)."""
    if yaml is None or not META_POOL.exists():
        return [], {}, {}
    pool = yaml.safe_load(META_POOL.read_text(encoding="utf-8")) or {}
    weights = pool.get("evaluation_weights", {}) or {}
    opps = []
    for a in pool.get("archetypes", []):
        if a.get("is_ours"):
            continue
        deck = a.get("surrogate_deck")
        if deck and (REPO / deck).exists():
            opps.append({"key": a["key"], "deck": str(REPO / deck),
                         "confidence": a.get("confidence"),
                         "weight": weights.get(a["key"], 0.0)})
    return opps, weights, pool


def _run_game(agent_a: str, agent_b: str) -> dict:
    from kaggle_environments import make
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(GAME_TIMEOUT_S)
    try:
        env = make("cabt")
        env.run([agent_a, agent_b])
        last = env.steps[-1]
        rewards = [s.get("reward") for s in last]
        statuses = [s.get("status") for s in last]
        metrics = _extract_metrics(env)
        return {"ok": True, "steps": len(env.steps), "rewards": rewards,
                "statuses": statuses, "timeout": False, **metrics}
    except _Timeout:
        return {"ok": False, "timeout": True, "error": "watchdog"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "timeout": False, "error": repr(exc)}
    finally:
        signal.alarm(0)


def _extract_metrics(env) -> dict:
    """Per-game metrics that are robustly derivable from cabt logs.

    Deeper board metrics (Kyogre pressure, no-bench loss, deckout) are NOT
    decoded here because the board state is an opaque encoded blob; they are
    reported as not_measured rather than guessed.
    """
    first_attack = {0: None, 1: None}
    attacks = {0: 0, 1: 0}
    first_evo = {0: None, 1: None}
    invalid_returns = 0
    seen_logs: set[str] = set()
    for idx, st in enumerate(env.steps):
        for seat in st:
            obs = seat.get("observation") if isinstance(seat, dict) else None
            logs = obs.get("logs") if isinstance(obs, dict) else None
            if not logs:
                continue
            for l in logs:
                key = json.dumps(l, sort_keys=True, default=str)
                if key in seen_logs:
                    continue
                seen_logs.add(key)
                if not isinstance(l, dict):
                    continue
                pi = l.get("playerIndex")
                if l.get("type") == ATTACK_LOG_TYPE and l.get("attackId") is not None:
                    if pi in attacks:
                        attacks[pi] += 1
                        if first_attack[pi] is None:
                            first_attack[pi] = idx
                if (l.get("type") == 6 and l.get("cardId") in EVOLUTION_CARD_IDS
                        and pi in first_evo and first_evo[pi] is None):
                    first_evo[pi] = idx
    return {
        "first_attack_step": first_attack,
        "attack_count": attacks,
        "first_evolution_step": first_evo,
        "invalid_returns": invalid_returns,
        "not_measured": ["first_kyogre_pressure", "no_bench_loss",
                         "deckout_low_deck", "stuck_on_snover_board"],
    }


def _outcome_for_seat(game: dict, our_seat: int) -> str | None:
    if not game.get("ok"):
        return None
    rewards = game.get("rewards") or [None, None]
    r = rewards[our_seat] if our_seat < len(rewards) else None
    if r is None:
        return None
    if r > 0:
        return "win"
    if r < 0:
        return "loss"
    return "draw"


def _run_matchup(cand_agent: str, opp_agent: str, budget_left, label: str) -> dict:
    games = []
    # 3 games per seat: candidate@0 then candidate@1.
    for seat, (a, b, our) in enumerate([(cand_agent, opp_agent, 0),
                                        (opp_agent, cand_agent, 1)]):
        for _ in range(GAMES_PER_SEAT):
            if budget_left() <= 0:
                games.append({"ok": False, "skipped": True,
                              "reason": "global_budget_exhausted",
                              "our_seat": our})
                continue
            g = _run_game(a, b)
            g["our_seat"] = our
            g["outcome"] = _outcome_for_seat(g, our)
            games.append(g)
    wins = sum(1 for g in games if g.get("outcome") == "win")
    losses = sum(1 for g in games if g.get("outcome") == "loss")
    draws = sum(1 for g in games if g.get("outcome") == "draw")
    decisive = wins + losses
    return {
        "label": label,
        "games": games,
        "wins": wins, "losses": losses, "draws": draws,
        "win_rate": round(wins / decisive, 4) if decisive else None,
        "crashes": sum(1 for g in games
                       if not g.get("ok") and not g.get("timeout")
                       and not g.get("skipped")),
        "timeouts": sum(1 for g in games if g.get("timeout")),
        "skipped": sum(1 for g in games if g.get("skipped")),
    }


def run() -> dict:
    start = time.time()

    def budget_left():
        return GLOBAL_BUDGET_S - (time.time() - start)

    rep: dict = {
        "pass": "11b", "generated_at": time.time(),
        "disclaimer": ("Surrogate-based and DIRECTIONAL ONLY. Opponent decks are "
                       "piloted by a generic surrogate policy, not the real "
                       "opponent policy. These results never equal Kaggle results "
                       "and are not sufficient to promote or upload a candidate."),
    }
    rep["cabt_available"] = _cabt_available()
    opponents, weights, pool = _load_opponents()
    rep["opponent_families"] = [o["key"] for o in opponents]
    rep["evaluation_weights"] = weights

    if not rep["cabt_available"]:
        rep["status"] = "blocked"
        rep["reason"] = "cabt_unavailable"
        return rep

    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)
        candidates, notes = _resolve_candidates(tmp)
        rep["candidate_notes"] = notes
        rep["candidates_evaluated"] = [c["id"] for c in candidates]
        ac = next((c for c in candidates if c["role"] == "active_control"), None)

        if len(opponents) < 2:
            # Control regression only; mark external meta eval incomplete.
            rep["status"] = "control_regression_only"
            rep["reason"] = "fewer_than_2_replay_families"
            rep["external_meta_eval"] = "incomplete"
            if ac:
                rep["control_regression"] = _run_matchup(
                    ac["agent"], ac["agent"], budget_left, "active_vs_active")
            return rep

        rep["status"] = "ran"
        rep["external_meta_eval"] = "directional"
        rep["matchups"] = []

        # active control mirror baseline.
        if ac:
            mirror = _run_matchup(ac["agent"], ac["agent"], budget_left,
                                  "active_control_mirror")
            rep["active_control_mirror_win_rate"] = mirror["win_rate"]
            rep["matchups"].append({"candidate": ac["id"],
                                    "opponent": "active_control_mirror",
                                    **mirror})

        # candidate vs each archetype family + vs active control.
        per_candidate: dict = {}
        for c in candidates:
            cand_summary = {"id": c["id"], "role": c["role"],
                            "per_archetype": {}, "vs_active_control": None}
            for opp in opponents:
                with tempfile.TemporaryDirectory() as od:
                    from ptcg_activegraph.sim.surrogate_agents import (
                        materialize_surrogate_agent)
                    opp_agent = str(materialize_surrogate_agent(opp["deck"], od))
                    m = _run_matchup(c["agent"], opp_agent, budget_left,
                                     f"{c['id']}_vs_{opp['key']}")
                cand_summary["per_archetype"][opp["key"]] = {
                    "win_rate": m["win_rate"], "wins": m["wins"],
                    "losses": m["losses"], "draws": m["draws"],
                    "weight": opp["weight"], "confidence": opp["confidence"],
                    "crashes": m["crashes"], "timeouts": m["timeouts"],
                    "skipped": m["skipped"],
                }
                rep["matchups"].append({"candidate": c["id"],
                                        "opponent": opp["key"], **m})
            if ac and c["id"] != ac["id"]:
                vac = _run_matchup(c["agent"], ac["agent"], budget_left,
                                   f"{c['id']}_vs_active_control")
                cand_summary["vs_active_control"] = vac["win_rate"]
                rep["matchups"].append({"candidate": c["id"],
                                        "opponent": ac["id"], **vac})
            cand_summary["weighted_meta_score"] = _weighted_meta_score(
                cand_summary["per_archetype"], weights)
            per_candidate[c["id"]] = cand_summary
        rep["per_candidate"] = per_candidate

    rep["elapsed_s"] = round(time.time() - start, 1)
    rep["budget_exhausted"] = budget_left() <= 0
    return rep


def _weighted_meta_score(per_arch: dict, weights: dict) -> float | None:
    total_w = 0.0
    acc = 0.0
    for key, w in weights.items():
        wr = (per_arch.get(key) or {}).get("win_rate")
        if wr is None:
            continue
        acc += float(w) * float(wr)
        total_w += float(w)
    if total_w <= 0:
        return None
    return round(acc / total_w, 4)


def build_ranking(rep: dict) -> dict:
    rows = []
    for cid, c in (rep.get("per_candidate") or {}).items():
        rows.append({
            "candidate": cid, "role": c.get("role"),
            "weighted_meta_score": c.get("weighted_meta_score"),
            "vs_active_control": c.get("vs_active_control"),
        })
    rows.sort(key=lambda r: (r["weighted_meta_score"] is not None,
                             r["weighted_meta_score"] or -1), reverse=True)
    return {
        "pass": "11b",
        "disclaimer": rep.get("disclaimer"),
        "ranking": rows,
        "upload_ready": False,
        "reason_not_upload_ready": (
            "Surrogate eval is directional only; opponent meta is "
            f"{rep.get('external_meta_eval')} and the dominant opponent family is "
            "provisional. No candidate is promotable on this evidence."),
    }


def _md_eval(rep: dict) -> str:
    L = ["# Pass 11B meta-pool evaluation", "",
         f"> {rep.get('disclaimer','')}", "",
         f"- status: **{rep.get('status')}**"
         + (f" (reason: {rep.get('reason')})" if rep.get("reason") else ""),
         f"- cabt available: {rep.get('cabt_available')}",
         f"- external meta eval: {rep.get('external_meta_eval','n/a')}",
         f"- opponent families: {', '.join(rep.get('opponent_families', [])) or 'none'}",
         f"- candidates evaluated: {', '.join(rep.get('candidates_evaluated', [])) or 'none'}",
         f"- active-control mirror win rate: {rep.get('active_control_mirror_win_rate')}",
         ""]
    pc = rep.get("per_candidate") or {}
    if pc:
        L.append("## Per-candidate weighted meta score")
        L.append("| candidate | role | weighted_meta_score | vs active control |")
        L.append("|---|---|---|---|")
        for cid, c in pc.items():
            L.append(f"| {cid} | {c.get('role')} | "
                     f"{c.get('weighted_meta_score')} | "
                     f"{c.get('vs_active_control')} |")
        L.append("")
        L.append("## Per-archetype win rates")
        L.append("| candidate | archetype | confidence | weight | win rate | W-L-D | crash/timeout/skip |")
        L.append("|---|---|---|---|---|---|---|")
        for cid, c in pc.items():
            for key, m in c.get("per_archetype", {}).items():
                L.append(f"| {cid} | {key} | {m.get('confidence')} | "
                         f"{m.get('weight')} | {m.get('win_rate')} | "
                         f"{m.get('wins')}-{m.get('losses')}-{m.get('draws')} | "
                         f"{m.get('crashes')}/{m.get('timeouts')}/{m.get('skipped')} |")
        L.append("")
    L.append("## Metric coverage")
    L.append("- measured from cabt logs: win/loss/draw, first attack step, "
             "attack count, first evolution step (Abomasnow line), "
             "crashes/timeouts/skips.")
    L.append("- NOT measured (encoded board state): first Kyogre pressure, "
             "no-bench-loss rate, deckout/low-deck rate, board-level "
             "stuck-on-snover. Reported as not_measured, not guessed.")
    L.append("")
    if rep.get("candidate_notes"):
        L.append("## Notes")
        for n in rep["candidate_notes"]:
            L.append(f"- {n}")
        L.append("")
    return "\n".join(L)


def _md_rank(rank: dict) -> str:
    L = ["# Pass 11B candidate ranking (directional)", "",
         f"> {rank.get('disclaimer','')}", "",
         "| rank | candidate | role | weighted_meta_score | vs active control |",
         "|---|---|---|---|---|"]
    for i, r in enumerate(rank.get("ranking", []), 1):
        L.append(f"| {i} | {r['candidate']} | {r.get('role')} | "
                 f"{r.get('weighted_meta_score')} | {r.get('vs_active_control')} |")
    L.append("")
    L.append(f"- upload ready: **{rank.get('upload_ready')}**")
    L.append(f"- reason: {rank.get('reason_not_upload_ready')}")
    L.append("")
    return "\n".join(L)


def main() -> int:
    rep = run()
    rank = build_ranking(rep)
    OUT_EVAL_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_EVAL_JSON.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    OUT_EVAL_MD.write_text(_md_eval(rep), encoding="utf-8")
    OUT_RANK_JSON.write_text(json.dumps(rank, indent=2, default=str), encoding="utf-8")
    OUT_RANK_MD.write_text(_md_rank(rank), encoding="utf-8")
    print(f"meta-pool eval: status={rep.get('status')} "
          f"families={len(rep.get('opponent_families', []))} "
          f"candidates={len(rep.get('candidates_evaluated', []))}")
    print(f"  -> {OUT_EVAL_JSON.relative_to(REPO)}")
    print(f"  -> {OUT_RANK_JSON.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
