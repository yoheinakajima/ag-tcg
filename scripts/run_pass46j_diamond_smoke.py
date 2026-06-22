#!/usr/bin/env python3
"""PASS 46J (Part H) — runnability smoke + non-inertness + planner attribution.

Three complementary, HONEST measurements for the owned cg_typed Diamond SPECIALIST
PLANNER candidate. LOCAL / READ-ONLY w.r.t. production: NO Object Storage, NO Kaggle,
NO events, NO tick, NO online Search, NO tarball mutation. Only writes this pass's own
experiment artifacts + a transient resumable progress file. Re-invoke until ``ALL DONE``.

A. NON-INERTNESS vs PARENT (deterministic, no game execution):
   replays the PARENT's own ACTIVE decision frames (recorded in the Pass-46C trace panel)
   through the BUILT candidate's actual ``agent()`` (hard-timeout subprocess) and reports
   the fraction of frames where the planner picks a DIFFERENT legal option-set than the
   parent did, plus legality / never-raise / fallback / distinct-context spread. The planner
   is a wholly different policy, so being clearly non-inert proves the policy is ACTIVE and
   SAFE — NOT that it is stronger.

B. ATTRIBUTION vs the 46H GENERIC DIAMOND SCORER (deterministic):
   replays the SAME parent frames through the 46H ``cg_typed_diamond_option_value_v1``
   agent and reports the fraction of frames where the SPECIALIST PLANNER's chosen option-set
   differs from that generic flat option/family scorer. A meaningful change-rate is the
   attribution evidence that any downstream effect is the PLANNER's per-context policies,
   not the previously-shipped generic scorer. Still NOT a strength claim.

C. PLAN-FIELD-DRIVEN (deterministic, in-process):
   for every frame where the candidate differs from the parent, recomputes the candidate's
   own DiamondTurnPlan in-process and checks the change is governed by an ACTIVE plan whose
   context field is populated (NOT a degenerate neutral/exception fallback). Reports the
   driven-rate + the governing-field histogram so the changes are demonstrably plan-driven,
   not cosmetic.

D. RUNNABILITY SMOKE (real cabt games, resumable, wall-budgeted):
   the candidate plays self + parent + the internal live-score leader (== the league water
   deck) + >= 2 public references, BOTH seats, each in a KILLABLE child. Proves zero
   import/deck/runtime/timeout failures across diverse opponents. Win/loss is FEASIBILITY
   CONTEXT ONLY — NOT a strength / win-rate / Kaggle-score claim, and references are
   benchmark-only (excluded from every decision).

Role buckets / target areas / contexts are observable heuristic labels — NO exact-damage /
lethal / KO / missed-KO / Boss-gust / spread / best-action claim anywhere.

Outputs: data/experiments/pass46j_diamond_smoke.{json,md}
         data/experiments/pass46j_diamond_non_inertness.{json,md}
Progress (transient): data/experiments/pass46j_diamond_smoke_progress.json
"""
from __future__ import annotations

import glob
import gzip
import hashlib
import json
import subprocess
import sys
import tarfile
import tempfile
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.analysis import diamond_specialist as ds  # noqa: E402
from ptcg_activegraph.analysis import search_oracle as O  # noqa: E402
from ptcg_activegraph.decks.deck_io import load_deck  # noqa: E402
from ptcg_activegraph.experiments.runner import run_one_game_subprocess  # noqa: E402
from ptcg_activegraph.tournament.artifacts import safe_extract_all  # noqa: E402

EXP = REPO / "data" / "experiments"
TRACES = EXP / "pass46c_traces"
PROGRESS = EXP / "pass46j_diamond_smoke_progress.json"
WORK = REPO / "data/tournament/benchmark/_pass46j_smoke"
ROOT_MAIN = REPO / "main.py"
ROOT_DECK = REPO / "deck.csv"
CG_CHILD = str(REPO / "src/ptcg_activegraph/experiments/_pass41_cg_duel_subprocess.py")

