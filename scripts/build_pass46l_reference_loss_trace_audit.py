#!/usr/bin/env python3
"""PASS 46L (Part B) — reference-LOSS trace audit for the diamond specialist v0.

WHY: 46K found v0 beats parent / generic_ov / floor INTERNALLY but went ~1/60 pooled vs the 5
public references. Before designing v1 we must SEE — honestly, from visible state only — WHICH
decision families v0 mishandles in reference games. This audit drives the Part-C v1 blueprint.

HOW (same proven mechanism as the 46K planner trace, extended to ALL ready references, BOTH
seats, with richer LOSS-mode diagnostics):
  1. play v0 vs each ready public reference, both seats, a few games each, using the
     subprocess-isolated, hard-killable trace worker (native open_spiel C hangs cannot be
     interrupted in-process), resumable + wall-bounded;
  2. for every frame where v0's seat is ACTIVE with a real multi-option select, RE-RUN v0's OWN
     deterministic visible-only planner (make_board_view -> make_turn_plan -> _annotate_plan ->
     choose_indices) on the recorded select+board, and cross-check the replayed pick against the
     recorded action to PROVE faithfulness (PYTHONHASHSEED=0; pure function of visible state);
  3. record ONLY visible-only LABELS per frame — phase, attack_now gate, desired role,
     attacker/backup/energy targets, my active id/role/energy count, bench size, opp active
     id/is_ex, self+opp hand/deck/prize/bench COUNTS, the select family mix, whether an attack
     option / any productive (non-end) option was present, the chosen contexts, and derived
     loss-mode flags: attack-available-but-not-taken, end-turn-with-productive-alternative, plus
     the chosen search / bench / attach / discard identities. Aggregated into per-area signals.

HONESTY (hard): references are BENCHMARK-ONLY (cross-deck) — never source/parent/candidate,
never a decision gate; nothing here is a parity / Kaggle / strength claim. Every field is an
observable heuristic LABEL. This is NOT a lethal / KO / missed-KO / exact-damage / Boss-gust /
spread / globally-best-action / card-value claim; "attack available but not taken" means only
that an attack option was OFFERED and a non-attack context was chosen while the active had
VISIBLE energy and an attacker role — NOT that attacking would have won or dealt lethal. Win/
loss links are descriptive co-occurrence at small n, never causal.

LOCAL / READ-ONLY: no Object Storage, no Kaggle, no events, no tarball writes, no promotion.
Writes data/experiments/pass46l_reference_loss_trace_audit.{json,md} + a per-game ledger.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tarfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data" / "experiments"
READINESS = EXP / "pass46l_reference_readiness.json"
REF_WORK = ROOT / "data" / "tournament" / "benchmark" / "_pass46l_ref_work"
TRACE_WORKER = ROOT / "scripts" / "_pass46c_trace_worker.py"
LEDGER = EXP / "pass46l_reference_loss_trace_games.jsonl"
RAW_DIR = ROOT / "data" / "tournament" / "benchmark" / "_pass46l_trace_raw"

SUBJECT = "cg_typed_diamond_specialist_planner_v0"
SUBJECT_TARBALL = (ROOT / "data" / "submissions" / "candidates_pass46j"
                   / f"{SUBJECT}.tar.gz")
ALL_REFS = [
    "public_ref_kiyotah_dragapult", "public_ref_kiyotah_iono",
    "public_ref_kiyotah_mega_abomasnow", "public_ref_kiyotah_mega_lucario",
    "public_ref_ryotasueyoshi_alakazam",
]
GAME_TIMEOUT = 30          # in-worker SIGALRM; subprocess hard-kill at +15 bounds native hangs
GAMES_PER_REF = 2          # both seats (0,1); resumable across ticks
MAX_FRAMES_PER_GAME = 30


def _ref_tarball(rid: str) -> Path:
    return ROOT / "data" / "reference_agents" / "raw_outputs" / rid / "submission.tar.gz"


def _validate_tar_members(tarball: Path) -> bool:
    try:
        with tarfile.open(tarball, "r:gz") as t:
            for m in t.getmembers():
                if m.name.startswith("/") or ".." in Path(m.name).parts:
                    return False
                if m.issym() or m.islnk() or m.ischr() or m.isblk() or m.isfifo() or m.isdev():
                    return False
                if not (m.isfile() or m.isdir()):
                    return False
    except Exception:  # noqa: BLE001
        return False
    return True


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


def _ensure_extracted() -> tuple[Path, list[str]]:
    """Subject + ready references extracted into the benchmark work dir (idempotent)."""
    subj_dir = REF_WORK / SUBJECT
    if SUBJECT_TARBALL.exists() and _validate_tar_members(SUBJECT_TARBALL):
        _safe_extract(SUBJECT_TARBALL, subj_dir)
    ready: list[str] = []
    if READINESS.exists():
        try:
            ready = list(json.loads(READINESS.read_text(encoding="utf-8")).get(
                "ready_opponents") or [])
        except Exception:  # noqa: BLE001
            ready = []
    if not ready:
        ready = list(ALL_REFS)
    usable: list[str] = []
    for rid in ready:
        tb = _ref_tarball(rid)
        if tb.exists() and _validate_tar_members(tb):
            _safe_extract(tb, REF_WORK / rid)
            if (REF_WORK / rid / "main.py").exists():
                usable.append(rid)
    return subj_dir, usable


_PLANNER = None


def _planner(subj_dir: Path):
    global _PLANNER
    if _PLANNER is not None:
        return _PLANNER
    if str(subj_dir) not in sys.path:
        sys.path.insert(0, str(subj_dir))
    spec = importlib.util.spec_from_file_location("subj_main_46l", subj_dir / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _PLANNER = mod
    return mod


def _play_game(a_main: str, b_main: str, out_json: Path) -> dict:
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


def _energy_of(mod, poke) -> int:
    try:
        return int(mod._poke_energy_count(poke))
    except Exception:  # noqa: BLE001
        return 0


def _frame_diag(mod, obs: dict, spec_seat: int) -> dict | None:
    """Replay v0's visible-only planner on one recorded ACTIVE multi-option frame."""
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
        # per-option family + specialist context (annotated plan needed for setup distinction)
        fams = [mod.family_for_option(o) for o in opts]
        ctxs = [mod._context_of(o, select, board, plan, None) for o in opts]
        chosen_fams = sorted({fams[i] for i in chosen})
        chosen_ctxs = sorted({ctxs[i] for i in chosen})
        agent_action = mod.agent(obs)
        if not isinstance(agent_action, list):
            agent_action = []
    except Exception as exc:  # noqa: BLE001
        return {"replay_error": repr(exc)}

    sc = view.get("self_counts") or {}
    oc = view.get("opp_counts") or {}
    active_energy = view.get("my_active_energy_count") or 0
    my_roles = view.get("my_active_role") or []
    is_attacker_active = ("main_attacker" in my_roles) or ("backup_attacker" in my_roles)

    attack_present = "attack" in ctxs
    productive_present = any(c != "end_turn" for c in ctxs)
    chose_attack = "attack" in chosen_ctxs
    chose_end_turn = "end_turn" in chosen_ctxs
    # honest loss-mode flags (visible-only; NOT lethal/KO/best-action claims):
    attack_available_not_taken = bool(
        attack_present and not chose_attack and is_attacker_active and active_energy >= 1)
    end_turn_with_alternatives = bool(
        chose_end_turn and any(c != "end_turn" for i, c in enumerate(ctxs)
                               if i not in chosen))

    # chosen identities per family of interest (for search/bench/attach/discard signals)
    chosen_search_roles, chosen_bench_roles, chosen_discard_roles = [], [], []
    chosen_attach = None
    for i in chosen:
        c = ctxs[i]
        o = opts[i]
        if c == "search_to_hand":
            cid = mod.resolve_play_card(o, select, board)
            chosen_search_roles.append(sorted(mod._roles(cid, None)) or ["unknown"])
        elif c in ("setup_bench", "play_in_play", "choose_active"):
            cid = mod.resolve_play_card(o, select, board)
            chosen_bench_roles.append(sorted(mod._roles(cid, None)) or ["unknown"])
        elif c == "discard":
            cid = mod.resolve_play_card(o, select, board)
            chosen_discard_roles.append(sorted(mod._roles(cid, None)) or ["unknown"])
        elif c == "attach_energy":
            tpoke, tarea = mod._target_poke(o, board)
            tcid = mod._card_id(tpoke) if tpoke is not None else None
            chosen_attach = {
                "area": tarea, "target_id": tcid,
                "target_existing_energy": _energy_of(mod, tpoke),
                "is_plan_energy_target": (tcid is not None
                                          and tcid == plan.get("energy_target"))}

    return {
        "turn": view.get("turn"), "phase": plan.get("phase"),
        "attack_now": plan.get("attack_now"), "neutral_plan": plan.get("neutral"),
        "desired_active_role": plan.get("desired_active_role"),
        "attacker_target": plan.get("attacker_target"),
        "backup_target": plan.get("backup_target"),
        "energy_target": plan.get("energy_target"),
        "retreat_switch_goal": plan.get("retreat_switch_goal"),
        "my_active_id": view.get("my_active_id"), "my_active_role": my_roles,
        "my_active_energy_count": active_energy,
        "my_bench_count": len(view.get("my_bench_ids") or []),
        "is_attacker_active": is_attacker_active,
        "opp_active_id": view.get("opp_active_id"),
        "opp_active_is_ex": view.get("opp_active_is_ex"),
        "self_hand": sc.get("hand_count"), "self_deck": sc.get("deck_count"),
        "self_prize": sc.get("prize_remaining"), "self_bench": sc.get("bench_count"),
        "opp_hand": oc.get("hand_count"), "opp_deck": oc.get("deck_count"),
        "opp_prize": oc.get("prize_remaining"), "opp_bench": oc.get("bench_count"),
        "n_options": len(opts), "families_present": sorted(set(fams)),
        "contexts_present": sorted(set(ctxs)),
        "attack_option_present": attack_present,
        "productive_option_present": productive_present,
        "chosen_contexts": chosen_ctxs, "chosen_families": chosen_fams,
        "chose_attack": chose_attack, "chose_end_turn": chose_end_turn,
        "attack_available_not_taken": attack_available_not_taken,
        "end_turn_with_alternatives": end_turn_with_alternatives,
        "chosen_search_roles": chosen_search_roles,
        "chosen_bench_roles": chosen_bench_roles,
        "chosen_discard_roles": chosen_discard_roles,
        "chosen_attach": chosen_attach,
        "agent_action": agent_action,
    }


