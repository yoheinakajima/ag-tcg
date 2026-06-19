#!/usr/bin/env python3
"""Pass 18 (Part D) — diagnose why Raging Bolt / Ogerpon went 0-30.

The diagnosis is **evidence-based and effect-free**: it never fabricates card
effects. It instruments the candidate's OWN decision function (the embedded
``core_pilot_agent``) so every choice it makes is recorded with the raw cabt
option metadata it saw — option ``type`` integers, ``attackId``, resolved card
ids and in-play targets, the select ``context``, and a normalized board snapshot.
From those observed facts (only) it answers the Part-D questions:

  * Did Raging Bolt ex (63) ever become the active Pokemon?
  * Did it attach Energy, and onto Raging Bolt? Which energy ids?
  * Did it attack (chose an option of cabt type 13 with an attackId)?
  * Did it bench Teal Mask Ogerpon ex (96)?
  * Did it play Crispin (1198)?
  * Which attackIds were ever even offered to it (Burst Roar / Bellowing Thunder
    are not name-decoded — only the raw attackId integers are reported)?
  * How often did it pass/decline while an attack option was on the table?
  * Which cabt contexts/option types would need wiring to fix it?

If no Pass-17 traces are available it runs a small fresh diagnostic:
Raging Bolt vs Water (2 games/seat) and Raging Bolt self-play (2 games/seat).

LOCAL ONLY. No upload.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import signal
import sys
import tarfile
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import _bootstrap  # noqa: F401

REPO = Path(__file__).resolve().parents[1]
RB_TARBALL = REPO / "data" / "submissions" / "candidates_pass17" / \
    "league_raging_bolt_ogerpon.tar.gz"
WATER_TARBALL = REPO / "data" / "submissions" / "candidates_pass17" / \
    "league_water_core_reference.tar.gz"
OUT_JSON = REPO / "data" / "experiments" / "pass18_raging_bolt_diagnosis.json"
OUT_MD = REPO / "data" / "experiments" / "pass18_raging_bolt_diagnosis.md"

RAGING_BOLT = 63
OGERPON = 96
CRISPIN = 1198
RB_REQUIRED_ENERGY = [4, 6]   # Lightning + Fighting (from playbook/spec)
OGERPON_ENERGY = [1]          # Grass
BASIC_ENERGY_IDS = {1, 2, 3, 4, 5, 6, 7}
ATTACK_OPTION_TYPE = 13
GAME_TIMEOUT_S = int(os.environ.get("RB_DIAG_GAME_TIMEOUT_S", "60"))
GAMES_PER_SEAT = int(os.environ.get("RB_DIAG_GAMES_PER_SEAT", "2"))


class _Timeout(Exception):
    pass


def _alarm(_s, _f):
    raise _Timeout()


def _cabt_available() -> bool:
    diag = REPO / "data" / "experiments" / "cabt_diagnostic.json"
    if not diag.exists():
        try:
            import kaggle_environments  # noqa: F401
            return True
        except Exception:
            return False
    try:
        return bool(json.loads(diag.read_text(encoding="utf-8")).get("cabt_available"))
    except Exception:
        return False


def _extract(tarball: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:gz") as tar:
        tar.extractall(dest)  # noqa: S202 (our own build artifact)
    main = dest / "main.py"
    if not main.exists():
        raise FileNotFoundError(f"no main.py inside {tarball.name}")
    return main


def _import_candidate(main_path: Path, mod_name: str):
    old_cwd = os.getcwd()
    added = str(main_path.parent)
    sys.path.insert(0, added)
    os.chdir(main_path.parent)
    try:
        spec = importlib.util.spec_from_file_location(mod_name, main_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod
    finally:
        os.chdir(old_cwd)
        if added in sys.path:
            sys.path.remove(added)


def _summarize_decision(mod, obs, action) -> dict:
    """Pure read of one decision: what was offered and what was chosen."""
    rec: dict = {"context": None, "select_type": None, "n_options": 0,
                 "chosen": list(action) if isinstance(action, (list, tuple)) else action}
    try:
        sel = mod._get_select(obs)
        if not isinstance(sel, dict):
            return rec
        rec["context"] = sel.get("context")
        rec["select_type"] = sel.get("type")
        options = mod._get_options(sel)
        rec["n_options"] = len(options)
        mn, mx = mod._get_min_max_count(sel, len(options))
        rec["min_count"], rec["max_count"] = mn, mx
        board = mod.build_board(obs)
        active = (board or {}).get("active") or {}
        rec["active_card_id"] = active.get("card_id")
        rec["active_energy"] = active.get("energy")
        rec["bench_ids"] = [c.get("card_id") for c in (board or {}).get("bench") or []]
        rec["hand_size"] = len((board or {}).get("hand") or [])
        rec["deck_count"] = (board or {}).get("deck_count")

        opt_summ = []
        for i, o in enumerate(options):
            if not isinstance(o, dict):
                opt_summ.append({"i": i, "type": None})
                continue
            entry = {
                "i": i,
                "type": o.get("type"),
                "attackId": o.get("attackId"),
                "card_id": mod.resolve_option_card(obs, o),
                "target_id": mod.resolve_option_target(obs, o),
            }
            opt_summ.append(entry)
        rec["options"] = opt_summ
        # Classify the chosen option(s).
        chosen_idx = action if isinstance(action, (list, tuple)) else []
        chosen = [opt_summ[i] for i in chosen_idx if isinstance(i, int) and 0 <= i < len(opt_summ)]
        rec["chosen_options"] = chosen
        rec["attack_offered"] = any(e.get("type") == ATTACK_OPTION_TYPE
                                    and e.get("attackId") is not None for e in opt_summ)
        rec["attack_chosen"] = any(e.get("type") == ATTACK_OPTION_TYPE
                                   and e.get("attackId") is not None for e in chosen)
        rec["attack_ids_offered"] = sorted({e.get("attackId") for e in opt_summ
                                            if e.get("type") == ATTACK_OPTION_TYPE
                                            and e.get("attackId") is not None})
        # Energy attach = a hand basic-energy option that targets an in-play card.
        rec["energy_attach_offered"] = [
            {"energy_id": e.get("card_id"), "target_id": e.get("target_id")}
            for e in opt_summ
            if e.get("card_id") in BASIC_ENERGY_IDS and e.get("target_id") is not None]
        rec["energy_attach_chosen"] = [
            {"energy_id": e.get("card_id"), "target_id": e.get("target_id")}
            for e in chosen
            if e.get("card_id") in BASIC_ENERGY_IDS and e.get("target_id") is not None]
        rec["chosen_card_ids"] = [e.get("card_id") for e in chosen
                                  if e.get("card_id") is not None]
        rec["empty_action"] = len(chosen_idx) == 0
    except Exception as exc:  # never raise into a runtime agent
        rec["summary_error"] = repr(exc)
    return rec


def _make_logged_agent(mod, sink: list):
    fn = mod.core_pilot_agent

    def logged(obs, *_a, **_k):
        action = fn(obs)
        try:
            rec = _summarize_decision(mod, obs, action)
            sink.append(rec)
        except Exception as exc:  # pragma: no cover
            sink.append({"summary_error": repr(exc)})
        return action

    return logged


def _run_game(agents, sink_reset_fns) -> dict:
    from kaggle_environments import make
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(GAME_TIMEOUT_S)
    try:
        env = make("cabt")
        env.run(agents)
        last = env.steps[-1]
        rewards = [s.get("reward") for s in last]
        statuses = [s.get("status") for s in last]
        return {"ok": True, "steps": len(env.steps), "rewards": rewards,
                "statuses": statuses, "timeout": False}
    except _Timeout:
        return {"ok": False, "timeout": True, "error": "watchdog"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "timeout": False, "error": repr(exc)}
    finally:
        signal.alarm(0)


def _aggregate(decisions: list) -> dict:
    """Roll observed decision facts up into the Part-D answer set."""
    ctx_hist = Counter()
    ctx0_type_hist = Counter()
    n = len(decisions)
    rb_active = ogerpon_benched = crispin_played = 0
    attach_any = attach_to_rb = attach_right_to_rb = 0
    attack_offered = attack_chosen = pass_while_attack = 0
    attack_ids_seen: set = set()
    energy_attach_targets = Counter()
    for d in decisions:
        if not isinstance(d, dict):
            continue
        ctx = d.get("context")
        ctx_hist[ctx] += 1
        if d.get("active_card_id") == RAGING_BOLT:
            rb_active += 1
        if OGERPON in (d.get("bench_ids") or []):
            ogerpon_benched += 1
        if CRISPIN in (d.get("chosen_card_ids") or []):
            crispin_played += 1
        for e in d.get("options") or []:
            if ctx == 0 and isinstance(e, dict):
                ctx0_type_hist[e.get("type")] += 1
        for a in d.get("attack_ids_offered") or []:
            attack_ids_seen.add(a)
        if d.get("attack_offered"):
            attack_offered += 1
            if d.get("attack_chosen"):
                attack_chosen += 1
            elif d.get("empty_action") or not d.get("attack_chosen"):
                pass_while_attack += 1
        for ea in d.get("energy_attach_chosen") or []:
            attach_any += 1
            tgt = ea.get("target_id")
            energy_attach_targets[tgt] += 1
            if tgt == RAGING_BOLT:
                attach_to_rb += 1
                if ea.get("energy_id") in RB_REQUIRED_ENERGY:
                    attach_right_to_rb += 1
    return {
        "decisions_recorded": n,
        "context_histogram": {str(k): v for k, v in ctx_hist.most_common()},
        "ctx0_option_type_histogram": {str(k): v for k, v in ctx0_type_hist.most_common()},
        "raging_bolt_became_active": rb_active > 0,
        "raging_bolt_active_decisions": rb_active,
        "ogerpon_benched": ogerpon_benched > 0,
        "crispin_played": crispin_played > 0,
        "energy_attaches_made": attach_any,
        "energy_attaches_to_raging_bolt": attach_to_rb,
        "correct_energy_attaches_to_raging_bolt": attach_right_to_rb,
        "energy_attach_target_histogram": {str(k): v for k, v in energy_attach_targets.most_common()},
        "attack_option_offered_decisions": attack_offered,
        "attacks_chosen": attack_chosen,
        "passed_or_declined_while_attack_offered": pass_while_attack,
        "attack_ids_ever_offered": sorted(attack_ids_seen),
    }


def run() -> dict:
    rep: dict = {
        "pass": "18", "part": "D",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "upload_performed": False,
        "candidate": "league_raging_bolt_ogerpon",
        "method": ("Instruments the candidate's own core_pilot_agent and records "
                   "only observed cabt option metadata. No card effects are "
                   "fabricated; attack names are not decoded (raw attackIds only)."),
        "energy_semantics_note": (
            "Raging Bolt ex (63) required energy taken from playbook/spec as "
            "Lightning(4)+Fighting(6); Ogerpon(96) Grass(1). Energy *color* of an "
            "attach is inferred from the energy card id only."),
    }
    rep["cabt_available"] = _cabt_available()
    rep["pass17_traces_available"] = False  # league stored aggregate results, not per-decision traces
    if not rep["cabt_available"]:
        rep["status"] = "blocked"
        rep["reason"] = "cabt_unavailable"
        return rep

    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)
        rb_main = _extract(RB_TARBALL, tmp / "rb")
        water_main = _extract(WATER_TARBALL, tmp / "water")
        rb_mod = _import_candidate(rb_main, "rb_diag_cand")

        scenarios = []

        # Scenario 1: Raging Bolt vs Water, 2 games/seat (RB instrumented).
        vs_water_decisions: list = []
        vs_water_games = []
        for seat in (0, 1):
            for _ in range(GAMES_PER_SEAT):
                logged = _make_logged_agent(rb_mod, vs_water_decisions)
                agents = [logged, str(water_main)] if seat == 0 else [str(water_main), logged]
                g = _run_game(agents, [])
                g["rb_seat"] = seat
                if g.get("ok"):
                    r = g["rewards"][seat] if seat < len(g["rewards"]) else None
                    g["rb_outcome"] = ("win" if (r or 0) > 0 else
                                       "loss" if (r or 0) < 0 else "draw") if r is not None else None
                vs_water_games.append(g)
        scenarios.append({
            "name": "raging_bolt_vs_water",
            "games_per_seat": GAMES_PER_SEAT,
            "games": vs_water_games,
            "decision_facts": _aggregate(vs_water_decisions),
        })

        # Scenario 2: Raging Bolt self-play, 2 games/seat (both seats instrumented).
        self_decisions: list = []
        self_games = []
        for _ in range(GAMES_PER_SEAT * 2):
            a = _make_logged_agent(rb_mod, self_decisions)
            b = _make_logged_agent(rb_mod, self_decisions)
            g = _run_game([a, b], [])
            self_games.append(g)
        scenarios.append({
            "name": "raging_bolt_self_play",
            "games_per_seat": GAMES_PER_SEAT,
            "games": self_games,
            "decision_facts": _aggregate(self_decisions),
        })

        rep["scenarios"] = scenarios

    # Build the diagnosis verdict from observed facts (vs Water is the signal).
    vw = next(s for s in rep["scenarios"] if s["name"] == "raging_bolt_vs_water")
    f = vw["decision_facts"]
    g_decisive = [g for g in vw["games"] if g.get("ok")]
    wins = sum(1 for g in g_decisive if g.get("rb_outcome") == "win")
    losses = sum(1 for g in g_decisive if g.get("rb_outcome") == "loss")
    findings = {
        "became_active": f["raging_bolt_became_active"],
        "attached_energy": f["energy_attaches_made"] > 0,
        "attached_energy_to_raging_bolt": f["energy_attaches_to_raging_bolt"] > 0,
        "attached_correct_energy_to_raging_bolt": f["correct_energy_attaches_to_raging_bolt"] > 0,
        "attacked": f["attacks_chosen"] > 0,
        "benched_ogerpon": f["ogerpon_benched"],
        "used_crispin": f["crispin_played"],
        "attack_offered_but_passed": f["passed_or_declined_while_attack_offered"],
        "vs_water_record": f"{wins}-{losses}",
    }
    rep["findings"] = findings

    # Verdict logic (only from observed facts).
    energy_problem = (not findings["attached_correct_energy_to_raging_bolt"]) \
        and (f["attack_option_offered_decisions"] == 0 or not findings["attacked"])
    tempo_problem = findings["attack_offered_but_passed"] > 0 and not findings["attacked"]
    rep["core_failure"] = (
        "energy/tempo pilot fit: the attacker is not being brought online with "
        "its required energy, so legal attacks rarely materialize"
        if energy_problem or tempo_problem else
        "deck/structural: attacker comes online but still loses (not an attach/tempo gap)")
    rep["energy_matching"] = (
        "the generic pilot does NOT color-match attachment; required Lightning(4)+"
        "Fighting(6) are not preferentially routed onto Raging Bolt"
        if not findings["attached_correct_energy_to_raging_bolt"] else
        "correct energy reached Raging Bolt at least once")
    rep["attack_first"] = (
        "attack-first is not enforced: attack options were offered but the pilot "
        "passed/declined" if tempo_problem else
        ("attacks were taken when offered" if findings["attacked"] else
         "attack options were essentially never offered (attacker never online)"))
    rep["contexts_needing_wiring"] = {
        "broad_main_ctx_0": ("attach required energy onto Raging Bolt and prefer a "
                             "legal attack — currently delegated to the base policy"),
        "observed_ctx0_option_types": f["ctx0_option_type_histogram"],
        "attack_option_type": ATTACK_OPTION_TYPE,
    }
    rep["loss_attribution"] = (
        "no_attack / attacker_never_online" if not findings["attacked"] else
        "attacks made but still lost (race/structural)")
    rep["rescue_justified"] = bool(energy_problem or tempo_problem)
    rep["rescue_justification"] = (
        "Diagnosis shows a pilot-fit failure (energy routing + attack-first), which "
        "a deck-specific aggro playbook + guarded ctx-0 attach/attack hook can "
        "address. Parts E/F are justified."
        if rep["rescue_justified"] else
        "Observed facts do not isolate an attach/tempo gap; an aggro hook is NOT "
        "justified. Keep Raging Bolt blocked/poor-fit.")
    rep["do_not_fabricate_note"] = (
        "Attack names (Burst Roar / Bellowing Thunder) are NOT decoded; only raw "
        f"attackIds {f['attack_ids_ever_offered']} were observed.")
    rep["status"] = "ran"
    return rep


def render_md(rep: dict) -> str:
    if rep.get("status") != "ran":
        return (f"# Pass 18 — Raging Bolt Diagnosis\n\n"
                f"- status: **{rep.get('status')}** ({rep.get('reason')})\n"
                f"- upload_performed: {rep.get('upload_performed')}\n")
    f = rep["findings"]
    lines = [
        "# Pass 18 — Raging Bolt / Ogerpon Failure Diagnosis",
        "",
        f"- generated: {rep['generated_at']}",
        f"- candidate: `{rep['candidate']}`",
        "- **upload_performed: false** (local only)",
        f"- method: {rep['method']}",
        "",
        "## Observed findings (vs Water, instrumented)",
        "",
        f"- Raging Bolt became active: **{f['became_active']}**",
        f"- attached energy at all: **{f['attached_energy']}**",
        f"- attached energy to Raging Bolt: **{f['attached_energy_to_raging_bolt']}**",
        f"- attached *correct* (L/F) energy to Raging Bolt: **{f['attached_correct_energy_to_raging_bolt']}**",
        f"- attacked: **{f['attacked']}**",
        f"- benched Ogerpon: **{f['benched_ogerpon']}**",
        f"- used Crispin: **{f['used_crispin']}**",
        f"- passed/declined while an attack was offered: **{f['attack_offered_but_passed']}**",
        f"- fresh vs-Water record (decisive): **{f['vs_water_record']}**",
        "",
        "## Verdict",
        "",
        f"- **core failure:** {rep['core_failure']}",
        f"- **energy matching:** {rep['energy_matching']}",
        f"- **attack-first:** {rep['attack_first']}",
        f"- **loss attribution:** {rep['loss_attribution']}",
        f"- **rescue justified (Parts E/F):** {rep['rescue_justified']}",
        f"- {rep['rescue_justification']}",
        "",
        "## Contexts / options needing wiring",
        "",
        f"- broad Main (ctx 0): {rep['contexts_needing_wiring']['broad_main_ctx_0']}",
        f"- attack option type: {rep['contexts_needing_wiring']['attack_option_type']}",
        f"- observed ctx-0 option type histogram: "
        f"{rep['contexts_needing_wiring']['observed_ctx0_option_types']}",
        "",
        f"> {rep['do_not_fabricate_note']}",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-json", default=str(OUT_JSON))
    ap.add_argument("--out-md", default=str(OUT_MD))
    args = ap.parse_args()

    rep = run()
    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    Path(args.out_md).write_text(render_md(rep), encoding="utf-8")
    print(render_md(rep))
    print(f"\nwrote {args.out_json}\nwrote {args.out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