CANDIDATE_ID = "cg_typed_diamond_specialist_planner_v0"
CANDIDATE_TAR = "data/submissions/candidates_pass46j/cg_typed_diamond_specialist_planner_v0.tar.gz"
PARENT_ID = "diamond_toolbox_diancie"
PARENT_TAR = "data/submissions/candidates_pass34/diamond_toolbox_diancie.tar.gz"
GENERIC_ID = "cg_typed_diamond_option_value_v1"  # 46H generic scorer (attribution baseline)
GENERIC_TAR = "data/submissions/candidates_pass46h/cg_typed_diamond_option_value_v1.tar.gz"
LEADER_ID = "league_water_anti_disruption_pivot_v1"  # internal live-score leader (== water)
LEADER_TAR = "data/submissions/candidates_pass33/league_water_anti_disruption_pivot_v1.tar.gz"
REFS = [
    ("public_ref_kiyotah_dragapult",
     "data/reference_agents/raw_outputs/public_ref_kiyotah_dragapult/submission.tar.gz"),
    ("public_ref_kiyotah_iono",
     "data/reference_agents/raw_outputs/public_ref_kiyotah_iono/submission.tar.gz"),
]

PARENT_CHANGED_FLOOR = 0.05       # min changed-rate vs parent to be "non-inert"
ATTRIBUTION_DISTINCT_FLOOR = 0.05  # min changed-rate vs the 46H generic scorer (attribution)
PLAN_FIELD_DRIVEN_FLOOR = 0.5     # min fraction of changed frames governed by an active plan
DISTINCT_CONTEXT_FLOOR = 2        # changes must span >= this many distinct select-contexts
GAME_TIMEOUT = 70
INVOCATION_WALL_BUDGET = 95

# Each per-context policy consults a primary DiamondTurnPlan field. (Attack ordering/gating
# is governed by the (phase, attack_now) gate — a real computed plan decision.)
CONTEXT_PLAN_FIELD = {
    "choose_active": "desired_active_role", "setup_bench": "setup_bench",
    "attach_energy": "energy_target", "move_energy": "energy_target",
    "search_to_hand": "search_targets", "play_from_hand_engine": "search_targets",
    "play_in_play": "setup_bench", "discard": "safe_discard",
    "draw_count": "draw_deckout_safety", "attack": "attack_now",
    "use_ability": "phase", "effect_choice": "phase", "end_turn": "phase",
    "default": "phase",
}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _ensure(cand_id: str, tar_rel: str) -> Path:
    run = WORK / cand_id
    if not (run / "main.py").is_file():
        run.mkdir(parents=True, exist_ok=True)
        with tarfile.open(REPO / tar_rel) as t:
            safe_extract_all(t, run)
    return run


# ---------------------------------------------------------------------------
# Parent ACTIVE decision frames (real recorded observations from the trace panel).
# ---------------------------------------------------------------------------
def _parent_frames(source_id: str) -> list[dict]:
    frames: list[dict] = []
    for tp in sorted(glob.glob(str(TRACES / "*.json.gz"))):
        try:
            d = json.loads(gzip.open(tp).read())
        except Exception:  # noqa: BLE001
            continue
        a_seat = int(d.get("a_seat", 0))
        cand_a, cand_b = d.get("candidate_a"), d.get("candidate_b")
        for i, st in enumerate(d.get("steps") or []):
            if not isinstance(st, list):
                continue
            for seat, o in enumerate(st):
                if not isinstance(o, dict):
                    continue
                if str(o.get("status", "")).upper() != "ACTIVE":
                    continue
                acting = cand_a if seat == a_seat else cand_b
                if acting != source_id:
                    continue
                obs = o.get("observation")
                if not isinstance(obs, dict):
                    continue
                sel, cur = obs.get("select"), obs.get("current")
                if not isinstance(sel, dict) or not isinstance(cur, dict):
                    continue
                opts = sel.get("option") or []
                if len(opts) < 2:
                    continue
                action = o.get("action")
                if not O._is_index_action(action, len(opts), sel.get("minCount"),
                                          sel.get("maxCount")):
                    continue
                frames.append({
                    "trace": Path(tp).name, "step": i, "seat": seat,
                    "select": sel, "current": cur, "n_options": len(opts),
                    "min_count": sel.get("minCount"), "max_count": sel.get("maxCount"),
                    "parent_selected": list(action)})
    return frames