def _extract_frames(mod, rec: dict, spec_seat: int) -> tuple[list, str, int]:
    steps = rec.get("steps") or []
    rewards = rec.get("rewards") or []
    spec_reward = rewards[spec_seat] if spec_seat < len(rewards) else None
    if not isinstance(spec_reward, (int, float)):
        outcome = "unknown"
        spec_reward = 0
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
        o = sel.get("option")
        if not isinstance(o, list) or len(o) < 2:
            continue
        fp = _frame_diag(mod, obs, spec_seat)
        if not fp or fp.get("replay_error"):
            continue
        fp["step"] = t
        recorded = _action_at(t + 1)
        fp["recorded_action"] = recorded
        fp["replay_matches_recorded_action"] = (
            isinstance(recorded, list)
            and sorted(recorded) == sorted(fp.get("agent_action") or []))
        frames.append(fp)
        if len(frames) >= MAX_FRAMES_PER_GAME:
            break
    return frames, outcome, int(spec_reward)


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


def _planned_games(subj_dir: Path, refs: list[str]) -> list:
    subj_main = str(subj_dir / "main.py")
    games = []
    for rid in refs:
        ref_main = str(REF_WORK / rid / "main.py")
        for k in range(GAMES_PER_REF):
            seat = k % 2
            a = subj_main if seat == 0 else ref_main
            b = ref_main if seat == 0 else subj_main
            games.append({"game_id": f"ref_{rid}#s{seat}#g{k:02d}", "ref_id": rid,
                          "spec_seat": seat, "a_main": a, "b_main": b})
    return games


