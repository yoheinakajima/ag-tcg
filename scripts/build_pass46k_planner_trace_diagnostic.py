#!/usr/bin/env python3
"""PASS 46K (Part G) — diamond specialist planner trace diagnostic.

Answers "which planner components co-occur with wins vs losses?" HONESTLY, by replaying the
specialist's OWN visible-only planner functions on REAL recorded game states:

  1. plays a small, seat-balanced set of full cabt games (specialist vs parent, vs the stronger
     generic option_value scorer, and — benchmark-only, for colour — vs one public reference)
     using the proven subprocess-isolated trace worker (hard-killable; native open_spiel C hangs
     cannot be interrupted in-process). Both agents run as plain file paths, exactly as in the
     eval, so the games are genuine;
  2. for every frame where the specialist seat is ACTIVE with a real multi-option select, it
     RE-RUNS the specialist's own deterministic ``make_board_view`` -> ``make_turn_plan`` ->
     ``choose_indices`` on the recorded ``select`` + ``current`` board. The planner is a pure
     function of the visible state (PYTHONHASHSEED=0; no online Search, no randomness), so the
     replay reproduces exactly what the agent did — and we cross-check the replayed pick against
     the frame's recorded action to PROVE the replay is faithful;
  3. records ONLY visible-only plan fields (phase, desired active role, attacker/backup/energy
     targets, attack_now gate, deck-out safety) + the select-window family mix + the chosen
     option families, tied to the GAME-level outcome.

Every field is an observable heuristic LABEL. This is NOT a lethal / KO / missed-KO /
exact-damage / Boss-gust / spread / globally-best-action / card-value claim, and the win/loss
association is descriptive co-occurrence at small n — NEVER a causal or "best move" claim. The
specialist's own ``unsupported_claims()`` honesty boundary is surfaced verbatim. Public-reference
frames are benchmark-only (cross-deck) and carry NO parity claim.

LOCAL / READ-ONLY: no Object Storage, no Kaggle, no events, no tarball writes, no promotion.
Resumable + wall-bounded (re-invoke until ``complete``). Writes
data/experiments/pass46k_planner_trace_diagnostic.{json,md} + a per-game ledger.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data" / "experiments"
PLAN_JSON = EXP / "pass46k_eval_plan.json"
WORK = ROOT / "data" / "tournament" / "benchmark" / "_pass46k_eval_work"
REF_WORK = ROOT / "data" / "tournament" / "benchmark" / "_pass46k_ref_work"
TRACE_WORKER = ROOT / "scripts" / "_pass46c_trace_worker.py"
LEDGER = EXP / "pass46k_planner_trace_games.jsonl"
RAW_DIR = ROOT / "data" / "tournament" / "benchmark" / "_pass46k_trace_raw"

SPEC = "cg_typed_diamond_specialist_planner_v0"
PARENT = "diamond_toolbox_diancie"
OV = "cg_typed_diamond_option_value_v1"
GAME_TIMEOUT = 30        # in-worker alarm; subprocess hard-kill at +15 bounds native hangs
PER_OPP_CAP = 6           # internal opponents: play until win+loss seen, capped
REF_GAMES = 2             # benchmark-only colour games vs one safe reference
MAX_FRAMES_PER_GAME = 4
TARGET_FRAMES = 16


def _main_path(work: Path, cid: str) -> Path:
    return work / cid / "main.py"


def _validate_tar_members(tarball: Path) -> tuple[bool, list]:
    reasons: list[str] = []
    try:
        with tarfile.open(tarball, "r:gz") as t:
            for m in t.getmembers():
                nm = m.name
                if nm.startswith("/") or ".." in Path(nm).parts:
                    reasons.append(f"path-traversal: {nm}")
                if m.issym() or m.islnk():
                    reasons.append(f"link member: {nm}")
                if m.ischr() or m.isblk() or m.isfifo() or m.isdev():
                    reasons.append(f"device member: {nm}")
                if not (m.isfile() or m.isdir()):
                    reasons.append(f"non-regular member: {nm}")
    except Exception as exc:  # noqa: BLE001
        reasons.append(f"open_error: {exc}")
    return (len(reasons) == 0, reasons)


def _safe_extract(tarball: Path, dest: Path) -> None:
    if (dest / "main.py").exists():
        return
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:gz") as t:
        for m in t.getmembers():
            if not m.isfile():
                continue
            if m.name.startswith("/") or ".." in Path(m.name).parts:
                continue
            t.extract(m, dest)


def _resolve_ref() -> tuple[str | None, str | None]:
    """First public reference whose tarball exists AND passes the untrusted-member gate."""
    if not PLAN_JSON.exists():
        return None, None
    plan = json.loads(PLAN_JSON.read_text(encoding="utf-8"))
    for r in plan.get("references_available", []):
        tb = ROOT / r["tarball"]
        if not tb.exists():
            continue
        ok, _ = _validate_tar_members(tb)
        if not ok:
            continue
        rid = r["ref_id"]
        _safe_extract(tb, REF_WORK / rid)
        if (REF_WORK / rid / "main.py").exists():
            return rid, str((REF_WORK / rid / "main.py"))
    return None, None


_PLANNER = None


def _planner():
    """Import the specialist's OWN planner functions once (cg resolves from its dir)."""
    global _PLANNER
    if _PLANNER is not None:
        return _PLANNER
    spec_dir = WORK / SPEC
    if str(spec_dir) not in sys.path:
        sys.path.insert(0, str(spec_dir))
    spec = importlib.util.spec_from_file_location("spec_main_46k", spec_dir / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _PLANNER = mod
    return mod


def _play_game(a_main: str, b_main: str, out_json: Path) -> dict:
    """Subprocess-isolated single game; hard-killable; returns the trace worker record."""
    try:
        subprocess.run([sys.executable, str(TRACE_WORKER), a_main, b_main,
                        str(out_json), str(GAME_TIMEOUT)],
                       capture_output=True, text=True, timeout=GAME_TIMEOUT + 15)
    except subprocess.TimeoutExpired:
        return {"ok": False, "timeout": True, "error": "parent_timeout"}
    if not out_json.exists():
        return {"ok": False, "timeout": False, "error": "no_output"}
    try:
        return json.loads(out_json.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "timeout": False, "error": f"parse:{exc}"}


def _frame_plan(mod, obs: dict) -> dict | None:
    """Replay the specialist's visible-only plan on one recorded observation frame."""
    select = obs.get("select")
    board = obs.get("current")
    if not isinstance(select, dict):
        return None
    opts = select.get("option")
    if not isinstance(opts, list) or len(opts) < 2:
        return None
    try:
        view = mod.make_board_view(select, board)
        plan = mod.make_turn_plan(view)
        ann = getattr(mod, "_annotate_plan", None)
        if callable(ann):
            ann(plan, view)
        chosen = mod.choose_indices(select, board)
        chosen = [i for i in chosen if isinstance(i, int) and 0 <= i < len(opts)]
        chosen_families = sorted({mod.family_for_option(opts[i]) for i in chosen})
        sel_ctx = mod._select_ctx(select)
        # Full agent path (choose_indices + _validate + legal fallback) on the EXACT recorded
        # observation; this is what was actually submitted in the live game and is the basis
        # for the faithfulness cross-check below.
        agent_action = mod.agent(obs)
        if not isinstance(agent_action, list):
            agent_action = []
    except Exception as exc:  # noqa: BLE001
        return {"replay_error": repr(exc)}
    return {
        "turn": view.get("turn"), "acting_seat": view.get("acting_seat"),
        "phase": plan.get("phase"), "neutral_plan": plan.get("neutral"),
        "desired_active_role": plan.get("desired_active_role"),
        "attacker_target": plan.get("attacker_target"),
        "backup_target": plan.get("backup_target"),
        "energy_target": plan.get("energy_target"),
        "attack_now": plan.get("attack_now"),
        "retreat_switch_goal": plan.get("retreat_switch_goal"),
        "draw_deckout_safety": plan.get("draw_deckout_safety"),
        "plan_fallback_reason": plan.get("fallback_reason"),
        "my_active_id": view.get("my_active_id"),
        "my_active_role": view.get("my_active_role"),
        "my_active_energy_count": view.get("my_active_energy_count"),
        "my_bench_ids": view.get("my_bench_ids"),
        "opp_active_id": view.get("opp_active_id"),
        "opp_active_is_ex": view.get("opp_active_is_ex"),
        "select_n_options": sel_ctx.get("n_options"),
        "select_families_present": sel_ctx.get("families_present"),
        "chosen_indices": chosen, "chosen_families": chosen_families,
        "agent_action": agent_action,
    }


def _extract_frames(mod, rec: dict, spec_seat: int) -> tuple[list, str, int]:
    """Curated visible plan frames + game outcome from a recorded env.steps trace."""
    steps = rec.get("steps") or []
    rewards = rec.get("rewards") or []
    spec_reward = rewards[spec_seat] if spec_seat < len(rewards) else None
    if spec_reward is None:
        outcome = "unknown"
    elif spec_reward > 0:
        outcome = "win"
    elif spec_reward < 0:
        outcome = "loss"
    else:
        outcome = "draw"

    def _action_at(idx: int):
        if 0 <= idx < len(steps) and spec_seat < len(steps[idx]):
            av = steps[idx][spec_seat].get("action")
            return av if isinstance(av, list) else None
        return None

    frames = []
    for t, fr in enumerate(steps):
        if spec_seat >= len(fr):
            continue
        cell = fr[spec_seat]
        if cell.get("status") != "ACTIVE":
            continue
        obs = cell.get("observation") or {}
        sel = obs.get("select")
        if not isinstance(sel, dict):
            continue
        opts = sel.get("option")
        if not isinstance(opts, list) or len(opts) < 2:
            continue
        fp = _frame_plan(mod, obs)
        if not fp or fp.get("replay_error"):
            continue
        # kaggle_environments stores the action TAKEN in response to obs[t] at steps[t+1].
        # The full agent path is a pure function of the visible obs, so replaying it must
        # reproduce that recorded action — this is the faithfulness proof.
        fp["step"] = t
        recorded_action = _action_at(t + 1)
        fp["recorded_action"] = recorded_action
        fp["replay_matches_recorded_action"] = (
            isinstance(recorded_action, list)
            and sorted(recorded_action) == sorted(fp.get("agent_action") or []))
        frames.append(fp)

    # representative curation: first setup, first attack_now, a develop, and the last.
    if len(frames) > MAX_FRAMES_PER_GAME:
        picks, seen = [], set()
        for key in (lambda f: f["phase"] == "setup",
                    lambda f: bool(f["attack_now"]),
                    lambda f: f["phase"] == "develop",
                    lambda f: f["phase"] == "attack"):
            for f in frames:
                if f["step"] not in seen and key(f):
                    picks.append(f)
                    seen.add(f["step"])
                    break
        for f in (frames[0], frames[-1]):
            if f["step"] not in seen and len(picks) < MAX_FRAMES_PER_GAME:
                picks.append(f)
                seen.add(f["step"])
        frames = sorted(picks, key=lambda f: f["step"])[:MAX_FRAMES_PER_GAME]
    return frames, outcome, (spec_reward if isinstance(spec_reward, (int, float)) else 0)


def _done_game_ids() -> set:
    ids = set()
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ids.add(json.loads(line)["game_id"])
            except Exception:  # noqa: BLE001
                continue
    return ids


def _ledger_records() -> list:
    recs = []
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
    return recs


def _planned_games(ref_id, ref_main) -> list:
    """Deterministic game list: internal opponents (alternating seats, capped) + ref colour."""
    games = []
    for opp, opp_name in ((PARENT, "parent"), (OV, "generic_ov")):
        opp_main = str(_main_path(WORK, opp))
        for k in range(PER_OPP_CAP):
            seat = k % 2
            a = str(_main_path(WORK, SPEC)) if seat == 0 else opp_main
            b = opp_main if seat == 0 else str(_main_path(WORK, SPEC))
            games.append({"game_id": f"{opp_name}#s{seat}#g{k:02d}", "opp_label": opp_name,
                          "spec_seat": seat, "a_main": a, "b_main": b,
                          "benchmark_only": False, "early_stop_group": opp_name})
    if ref_id and ref_main:
        for k in range(REF_GAMES):
            seat = k % 2
            a = str(_main_path(WORK, SPEC)) if seat == 0 else ref_main
            b = ref_main if seat == 0 else str(_main_path(WORK, SPEC))
            games.append({"game_id": f"ref_{ref_id}#s{seat}#g{k:02d}",
                          "opp_label": f"public_ref:{ref_id}", "spec_seat": seat,
                          "a_main": a, "b_main": b, "benchmark_only": True,
                          "early_stop_group": f"ref:{ref_id}"})
    return games


def _group_has_win_and_loss(recs: list, group: str) -> bool:
    outs = {r["outcome"] for r in recs if r.get("early_stop_group") == group}
    return "win" in outs and "loss" in outs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--orch-budget-seconds", type=float, default=95.0)
    ap.add_argument("--max-games-per-tick", type=int, default=2)
    a = ap.parse_args()
    if not (WORK / SPEC / "main.py").exists():
        raise SystemExit("specialist not extracted; run Part D first")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    EXP.mkdir(parents=True, exist_ok=True)

    ref_id, ref_main = _resolve_ref()
    mod = _planner()
    games = _planned_games(ref_id, ref_main)

    t0 = time.time()
    done = _done_game_ids()
    played_this_tick = 0
    per_game_worst = GAME_TIMEOUT + 15 + 5
    for g in games:
        if played_this_tick >= a.max_games_per_tick:
            break
        if time.time() - t0 > a.orch_budget_seconds - per_game_worst:
            break
        if g["game_id"] in done:
            continue
        # early-stop internal opponents once both a win and a loss are captured
        if not g["benchmark_only"]:
            recs = _ledger_records()
            if _group_has_win_and_loss(recs, g["early_stop_group"]):
                continue
        out_json = RAW_DIR / f"{g['game_id']}.json"
        played_this_tick += 1
        rec = _play_game(g["a_main"], g["b_main"], out_json)
        if not rec.get("ok"):
            with LEDGER.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"game_id": g["game_id"], "opp_label": g["opp_label"],
                                     "spec_seat": g["spec_seat"],
                                     "benchmark_only": g["benchmark_only"],
                                     "early_stop_group": g["early_stop_group"],
                                     "outcome": "error", "error": rec.get("error"),
                                     "timeout": rec.get("timeout"), "frames": []}) + "\n")
            try:
                out_json.unlink()
            except Exception:  # noqa: BLE001
                pass
            continue
        frames, outcome, reward = _extract_frames(mod, rec, g["spec_seat"])
        with LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "game_id": g["game_id"], "opp_label": g["opp_label"],
                "spec_seat": g["spec_seat"], "benchmark_only": g["benchmark_only"],
                "early_stop_group": g["early_stop_group"], "outcome": outcome,
                "spec_reward": reward, "n_steps": rec.get("n_steps"),
                "n_decision_frames_captured": len(frames), "frames": frames}) + "\n")
        try:
            out_json.unlink()  # raw env.steps dump no longer needed
        except Exception:  # noqa: BLE001
            pass

    recs = _ledger_records()
    played = [r for r in recs if r["outcome"] not in ("error",)]
    all_frames = [(r, f) for r in played for f in r["frames"]]
    total_frames = len(all_frames)

    # completion: every internal group has win+loss (or hit cap) AND >= 8 frames, ref attempted
    internal_groups = {"parent", "generic_ov"}
    groups_satisfied = True
    for grp in internal_groups:
        grp_recs = [r for r in recs if r.get("early_stop_group") == grp]
        if not (_group_has_win_and_loss(recs, grp) or len(grp_recs) >= PER_OPP_CAP):
            groups_satisfied = False
            break
    ref_groups = {r["early_stop_group"] for r in recs if r["benchmark_only"]}
    ref_attempted = (ref_id is None) or bool(ref_groups)
    complete = bool(groups_satisfied and ref_attempted and total_frames >= 8)

    # descriptive co-occurrence (NOT causal): plan-field rates in win vs loss frames
    def _rates(pred):
        sub = [f for (r, f) in all_frames if pred(r)]
        n = len(sub)
        if n == 0:
            return {"n": 0}
        return {
            "n": n,
            "attack_now_rate": round(sum(1 for f in sub if f.get("attack_now")) / n, 4),
            "neutral_plan_rate": round(sum(1 for f in sub if f.get("neutral_plan")) / n, 4),
            "phase_setup_rate": round(sum(1 for f in sub if f.get("phase") == "setup") / n, 4),
            "phase_develop_rate": round(
                sum(1 for f in sub if f.get("phase") == "develop") / n, 4),
            "phase_attack_rate": round(
                sum(1 for f in sub if f.get("phase") == "attack") / n, 4),
            "main_attacker_active_rate": round(
                sum(1 for f in sub if "main_attacker" in (f.get("my_active_role") or [])) / n, 4),
            "replay_faithful_rate": round(
                sum(1 for f in sub if f.get("replay_matches_recorded_action")) / n, 4),
        }

    # win/loss attribution cohorts are INTERNAL opponents only — benchmark-only public-reference
    # frames are cross-deck and are reported in their own cohort, never mixed into attribution.
    cooccurrence = {
        "win_frames_internal": _rates(
            lambda r: r["outcome"] == "win" and not r.get("benchmark_only")),
        "loss_frames_internal": _rates(
            lambda r: r["outcome"] == "loss" and not r.get("benchmark_only")),
        "vs_parent_frames": _rates(lambda r: r["opp_label"] == "parent"),
        "vs_generic_ov_frames": _rates(lambda r: r["opp_label"] == "generic_ov"),
        "benchmark_ref_frames": _rates(lambda r: bool(r.get("benchmark_only"))),
    }
    faithful_total = sum(1 for (_, f) in all_frames if f.get("replay_matches_recorded_action"))
    replay_faithful_rate = round(faithful_total / total_frames, 4) if total_frames else None

    unsupported = list(getattr(mod, "unsupported_claims", lambda: [])())

    data = {
        "pass": "46K", "part": "G", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "no_promotion": True,
        "subject": SPEC, "method": (
            "Real games (file-path agents, subprocess-isolated, hard-killable) then DETERMINISTIC "
            "replay of the specialist's own visible-only planner on each recorded ACTIVE "
            "multi-option frame; replayed pick cross-checked against the recorded action."),
        "reference_used": ref_id, "reference_benchmark_only": True,
        "n_games_played": len(played), "n_games_error": len(recs) - len(played),
        "n_decision_frames": total_frames,
        "replay_faithful_rate": replay_faithful_rate,
        "outcomes": {o: sum(1 for r in played if r["outcome"] == o)
                     for o in ("win", "loss", "draw", "unknown")},
        "cooccurrence_descriptive": cooccurrence,
        "planner_unsupported_claims": unsupported,
        "games": [{"game_id": r["game_id"], "opp_label": r["opp_label"],
                   "spec_seat": r["spec_seat"], "benchmark_only": r["benchmark_only"],
                   "outcome": r["outcome"], "n_steps": r.get("n_steps"),
                   "frames": r["frames"]} for r in played],
        "caveats": [
            "Every plan field is an observable heuristic LABEL; visible state only "
            "(no hidden hand/deck/prize contents).",
            "NOT a lethal / KO / missed-KO / exact-damage / Boss-gust / spread / "
            "globally-best-action / card-value claim.",
            "Win/loss association is descriptive co-occurrence at small n — NEVER causal "
            "and NEVER a 'best move' claim.",
            "Public-reference frames are benchmark-only (cross-deck) and carry NO parity claim.",
            "Decisive outcomes are LOCAL feasibility signals — NOT a Kaggle / leaderboard / "
            "strength claim.",
        ],
        "complete": complete,
        "all_ok": bool(total_frames >= 8 and (replay_faithful_rate or 0) >= 0.5),
    }
    (EXP / "pass46k_planner_trace_diagnostic.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        "# Pass 46K (Part G) — diamond specialist planner trace diagnostic", "",
        "_LOCAL / READ-ONLY. Visible-only planner fields, REPLAYED deterministically on real "
        "recorded game states (replayed pick cross-checked against the recorded action). Every "
        "field is an observable heuristic LABEL — NOT a lethal / KO / missed-KO / exact-damage / "
        "Boss-gust / spread / globally-best-action / card-value claim. Win/loss links are "
        "descriptive co-occurrence at small n, never causal. Public-reference frames are "
        "benchmark-only (cross-deck), no parity claim._", "",
        f"- games played: {len(played)} (errors {len(recs) - len(played)}) | decision frames: "
        f"{total_frames} | replay-faithful rate: {replay_faithful_rate}",
        f"- outcomes: {data['outcomes']} | reference (benchmark-only): {ref_id}",
        f"- planner's own refused claims: {unsupported}", "",
        "## Descriptive co-occurrence (NOT causal)",
        "_Win/loss cohorts are INTERNAL opponents only; benchmark-only public-reference frames "
        "(cross-deck) are reported separately and excluded from attribution._",
        "| cohort | n | attack_now | neutral_plan | setup | develop | attack | "
        "main_attacker active | replay faithful |",
        "|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]
    for label, key in (("win frames (internal)", "win_frames_internal"),
                       ("loss frames (internal)", "loss_frames_internal"),
                       ("vs parent", "vs_parent_frames"),
                       ("vs generic_ov", "vs_generic_ov_frames"),
                       ("benchmark refs (cross-deck)", "benchmark_ref_frames")):
        c = cooccurrence[key]
        if c.get("n"):
            md.append(f"| {label} | {c['n']} | {c['attack_now_rate']} | "
                      f"{c['neutral_plan_rate']} | {c['phase_setup_rate']} | "
                      f"{c['phase_develop_rate']} | {c['phase_attack_rate']} | "
                      f"{c['main_attacker_active_rate']} | {c['replay_faithful_rate']} |")
        else:
            md.append(f"| {label} | 0 | - | - | - | - | - | - | - |")
    md += ["", "## Sample decision frames (visible plan fields)"]
    shown = 0
    for r in played:
        if shown >= 8:
            break
        if not r["frames"]:
            continue
        md.append(f"### `{r['game_id']}` ({r['opp_label']}, seat {r['spec_seat']}, "
                  f"outcome **{r['outcome']}**)")
        for f in r["frames"]:
            if shown >= TARGET_FRAMES:
                break
            md.append(
                f"- step {f['step']} | phase **{f['phase']}** | active {f['my_active_id']} "
                f"role {f['my_active_role']} energy {f['my_active_energy_count']} | "
                f"attack_now {f['attack_now']} | desired_role {f['desired_active_role']} | "
                f"select n={f['select_n_options']} fams {f['select_families_present']} | "
                f"chose {f['chosen_indices']} fams {f['chosen_families']} | "
                f"replay_faithful {f['replay_matches_recorded_action']}")
            shown += 1
    md += ["", "## Caveats", *[f"- {c}" for c in data["caveats"]], "",
           f"**complete = {complete} | all_ok = {data['all_ok']}**"]
    (EXP / "pass46k_planner_trace_diagnostic.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({"complete": complete, "all_ok": data["all_ok"],
                      "n_games_played": len(played), "n_frames": total_frames,
                      "replay_faithful_rate": replay_faithful_rate,
                      "outcomes": data["outcomes"], "reference_used": ref_id}, indent=2))
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