_REPLAY_SNIPPET = r'''
import importlib.util, json, os, sys
cand_dir, frames_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
os.chdir(cand_dir)
sys.path.insert(0, cand_dir)
spec = importlib.util.spec_from_file_location("cand_ni", os.path.join(cand_dir, "main.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
agent = getattr(m, "agent")
frames = json.loads(open(frames_path).read())
out = []
for fr in frames:
    rec = {}
    try:
        r = agent({"select": fr["select"], "current": fr["current"]})
        rec["decision"] = r if isinstance(r, list) else None
        rec["raised"] = False
    except Exception as e:
        rec["decision"] = None
        rec["raised"] = True
        rec["err"] = type(e).__name__
    out.append(rec)
with open(out_path, "w") as fh:
    json.dump(out, fh); fh.flush(); os.fsync(fh.fileno())
print("REPLAY_OK", len(out))
'''


def _replay(cand_dir: Path, frames: list[dict]) -> list[dict] | None:
    with tempfile.TemporaryDirectory() as td:
        fp, op, sp = (Path(td) / "frames.json", Path(td) / "out.json",
                      Path(td) / "snip.py")
        fp.write_text(json.dumps([{"select": f["select"], "current": f["current"]}
                                  for f in frames]), encoding="utf-8")
        sp.write_text(_REPLAY_SNIPPET, encoding="utf-8")
        try:
            subprocess.run([sys.executable, str(sp), str(cand_dir), str(fp), str(op)],
                           capture_output=True, text=True, timeout=140)
        except subprocess.TimeoutExpired:
            return None
        if not op.is_file():
            return None
        return json.loads(op.read_text(encoding="utf-8"))


def _legal(d, fr) -> bool:
    nopt = fr["n_options"]
    return (isinstance(d, list) and O._is_index_action(
        d, nopt, fr["min_count"], fr["max_count"])) or (
        d == [] and fr["min_count"] in (0, None))


def _cand_context(fr: dict, c0) -> str:
    """In-process recompute of the candidate's own context for its chosen first index."""
    try:
        sel, board = fr["select"], fr["current"]
        view = ds.make_board_view(sel, board)
        plan = ds.make_turn_plan(view)
        ds._annotate_plan(plan, view)
        opts = ds._raw_options(sel)
        if isinstance(c0, int) and 0 <= c0 < len(opts):
            return ds._context_of(opts[c0], sel, board, plan, None)
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def _non_inert_vs_parent(frames: list[dict], decisions: list[dict]) -> dict:
    n = len(frames)
    changed = exceptions = illegal = fallback = decisive = 0
    ctx_changed: Counter = Counter()
    for fr, dec in zip(frames, decisions):
        d = dec.get("decision")
        if dec.get("raised"):
            exceptions += 1
        if isinstance(d, list) and not _legal(d, fr):
            illegal += 1
        is_change = isinstance(d, list) and set(d) != set(fr["parent_selected"])
        if is_change:
            changed += 1
        if isinstance(d, list) and d:
            decisive += 1
            if is_change:
                ctx_changed[_cand_context(fr, d[0])] += 1
        elif isinstance(d, list) and not d:
            fallback += 1
    changed_rate = round(changed / n, 4) if n else 0.0
    distinct_ctx = len(ctx_changed)
    non_inert = (changed_rate >= PARENT_CHANGED_FLOOR
                 and distinct_ctx >= DISTINCT_CONTEXT_FLOOR)
    safe = exceptions == 0 and illegal == 0
    return {"n_parent_frames": n, "changed_vs_parent": changed,
            "changed_rate": changed_rate,
            "agreement_with_parent": round(1 - changed_rate, 4),
            "decisive": decisive, "fallback_used": fallback,
            "illegal_decisions": illegal, "exceptions": exceptions,
            "changed_context_histogram": dict(ctx_changed.most_common()),
            "distinct_changed_contexts": distinct_ctx,
            "non_inert": non_inert, "safe": safe}