def _agg(frames: list) -> dict:
    """Per-area descriptive signal aggregation over a frame cohort (NOT causal)."""
    n = len(frames)
    if n == 0:
        return {"n": 0}
    phase = Counter(f.get("phase") for f in frames)
    # area 1: attack-now / end-turn / productive gating
    atk_avail = [f for f in frames if f.get("attack_option_present")
                 and f.get("is_attacker_active") and (f.get("my_active_energy_count") or 0) >= 1]
    atk_not_taken = sum(1 for f in atk_avail if f.get("attack_available_not_taken"))
    end_alt = sum(1 for f in frames if f.get("end_turn_with_alternatives"))
    # area 3/4/6: chosen role histograms
    search_roles, bench_roles, discard_roles = Counter(), Counter(), Counter()
    for f in frames:
        for rl in f.get("chosen_search_roles") or []:
            search_roles["+".join(rl)] += 1
        for rl in f.get("chosen_bench_roles") or []:
            bench_roles["+".join(rl)] += 1
        for rl in f.get("chosen_discard_roles") or []:
            discard_roles["+".join(rl)] += 1
    # area 5: attach targeting
    attach = [f.get("chosen_attach") for f in frames if f.get("chosen_attach")]
    attach_to_target = sum(1 for a in attach if a.get("is_plan_energy_target"))
    attach_to_energized_nontarget = sum(
        1 for a in attach if not a.get("is_plan_energy_target")
        and (a.get("target_existing_energy") or 0) >= 1)
    return {
        "n": n,
        "phase_mix": dict(phase),
        "frames_attack_available_with_energy": len(atk_avail),
        "attack_available_not_taken": atk_not_taken,
        "attack_available_not_taken_rate": (round(atk_not_taken / len(atk_avail), 4)
                                            if atk_avail else None),
        "end_turn_with_alternatives": end_alt,
        "chose_attack_frames": sum(1 for f in frames if f.get("chose_attack")),
        "search_role_hist": dict(search_roles.most_common(12)),
        "bench_role_hist": dict(bench_roles.most_common(12)),
        "discard_role_hist": dict(discard_roles.most_common(12)),
        "attach_choices": len(attach),
        "attach_to_plan_target": attach_to_target,
        "attach_to_energized_nontarget": attach_to_energized_nontarget,
        "replay_faithful_rate": round(
            sum(1 for f in frames if f.get("replay_matches_recorded_action")) / n, 4),
    }