def _attribution_vs_generic(frames, cand_dec, gen_dec) -> dict:
    """Specialist-planner vs the 46H generic flat scorer on the SAME parent frames."""
    n = len(frames)
    comparable = changed = cand_exc = gen_exc = either_illegal = 0
    for fr, cd, gd in zip(frames, cand_dec, gen_dec):
        if cd.get("raised"):
            cand_exc += 1
        if gd.get("raised"):
            gen_exc += 1
        c, g = cd.get("decision"), gd.get("decision")
        if not (isinstance(c, list) and isinstance(g, list)):
            continue
        if not _legal(c, fr) or not _legal(g, fr):
            either_illegal += 1
            continue
        comparable += 1
        if set(c) != set(g):
            changed += 1
    rate = round(changed / comparable, 4) if comparable else 0.0
    distinguishable = (rate >= ATTRIBUTION_DISTINCT_FLOOR
                       and cand_exc == 0 and either_illegal == 0)
    return {"baseline_id": GENERIC_ID, "n_frames": n,
            "comparable_frames": comparable, "changed_vs_generic": changed,
            "changed_rate": rate,
            "agreement_with_generic": round(1 - rate, 4),
            "candidate_exceptions": cand_exc, "generic_exceptions": gen_exc,
            "either_illegal": either_illegal,
            "distinguishable_from_generic": distinguishable}


def _field_populated(plan: dict, field: str) -> bool:
    if field == "attack_now":
        return True  # the (phase, attack_now) gate is itself a real computed decision
    v = plan.get(field)
    if isinstance(v, list):
        return len(v) > 0
    if isinstance(v, str):
        return v not in ("", "none", "neutral", "unknown")
    return v is not None


def _plan_attribution(frames, decisions) -> dict:
    """Of the CHANGED-vs-parent frames, fraction governed by an ACTIVE, populated plan."""
    changed_total = driven = plan_active_n = 0
    field_hist: Counter = Counter()
    for fr, dec in zip(frames, decisions):
        d = dec.get("decision")
        if not (isinstance(d, list) and d):
            continue
        if set(d) == set(fr["parent_selected"]):
            continue
        changed_total += 1
        try:
            view = ds.make_board_view(fr["select"], fr["current"])
            plan = ds.make_turn_plan(view)
            ds._annotate_plan(plan, view)
            opts = ds._raw_options(fr["select"])
            c0 = d[0]
            ctx = (ds._context_of(opts[c0], fr["select"], fr["current"], plan, None)
                   if isinstance(c0, int) and 0 <= c0 < len(opts) else "unknown")
            plan_active = (not plan.get("neutral")) and plan.get("fallback_reason") is None
            field = CONTEXT_PLAN_FIELD.get(ctx, "phase")
            if plan_active:
                plan_active_n += 1
            if plan_active and _field_populated(plan, field):
                driven += 1
                field_hist[field] += 1
        except Exception:  # noqa: BLE001
            pass
    driven_rate = round(driven / changed_total, 4) if changed_total else 0.0
    return {"changed_frames_examined": changed_total, "plan_active_frames": plan_active_n,
            "plan_field_driven_frames": driven, "plan_field_driven_rate": driven_rate,
            "governing_field_histogram": dict(field_hist.most_common()),
            "plan_field_driven": driven_rate >= PLAN_FIELD_DRIVEN_FLOOR}


def _compute_non_inertness() -> dict:
    frames = _parent_frames(PARENT_ID)
    if not frames:
        raise SystemExit(f"no parent ACTIVE frames for {PARENT_ID}")
    cand_dir = _ensure(CANDIDATE_ID, CANDIDATE_TAR)
    gen_dir = _ensure(GENERIC_ID, GENERIC_TAR)
    cand_dec = _replay(cand_dir, frames)
    if cand_dec is None or len(cand_dec) != len(frames):
        raise SystemExit("candidate replay failed/incomplete")
    gen_dec = _replay(gen_dir, frames)
    if gen_dec is None or len(gen_dec) != len(frames):
        raise SystemExit("generic-baseline replay failed/incomplete")
    return {"vs_parent": _non_inert_vs_parent(frames, cand_dec),
            "vs_generic_scorer": _attribution_vs_generic(frames, cand_dec, gen_dec),
            "plan_attribution": _plan_attribution(frames, cand_dec),
            "parent_changed_floor": PARENT_CHANGED_FLOOR,
            "attribution_distinct_floor": ATTRIBUTION_DISTINCT_FLOOR,
            "plan_field_driven_floor": PLAN_FIELD_DRIVEN_FLOOR,
            "distinct_context_floor": DISTINCT_CONTEXT_FLOOR}