def _first_attack_turns(games: list) -> dict:
    """Per-game first turn v0 chose an attack (None => never attacked in trace)."""
    out = {"games": 0, "never_attacked": 0, "first_attack_turn_values": []}
    for g in games:
        out["games"] += 1
        ft = None
        for f in sorted(g.get("frames") or [], key=lambda x: x.get("step", 0)):
            if f.get("chose_attack") and isinstance(f.get("turn"), int):
                ft = f["turn"]
                break
        if ft is None:
            out["never_attacked"] += 1
        else:
            out["first_attack_turn_values"].append(ft)
    vals = out["first_attack_turn_values"]
    out["first_attack_turn_min"] = min(vals) if vals else None
    out["first_attack_turn_max"] = max(vals) if vals else None
    out["first_attack_turn_mean"] = round(sum(vals) / len(vals), 2) if vals else None
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--orch-budget-seconds", type=float, default=110.0)
    ap.add_argument("--max-games-per-tick", type=int, default=2)
    a = ap.parse_args()
    EXP.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    subj_dir, refs = _ensure_extracted()
    if not (subj_dir / "main.py").exists():
        raise SystemExit("subject v0 not extracted")
    if not refs:
        raise SystemExit("no ready references to trace")
    mod = _planner(subj_dir)
    games = _planned_games(subj_dir, refs)

    done = {r["game_id"] for r in _ledger_records()}
    t0 = time.time()
    played_this_tick = 0
    per_game_worst = GAME_TIMEOUT + 15 + 5
    for g in games:
        if played_this_tick >= a.max_games_per_tick:
            break
        if time.time() - t0 > a.orch_budget_seconds - per_game_worst:
            break
        if g["game_id"] in done:
            continue
        out_json = RAW_DIR / f"{g['game_id']}.json"
        played_this_tick += 1
        rec = _play_game(g["a_main"], g["b_main"], out_json)
        if not rec.get("ok"):
            with LEDGER.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"game_id": g["game_id"], "ref_id": g["ref_id"],
                                     "spec_seat": g["spec_seat"], "outcome": "error",
                                     "error": rec.get("error"),
                                     "timeout": rec.get("timeout"), "frames": []}) + "\n")
            try:
                out_json.unlink()
            except Exception:  # noqa: BLE001
                pass
            continue
        frames, outcome, reward = _extract_frames(mod, rec, g["spec_seat"])
        with LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"game_id": g["game_id"], "ref_id": g["ref_id"],
                                 "spec_seat": g["spec_seat"], "outcome": outcome,
                                 "spec_reward": reward, "n_steps": rec.get("n_steps"),
                                 "n_frames": len(frames), "frames": frames}) + "\n")
        try:
            out_json.unlink()
        except Exception:  # noqa: BLE001
            pass

    recs = _ledger_records()
    played = [r for r in recs if r.get("outcome") != "error"]
    errors = [r for r in recs if r.get("outcome") == "error"]
    all_frames = [f for r in played for f in (r.get("frames") or [])]
    loss_frames = [f for r in played if r.get("outcome") == "loss"
                   for f in (r.get("frames") or [])]
    win_frames = [f for r in played if r.get("outcome") == "win"
                  for f in (r.get("frames") or [])]

    planned_ids = {g["game_id"] for g in games}
    complete = planned_ids.issubset({r["game_id"] for r in recs}) and len(all_frames) >= 8

    outcomes = Counter(r.get("outcome") for r in played)
    per_ref = {}
    for rid in refs:
        rr = [r for r in played if r.get("ref_id") == rid]
        per_ref[rid] = {
            "games": len(rr),
            "outcomes": dict(Counter(r.get("outcome") for r in rr)),
            "frames": sum(len(r.get("frames") or []) for r in rr),
            "seats": sorted({r.get("spec_seat") for r in rr}),
        }

    faithful = (round(sum(1 for f in all_frames if f.get("replay_matches_recorded_action"))
                      / len(all_frames), 4) if all_frames else None)

    # Honest synthesis: which areas show the strongest visible mishandling signal in LOSSES.
    loss_agg = _agg(loss_frames)
    findings = []
    if loss_agg.get("n"):
        r = loss_agg.get("attack_available_not_taken_rate")
        if r is not None and loss_agg.get("frames_attack_available_with_energy", 0) >= 3:
            findings.append(
                f"AREA 1 (attack gating): in {loss_agg['frames_attack_available_with_energy']} "
                f"loss frames an attack was offered with an energized attacker active; v0 chose "
                f"a non-attack context in {loss_agg['attack_available_not_taken']} "
                f"({r:.0%}). [visible-only; NOT a lethal/KO/best-action claim]")
        if loss_agg.get("end_turn_with_alternatives", 0) > 0:
            findings.append(
                f"AREA 1 (productive gating): {loss_agg['end_turn_with_alternatives']} loss "
                f"frames ended the turn while a productive non-end option was present.")
        if loss_agg.get("attach_to_energized_nontarget", 0) > 0:
            findings.append(
                f"AREA 5 (attach): {loss_agg['attach_to_energized_nontarget']} loss-frame "
                f"attaches went to an already-energized non-plan-target poke.")
        if loss_agg.get("search_role_hist"):
            findings.append(f"AREA 3 (search): chosen-search role mix in losses "
                            f"= {loss_agg['search_role_hist']}.")
        if loss_agg.get("bench_role_hist"):
            findings.append(f"AREA 4 (bench): chosen-bench role mix in losses "
                            f"= {loss_agg['bench_role_hist']}.")
        if loss_agg.get("discard_role_hist"):
            findings.append(f"AREA 6 (discard): chosen-discard role mix in losses "
                            f"= {loss_agg['discard_role_hist']}.")

    data = {
        "pass": "46L", "part": "B", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "no_promotion": True,
        "subject": SUBJECT, "references_traced": refs, "reference_benchmark_only": True,
        "method": (
            "Real games (file-path agents, subprocess-isolated, hard-killable) vs each ready "
            "public reference both seats, then DETERMINISTIC replay of v0's own visible-only "
            "planner on each recorded ACTIVE multi-option frame; replayed pick cross-checked "
            "against the recorded action."),
        "games_planned": len(games), "games_played": len(played),
        "games_error": len(errors),
        "outcomes": dict(outcomes),
        "n_decision_frames": len(all_frames), "n_loss_frames": len(loss_frames),
        "n_win_frames": len(win_frames),
        "replay_faithful_rate": faithful,
        "per_reference": per_ref,
        "first_attack_turn": _first_attack_turns(played),
        "signals_all_frames": _agg(all_frames),
        "signals_loss_frames": loss_agg,
        "signals_win_frames": _agg(win_frames),
        "findings_for_v1_blueprint": findings,
        "caveats": [
            "References are BENCHMARK-ONLY (cross-deck): never source/parent/candidate, never a "
            "decision gate; nothing here is a parity / Kaggle / strength claim.",
            "Every field is an observable heuristic LABEL from VISIBLE state only (no hidden "
            "hand/deck/prize contents).",
            "NOT a lethal / KO / missed-KO / exact-damage / Boss-gust / spread / "
            "globally-best-action / card-value claim.",
            "'attack available but not taken' = an attack option was OFFERED and a non-attack "
            "context was chosen while the active had VISIBLE energy and an attacker role; it "
            "does NOT assert attacking would have won or dealt lethal.",
            "Win/loss links are descriptive co-occurrence at small n, never causal.",
        ],
        "complete": complete,
        "all_ok": bool(len(all_frames) >= 8 and (faithful or 0) >= 0.5),
    }
    (EXP / "pass46l_reference_loss_trace_audit.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    la = loss_agg
    md = [
        "# Pass 46L (Part B) — reference-LOSS trace audit (diamond specialist v0)", "",
        "> **Benchmark-only, LOCAL, read-only.** v0 vs each ready public reference both seats; "
        "v0's OWN visible-only planner REPLAYED on every recorded ACTIVE multi-option frame "
        "(replayed pick cross-checked against the recorded action). Every field is a visible "
        "heuristic LABEL — NOT a lethal / KO / missed-KO / exact-damage / Boss-gust / spread / "
        "globally-best-action / card-value claim. References are cross-deck benchmark-only and "
        "NEVER a decision gate. Drives the Part-C v1 blueprint.", "",
        f"- references traced: {refs}",
        f"- games: planned {len(games)}, played {len(played)}, error {len(errors)} | "
        f"outcomes {dict(outcomes)}",
        f"- decision frames: {len(all_frames)} (loss {len(loss_frames)}, win "
        f"{len(win_frames)}) | replay-faithful rate: {faithful}",
        f"- complete: **{complete}**", "",
        "## First-attack-turn (per game; None => never attacked in trace)",
        f"- games {data['first_attack_turn']['games']}, never-attacked "
        f"{data['first_attack_turn']['never_attacked']}, first-attack turn "
        f"min/mean/max = {data['first_attack_turn']['first_attack_turn_min']}/"
        f"{data['first_attack_turn']['first_attack_turn_mean']}/"
        f"{data['first_attack_turn']['first_attack_turn_max']}", "",
        "## Loss-frame signals (descriptive co-occurrence, NOT causal)",
    ]
    if la.get("n"):
        md += [
            f"- loss frames: {la['n']} | phase mix {la.get('phase_mix')}",
            f"- AREA 1 attack-available-with-energy frames: "
            f"{la.get('frames_attack_available_with_energy')}; attack-available-not-taken: "
            f"{la.get('attack_available_not_taken')} "
            f"(rate {la.get('attack_available_not_taken_rate')})",
            f"- AREA 1 end-turn-with-productive-alternative: "
            f"{la.get('end_turn_with_alternatives')} | chose-attack frames: "
            f"{la.get('chose_attack_frames')}",
            f"- AREA 3 search role hist: {la.get('search_role_hist')}",
            f"- AREA 4 bench role hist: {la.get('bench_role_hist')}",
            f"- AREA 5 attach: choices {la.get('attach_choices')}, to-plan-target "
            f"{la.get('attach_to_plan_target')}, to-energized-non-target "
            f"{la.get('attach_to_energized_nontarget')}",
            f"- AREA 6 discard role hist: {la.get('discard_role_hist')}",
        ]
    else:
        md.append("- (no loss frames captured yet — re-run to accumulate)")
    md += ["", "## Per-reference", "| reference | games | seats | frames | outcomes |",
           "|---|:---:|:---:|:---:|---|"]
    for rid in refs:
        p = per_ref[rid]
        md.append(f"| `{rid}` | {p['games']} | {p['seats']} | {p['frames']} | {p['outcomes']} |")
    md += ["", "## Findings feeding the Part-C v1 blueprint"]
    md += [f"- {f}" for f in findings] or ["- (insufficient frames; re-run)"]
    md += ["", "## Honesty caveats"] + [f"- {c}" for c in data["caveats"]]
    (EXP / "pass46l_reference_loss_trace_audit.md").write_text("\n".join(md) + "\n",
                                                               encoding="utf-8")

    print(json.dumps({"complete": complete, "games_played": len(played),
                      "games_planned": len(games), "n_frames": len(all_frames),
                      "n_loss_frames": len(loss_frames), "outcomes": dict(outcomes),
                      "replay_faithful_rate": faithful}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