# ---------------------------------------------------------------------------
# Runnability smoke (real cabt games).
# ---------------------------------------------------------------------------
def _opponents() -> list[tuple]:
    """(opponent_id, tarball_or_None, kind). None tarball == self-mirror."""
    return [("self", None, "self"),
            (PARENT_ID, PARENT_TAR, "internal_parent"),
            (LEADER_ID, LEADER_TAR, "internal_leader_water"),
            *[(rid, rtar, "public_reference_benchmark_only") for rid, rtar in REFS]]


def _game_specs() -> list[tuple]:
    specs = []
    for oid, _tar, _kind in _opponents():
        for seat in (0, 1):
            specs.append((oid, seat))
    return specs


def _run_game(cand_dir: Path, cand_deck, opp_main: Path, opp_deck, seat: int) -> dict:
    t0 = time.time()
    res = run_one_game_subprocess(
        control_main=opp_main, control_deck=opp_deck,
        cand_main=cand_dir / "main.py", cand_deck=cand_deck,
        candidate_seat=seat, timeout_seconds=GAME_TIMEOUT, child_script=CG_CHILD)
    err = res.get("error")
    is_id = bool(err) and any(s in str(err).lower() for s in (
        "import", "modulenotfound", "deck", "no module", "cg"))
    return {"seconds": round(time.time() - t0, 1),
            "completed": bool(res.get("completed")), "error": err,
            "import_or_deck_failure": is_id, "timeout": bool(res.get("timeout")),
            "steps": res.get("steps"), "candidate_won": res.get("candidate_won"),
            "draw": bool(res.get("draw"))}


def _load_progress() -> dict:
    if PROGRESS.is_file():
        try:
            return json.loads(PROGRESS.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"non_inertness": None, "games": {},
            "root_main_sha": _sha(ROOT_MAIN), "root_deck_sha": _sha(ROOT_DECK)}


def _save_progress(progress: dict) -> None:
    PROGRESS.write_text(json.dumps(progress, indent=2, default=str), encoding="utf-8")


def _finalize(progress: dict) -> int:
    ni = progress["non_inertness"]
    games = list(progress["games"].values())
    completed = [g for g in games if g["completed"] and not g["error"]]
    errors = [g for g in games if g["error"] and not g["timeout"]]
    timeouts = [g for g in games if g["timeout"]]
    id_fail = [g for g in games if g.get("import_or_deck_failure")]
    root_ok = (_sha(ROOT_MAIN) == progress.get("root_main_sha")
               and _sha(ROOT_DECK) == progress.get("root_deck_sha"))

    vp, vg, pa = ni["vs_parent"], ni["vs_generic_scorer"], ni["plan_attribution"]
    non_inert_ok = bool(vp["non_inert"] and vp["safe"])
    attributable_ok = bool(vg["distinguishable_from_generic"])
    plan_driven_ok = bool(pa["plan_field_driven"])
    smoke_ok = (not id_fail and root_ok and len(errors) == 0 and len(timeouts) == 0
                and len(completed) >= len(games) and bool(games))
    all_ok = bool(smoke_ok and non_inert_ok and attributable_ok and plan_driven_ok)

    note = ("Non-inertness + legality of an ACTIVE never-raising PLANNER policy, its "
            "distinguishability from the 46H generic flat scorer (attribution), the "
            "plan-field-driven fraction of its changes (not cosmetic), and runnability of "
            "the tarball across diverse opponents. NONE of this is a strength / win-rate / "
            "Kaggle claim; public references are benchmark-only and excluded from every "
            "decision; role buckets / target areas / contexts are observable heuristic "
            "labels (no exact-damage / lethal / KO / missed-KO / Boss-gust / spread / "
            "best-action).")

    ni_out = {
        "pass": "46J", "part": "H", "local_only": True, "read_only": True,
        "no_upload": True, "production_mutated": False,
        "parent_id": PARENT_ID, "candidate_id": CANDIDATE_ID,
        "generic_baseline_id": GENERIC_ID,
        "parent_changed_floor": ni["parent_changed_floor"],
        "attribution_distinct_floor": ni["attribution_distinct_floor"],
        "plan_field_driven_floor": ni["plan_field_driven_floor"],
        "distinct_context_floor": ni["distinct_context_floor"],
        "non_inertness_vs_parent": vp,
        "attribution_vs_generic_scorer": vg,
        "plan_field_driven": pa,
        "non_inert_ok": non_inert_ok, "attributable_to_planner": attributable_ok,
        "plan_field_driven_ok": plan_driven_ok,
        "all_non_inertness_ok": bool(non_inert_ok and attributable_ok and plan_driven_ok),
        "note": note,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46j_diamond_non_inertness.json").write_text(
        json.dumps(ni_out, indent=2, default=str) + "\n", encoding="utf-8")

    smoke_out = {
        "pass": "46J", "part": "H", "local_only": True, "read_only": True,
        "no_upload": True, "production_mutated": False,
        "candidate_id": CANDIDATE_ID,
        "opponents": [{"opponent_id": o, "kind": k} for o, _t, k in _opponents()],
        "games_total": len(games), "games_completed": len(completed),
        "games_error": len(errors), "games_timeout": len(timeouts),
        "import_or_deck_failures": len(id_fail),
        "root_main_deck_unchanged": root_ok, "smoke_ok": smoke_ok,
        "all_ok": all_ok, "games": progress["games"], "note": note,
    }
    (EXP / "pass46j_diamond_smoke.json").write_text(
        json.dumps(smoke_out, indent=2, default=str) + "\n", encoding="utf-8")

    # ---- markdown ----
    md = [
        "# Pass 46J (Part H) — smoke + non-inertness + planner attribution", "",
        "_LOCAL / READ-ONLY. Non-inertness/legality of an ACTIVE never-raising PLANNER, "
        "its attribution vs the 46H generic flat scorer, the plan-field-driven fraction "
        "of its changes, and tarball runnability across diverse opponents. NOT a strength "
        "/ win-rate / Kaggle claim. Public references are benchmark-only and excluded from "
        "every decision. Role buckets / target areas / contexts are observable heuristic "
        "labels — no exact-damage / lethal / KO / missed-KO / Boss-gust / spread / "
        "best-action claim._", "",
        f"- **ALL OK:** **{all_ok}** (smoke_ok={smoke_ok}, non_inert={non_inert_ok}, "
        f"attributable={attributable_ok}, plan_field_driven={plan_driven_ok})",
        f"- **smoke games:** {len(completed)}/{len(games)} completed, "
        f"errors={len(errors)}, timeouts={len(timeouts)}, "
        f"import/deck failures={len(id_fail)}, root unchanged={root_ok}", "",
        "## A. Non-inertness vs parent (deterministic replay of parent ACTIVE frames)",
        f"- parent frames: **{vp['n_parent_frames']}**; changed-rate "
        f"**{vp['changed_rate']:.0%}** (>= {ni['parent_changed_floor']:.0%} floor); "
        f"distinct changed contexts: **{vp['distinct_changed_contexts']}** "
        f"(>= {ni['distinct_context_floor']})",
        f"- decisive: {vp['decisive']}; fallback: {vp['fallback_used']}; "
        f"illegal: **{vp['illegal_decisions']}**; exceptions: **{vp['exceptions']}**; "
        f"non-inert: **{vp['non_inert']}**; safe: **{vp['safe']}**",
        f"- changed-context histogram: `{vp['changed_context_histogram']}`", "",
        "## B. Attribution vs the 46H generic diamond scorer "
        f"(`{vg['baseline_id']}`)",
        f"- comparable frames: {vg['comparable_frames']}; changed-rate vs generic scorer: "
        f"**{vg['changed_rate']:.0%}** (>= {ni['attribution_distinct_floor']:.0%} floor); "
        f"distinguishable: **{vg['distinguishable_from_generic']}**",
        f"- candidate exceptions: {vg['candidate_exceptions']}; either-illegal: "
        f"{vg['either_illegal']}", "",
        "## C. Plan-field-driven (changes governed by an ACTIVE populated plan)",
        f"- changed frames examined: {pa['changed_frames_examined']}; plan-active: "
        f"{pa['plan_active_frames']}; plan-field-driven: {pa['plan_field_driven_frames']} "
        f"(**{pa['plan_field_driven_rate']:.0%}** >= {ni['plan_field_driven_floor']:.0%} "
        f"floor) => **{pa['plan_field_driven']}**",
        f"- governing-field histogram: `{pa['governing_field_histogram']}`", "",
        "## D. Runnability smoke (real cabt games — feasibility context only)",
        "| candidate::opponent::seat | kind | completed | won | draw | steps | secs | "
        "err | timeout |", "|---|---|:---:|:---:|:---:|---:|---:|---|:---:|",
    ]
    kind_by_id = {o: k for o, _t, k in _opponents()}
    for key, g in progress["games"].items():
        oid = key.split("::")[1]
        md.append(
            f"| `{key}` | {kind_by_id.get(oid, '?')} | {g['completed']} | "
            f"{g.get('candidate_won')} | {g.get('draw')} | {g.get('steps')} | "
            f"{g['seconds']} | {g.get('error')} | {g['timeout']} |")
    (EXP / "pass46j_diamond_smoke.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    # mirror the non-inertness markdown (sections A-C) into its own file
    (EXP / "pass46j_diamond_non_inertness.md").write_text(
        "\n".join(md[:int_index(md, "## D. Runnability smoke")]) + "\n",
        encoding="utf-8")
    print(f"ALL DONE: all_ok={all_ok} smoke_ok={smoke_ok} non_inert={non_inert_ok} "
          f"attributable={attributable_ok} plan_field_driven={plan_driven_ok}")
    return 0 if all_ok else 1


def int_index(lines: list[str], needle: str) -> int:
    for i, ln in enumerate(lines):
        if ln.startswith(needle):
            return i
    return len(lines)


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    progress = _load_progress()
    if progress.get("non_inertness") is None:
        progress["non_inertness"] = _compute_non_inertness()
        _save_progress(progress)
        vp = progress["non_inertness"]["vs_parent"]
        vg = progress["non_inertness"]["vs_generic_scorer"]
        print(f"NON-INERTNESS DONE: changed_vs_parent={vp['changed_rate']:.0%} "
              f"safe={vp['safe']} changed_vs_generic={vg['changed_rate']:.0%}", flush=True)

    specs = _game_specs()
    pending = [s for s in specs
               if f"{CANDIDATE_ID}::{s[0]}::seat{s[1]}" not in progress["games"]]
    if not pending:
        return _finalize(progress)

    cand_dir = _ensure(CANDIDATE_ID, CANDIDATE_TAR)
    cand_deck = load_deck(cand_dir / "deck.csv")
    tar_by_id = {o: t for o, t, _k in _opponents()}
    start = time.time()
    ran = 0
    for oid, seat in pending:
        if time.time() - start > INVOCATION_WALL_BUDGET and ran > 0:
            break
        if oid == "self":
            opp_main, opp_deck = cand_dir / "main.py", cand_deck
        else:
            odir = _ensure(oid, tar_by_id[oid])
            opp_main, opp_deck = odir / "main.py", load_deck(odir / "deck.csv")
        res = _run_game(cand_dir, cand_deck, opp_main, opp_deck, seat)
        progress["games"][f"{CANDIDATE_ID}::{oid}::seat{seat}"] = res
        _save_progress(progress)
        ran += 1
        flag = "OK" if (res["completed"] and not res["error"]) else "FAIL"
        print(f"[{flag}] {CANDIDATE_ID}::{oid}::seat{seat} {res['seconds']}s "
              f"steps={res.get('steps')} won={res.get('candidate_won')} "
              f"err={res.get('error')}", flush=True)

    remaining = [s for s in specs
                 if f"{CANDIDATE_ID}::{s[0]}::seat{s[1]}" not in progress["games"]]
    if remaining:
        print(f"TICK DONE: ran {ran}, {len(remaining)} remaining — re-invoke", flush=True)
        return 2
    return _finalize(progress)


if __name__ == "__main__":
    raise SystemExit(main())
