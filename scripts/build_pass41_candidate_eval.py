#!/usr/bin/env python3
"""Pass 41 (Part H) — bounded, checkpointed evaluation of the OWNED cg_typed candidate.

Three eval lanes, one resumable progress file:

  * parent  — candidate vs its stdlib parent family, 5 games/seat (10 total; >=4/seat)
  * ref     — candidate vs ALL 5 Pass-40 public references, 2 games/seat/ref (20)
  * anchor  — candidate vs {water control, internal leader, dragapult ref}, 2/seat each
              (dragapult games are REUSED from the ref lane, never double-run)

Every game runs in a killable child (``run_one_game_subprocess`` + the dedicated
``_pass41_cg_duel_subprocess`` child seating OUR candidate as subject). RESUMABLE +
wall-budgeted: each finished game is persisted and skipped on re-run; re-invoke until
``ALL DONE``.

Statistics: decisive win-rate with a Wilson 95% interval. We make NO superiority
claim over the parent unless the parent-H2H decisive-WR Wilson interval lies strictly
above 0.5 (and symmetrically NO inferiority claim unless strictly below). Public-ref
results report the delta vs the parent's OWN Part-B record against the same reference.

Benchmark-only: NO upload/submit/promote/mutate; root main.py/deck.csv read-only;
references never enter our pool/queue/lifecycle/rankings.

Outputs:
  data/experiments/pass41_parent_child_eval.{json,md}
  data/experiments/pass41_public_reference_eval.{json,md}
  data/experiments/pass41_anchor_eval.{json,md}
Progress (transient): data/experiments/pass41_candidate_eval_progress.json
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import tarfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
EXP = REPO / "data" / "experiments"
EXTR_OURS = REPO / "data/tournament/benchmark/_our_extracted"
EXTR_REFS = REPO / "data/reference_agents/tarballs/_extracted"
CAND_RUN = REPO / "data/tournament/benchmark/_cg_cand_extracted/cg_typed_mono_lightning_miraidon_policy_v1"
CAND_TAR = REPO / "data/submissions/candidates_pass41/cg_typed_mono_lightning_miraidon_policy_v1.tar.gz"
MATRIX = REPO / "data/tournament/benchmark/projections/pass41_public_benchmark_matrix.json"
PROGRESS = EXP / "pass41_candidate_eval_progress.json"
NOISE_CTRL = EXP / "pass41_h2h_noise_control.json"
ROOT_MAIN = REPO / "main.py"
ROOT_DECK = REPO / "deck.csv"

from ptcg_activegraph.decks.deck_io import load_deck  # noqa: E402
from ptcg_activegraph.experiments.runner import run_one_game_subprocess  # noqa: E402
from ptcg_activegraph.tournament.artifacts import safe_extract_all  # noqa: E402
from ptcg_activegraph.tournament.benchmark import load_opponents  # noqa: E402

CG_CHILD = str(REPO / "src/ptcg_activegraph/experiments/_pass41_cg_duel_subprocess.py")
GAME_TIMEOUT = 100
INVOCATION_WALL_BUDGET = 75
CAND_ID = "cg_typed_mono_lightning_miraidon_policy_v1"
PARENT_ID = "mono_lightning_miraidon_easy"
WATER_CONTROL_ID = "league_water_core_reference"
INTERNAL_LEADER_ID = "diamond_toolbox_diancie"
DRAGAPULT_REF = "public_ref_kiyotah_dragapult"
PARENT_GAMES_PER_SEAT = 5
REF_GAMES_PER_SEAT = 2
ANCHOR_GAMES_PER_SEAT = 2


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _ensure_candidate() -> Path:
    if not (CAND_RUN / "cg" / "libcg.so").is_file() or not (CAND_RUN / "main.py").is_file():
        CAND_RUN.mkdir(parents=True, exist_ok=True)
        with tarfile.open(CAND_TAR) as t:
            safe_extract_all(t, CAND_RUN)
    return CAND_RUN


def _ensure_ref(agent_id: str) -> Path:
    run = EXTR_REFS / agent_id
    if not (run / "cg" / "libcg.so").is_file():
        run.mkdir(parents=True, exist_ok=True)
        with tarfile.open(REPO / "data/reference_agents/tarballs" / f"{agent_id}.tar.gz") as t:
            safe_extract_all(t, run)
    return run


def _wilson(wins: int, n: int, z: float = 1.96) -> list[float]:
    """Wilson score 95% interval for a binomial proportion (decisive games only)."""
    if n == 0:
        return [0.0, 0.0]
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return [round(max(0.0, center - half), 4), round(min(1.0, center + half), 4)]


# --------------------------------------------------------------------------- #
# opponents / game list
# --------------------------------------------------------------------------- #
def _opp(agent_id: str, is_ref: bool) -> dict:
    base = (_ensure_ref(agent_id) if is_ref else (EXTR_OURS / agent_id))
    return {"id": agent_id, "main": base / "main.py",
            "deck": load_deck(base / "deck.csv")}


def _build_plan() -> tuple[Path, list[int], dict]:
    cand_dir = _ensure_candidate()
    cand_main = cand_dir / "main.py"
    cand_deck = load_deck(cand_dir / "deck.csv")
    ref_ids = [o.agent_id for o in load_opponents(include_optional=True)]

    plan: list[dict] = []
    # parent lane
    p = _opp(PARENT_ID, is_ref=False)
    for seat in (0, 1):
        for g in range(PARENT_GAMES_PER_SEAT):
            plan.append({"lane": "parent", "opp": PARENT_ID, "main": p["main"],
                         "deck": p["deck"], "seat": seat, "g": g})
    # ref lane (all 5)
    for rid in ref_ids:
        o = _opp(rid, is_ref=True)
        for seat in (0, 1):
            for g in range(REF_GAMES_PER_SEAT):
                plan.append({"lane": "ref", "opp": rid, "main": o["main"],
                             "deck": o["deck"], "seat": seat, "g": g})
    # anchor lane: water control + internal leader (dragapult REUSED from ref lane)
    for aid in (WATER_CONTROL_ID, INTERNAL_LEADER_ID):
        o = _opp(aid, is_ref=False)
        for seat in (0, 1):
            for g in range(ANCHOR_GAMES_PER_SEAT):
                plan.append({"lane": "anchor", "opp": aid, "main": o["main"],
                             "deck": o["deck"], "seat": seat, "g": g})
    return cand_main, cand_deck, {"plan": plan, "ref_ids": ref_ids}


def _key(e: dict) -> str:
    return f"{e['lane']}::{e['opp']}::seat{e['seat']}::g{e['g']}"


def _run_game(cand_main: Path, cand_deck: list[int], e: dict) -> dict:
    t0 = time.time()
    res = run_one_game_subprocess(
        control_main=e["main"], control_deck=e["deck"],
        cand_main=cand_main, cand_deck=cand_deck,
        candidate_seat=e["seat"], timeout_seconds=GAME_TIMEOUT, child_script=CG_CHILD,
    )
    return {
        "lane": e["lane"], "opp": e["opp"], "candidate_seat": e["seat"], "g": e["g"],
        "seconds": round(time.time() - t0, 1),
        "completed": bool(res.get("completed")), "error": res.get("error"),
        "timeout": bool(res.get("timeout")), "steps": res.get("steps"),
        "candidate_won": res.get("candidate_won"), "draw": bool(res.get("draw")),
        "decisions": res.get("decisions"), "fallbacks": res.get("fallbacks"),
        "attacks": res.get("attacks"), "passes": res.get("passes"),
    }


# --------------------------------------------------------------------------- #
# finalize
# --------------------------------------------------------------------------- #
def _tally(games: list[dict]) -> dict:
    n = len(games)
    comp = [g for g in games if g["completed"] and not g["error"]]
    wins = sum(1 for g in comp if g["candidate_won"] is True)
    losses = sum(1 for g in comp if g["candidate_won"] is False)
    draws = sum(1 for g in comp if g["draw"])
    errors = sum(1 for g in games if g["error"] and not g["timeout"])
    timeouts = sum(1 for g in games if g["timeout"])
    decisive = wins + losses
    wr = round(wins / decisive, 4) if decisive else None
    ci = _wilson(wins, decisive) if decisive else None
    return {"games": n, "completed": len(comp), "wins": wins, "losses": losses,
            "draws": draws, "errors": errors, "timeouts": timeouts,
            "decisive": decisive, "decisive_win_rate": wr, "wilson95": ci}


def _seat_split(games: list[dict]) -> dict:
    out = {}
    for s in (0, 1):
        out[f"seat{s}"] = _tally([g for g in games if g["candidate_seat"] == s])
    return out


def _parent_partb(ref_id: str) -> dict | None:
    if not MATRIX.is_file():
        return None
    cells = json.loads(MATRIX.read_text(encoding="utf-8")).get("cells", {})
    row = cells.get(PARENT_ID, {})
    c = row.get(ref_id)
    if not c:
        return None
    ow, rw = c.get("our_win", 0), c.get("reference_win", 0)
    dec = ow + rw
    return {"games": c.get("games"), "our_win": ow, "reference_win": rw,
            "decisive": dec, "decisive_win_rate": round(ow / dec, 4) if dec else None}


def _read_noise_control() -> dict | None:
    """Compact summary of the Part-I self-mirror noise control, if present.

    The noise control is the honesty gate on the parent 'beats parent' verdict: it
    shows the stochastic cabt self-mirror null is symmetric (no slot/seat artifact)
    and Fisher-tests the H2H win count against that null. Read-only; it never blocks
    or alters game scheduling and is simply surfaced alongside the verdict.
    """
    if not NOISE_CTRL.is_file():
        return None
    try:
        d = json.loads(NOISE_CTRL.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    fz = d.get("fisher_h2h_vs_mirror_p", {})
    return {
        "corroborates": d.get("noise_control_corroborates"),
        "controls_clean": d.get("controls_clean"),
        "fisher_pooled_p": fz.get("pooled_mirror"),
        "fisher_parent_mirror_p": fz.get("parent_mirror"),
        "fisher_candidate_mirror_p": fz.get("candidate_mirror"),
        "parent_mirror_wr": d.get("parent_mirror", {}).get("decisive_win_rate"),
        "candidate_mirror_wr": d.get("candidate_mirror", {}).get("decisive_win_rate"),
        "seat0_first_mover_wr": d.get("seat0_first_mover_pooled", {}).get("seat0_win_rate"),
        "clears_floor_conservative": d.get("h2h_clears_noise_floor_conservative"),
    }


def _finalize(progress: dict) -> int:
    games = list(progress["games"].values())
    by_lane = {"parent": [], "ref": [], "anchor": []}
    for g in games:
        by_lane.setdefault(g["lane"], []).append(g)

    root_ok = (_sha(ROOT_MAIN) == progress.get("root_main_sha")
               and _sha(ROOT_DECK) == progress.get("root_deck_sha"))
    ref_ids = progress.get("ref_ids", [])

    # ---- parent_child_eval ----
    pgames = by_lane["parent"]
    ptally = _tally(pgames)
    ci = ptally["wilson95"]
    if ci and ci[0] > 0.5:
        verdict = "candidate_beats_parent"
    elif ci and ci[1] < 0.5:
        verdict = "candidate_below_parent"
    else:
        verdict = "inconclusive"
    noise_control = _read_noise_control()
    parent_out = {
        "pass": 41, "part": "H", "lane": "parent_child", "candidate_id": CAND_ID,
        "parent_id": PARENT_ID, "no_upload": True, "local_only": True,
        "note": "decisive WR + Wilson 95% CI; superiority claimed ONLY if CI>0.5; "
                "the Part-I self-mirror noise control is the honesty gate (Fisher "
                "exact of this H2H vs a symmetric null).",
        "overall": ptally, "by_seat": _seat_split(pgames),
        "verdict": verdict, "noise_control": noise_control,
        "root_main_deck_unchanged": root_ok,
        "games": pgames,
    }

    # ---- public_reference_eval ----
    ref_rows = []
    for rid in ref_ids:
        rg = [g for g in by_lane["ref"] if g["opp"] == rid]
        t = _tally(rg)
        pb = _parent_partb(rid)
        delta = None
        if pb and pb["decisive_win_rate"] is not None and t["decisive_win_rate"] is not None:
            delta = round(t["decisive_win_rate"] - pb["decisive_win_rate"], 4)
        ref_rows.append({"reference_id": rid, "candidate": t,
                         "parent_partB": pb, "delta_vs_parent_partB": delta,
                         "by_seat": _seat_split(rg)})
    ref_all = _tally(by_lane["ref"])
    ref_out = {
        "pass": 41, "part": "H", "lane": "public_reference", "candidate_id": CAND_ID,
        "no_upload": True, "local_only": True,
        "note": ("decisive WR + Wilson 95% CI vs each public reference; delta is vs the "
                 "PARENT's own Part-B record. Feasibility/calibration only, NOT a "
                 "strength or Kaggle claim."),
        "overall_vs_all_refs": ref_all, "per_reference": ref_rows,
        "root_main_deck_unchanged": root_ok,
    }

    # ---- anchor_eval (water control + internal leader + dragapult reused) ----
    drag_games = [g for g in by_lane["ref"] if g["opp"] == DRAGAPULT_REF]
    anchor_specs = [
        ("water_control", WATER_CONTROL_ID,
         [g for g in by_lane["anchor"] if g["opp"] == WATER_CONTROL_ID]),
        ("internal_leader", INTERNAL_LEADER_ID,
         [g for g in by_lane["anchor"] if g["opp"] == INTERNAL_LEADER_ID]),
        ("dragapult_reference", DRAGAPULT_REF, drag_games),
    ]
    anchor_rows = []
    for role, aid, ag in anchor_specs:
        t = _tally(ag)
        ci_a = t["wilson95"]
        if ci_a and ci_a[0] > 0.5:
            v = "candidate_above"
        elif ci_a and ci_a[1] < 0.5:
            v = "candidate_below"
        else:
            v = "inconclusive"
        anchor_rows.append({"role": role, "anchor_id": aid,
                            "reused_from_ref_lane": role == "dragapult_reference",
                            "tally": t, "by_seat": _seat_split(ag), "verdict": v})
    anchor_out = {
        "pass": 41, "part": "H", "lane": "anchor", "candidate_id": CAND_ID,
        "no_upload": True, "local_only": True,
        "note": "decisive WR + Wilson 95% CI vs water control, internal leader, and "
                "the dragapult reference (reused from the ref lane).",
        "anchors": anchor_rows, "root_main_deck_unchanged": root_ok,
    }

    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass41_parent_child_eval.json").write_text(
        json.dumps(parent_out, indent=2, default=str), encoding="utf-8")
    (EXP / "pass41_public_reference_eval.json").write_text(
        json.dumps(ref_out, indent=2, default=str), encoding="utf-8")
    (EXP / "pass41_anchor_eval.json").write_text(
        json.dumps(anchor_out, indent=2, default=str), encoding="utf-8")

    _write_md(parent_out, ref_out, anchor_out)

    n = len(games)
    comp = sum(1 for g in games if g["completed"] and not g["error"])
    print(f"ALL DONE: games={n} completed={comp} parent_verdict={verdict} "
          f"root_unchanged={root_ok}")
    return 0


def _fmt_ci(t: dict) -> str:
    wr = t["decisive_win_rate"]
    ci = t["wilson95"]
    if wr is None:
        return "n/a"
    return f"{wr:.2f} [{ci[0]:.2f},{ci[1]:.2f}] (n={t['decisive']})"


def _write_md(parent_out: dict, ref_out: dict, anchor_out: dict) -> None:
    # parent
    p = parent_out["overall"]
    md = [
        "# Pass 41 (Part H) — Parent/Child Head-to-Head", "",
        f"> Candidate `{CAND_ID}` vs parent `{PARENT_ID}`. Decisive WR + Wilson 95% "
        "CI. **No superiority claim unless the CI lies strictly above 0.50.**", "",
        f"- overall: candidate {p['wins']}W / {p['losses']}L / {p['draws']}D "
        f"(decisive WR {_fmt_ci(p)})",
        f"- by seat: P0 {_fmt_ci(parent_out['by_seat']['seat0'])}  ·  "
        f"P1 {_fmt_ci(parent_out['by_seat']['seat1'])}",
        f"- errors={p['errors']} timeouts={p['timeouts']}  ·  root unchanged: "
        f"{'yes' if parent_out['root_main_deck_unchanged'] else 'no'}",
        f"- **verdict: {parent_out['verdict']}**",
    ]
    nc = parent_out.get("noise_control")
    if nc:
        md.append(
            f"- self-mirror noise control (Part I): **corroborates="
            f"{nc.get('corroborates')}** · pooled-mirror Fisher p="
            f"{nc.get('fisher_pooled_p')} · controls_clean={nc.get('controls_clean')} "
            f"· seat-0 first-mover WR={nc.get('seat0_first_mover_wr')} "
            f"(strict CI-non-overlap heuristic clears floor: "
            f"{nc.get('clears_floor_conservative')})")
    else:
        md.append("- self-mirror noise control (Part I): not yet run")
    md.append("")
    (EXP / "pass41_parent_child_eval.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    # public refs
    md = [
        "# Pass 41 (Part H) — Public-Reference Evaluation", "",
        f"> Candidate `{CAND_ID}` vs all 5 Pass-40 public references. Decisive WR + "
        "Wilson 95% CI; delta is vs the **parent's own Part-B** record. "
        "Calibration/feasibility only — NOT a strength or Kaggle claim.", "",
        f"- overall vs all refs: {_fmt_ci(ref_out['overall_vs_all_refs'])}", "",
        "| reference | candidate WR [CI] (n) | parent Part-B WR | delta |",
        "|---|---|---|---|",
    ]
    for r in ref_out["per_reference"]:
        pb = r["parent_partB"]
        pbwr = f"{pb['decisive_win_rate']:.2f}" if pb and pb["decisive_win_rate"] is not None else "—"
        dl = f"{r['delta_vs_parent_partB']:+.2f}" if r["delta_vs_parent_partB"] is not None else "—"
        md.append(f"| `{r['reference_id']}` | {_fmt_ci(r['candidate'])} | {pbwr} | {dl} |")
    md.append("")
    (EXP / "pass41_public_reference_eval.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    # anchors
    md = [
        "# Pass 41 (Part H) — Anchor Evaluation", "",
        f"> Candidate `{CAND_ID}` vs water control, internal leader, and the dragapult "
        "reference (reused from the ref lane). Decisive WR + Wilson 95% CI.", "",
        "| role | anchor | candidate WR [CI] (n) | verdict | reused |",
        "|---|---|---|---|---|",
    ]
    for a in anchor_out["anchors"]:
        md.append(f"| {a['role']} | `{a['anchor_id']}` | {_fmt_ci(a['tally'])} | "
                  f"{a['verdict']} | {'yes' if a['reused_from_ref_lane'] else 'no'} |")
    md.append("")
    (EXP / "pass41_anchor_eval.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def _load_progress(ref_ids: list[str]) -> dict:
    if PROGRESS.is_file():
        try:
            return json.loads(PROGRESS.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"games": {}, "ref_ids": ref_ids,
            "root_main_sha": _sha(ROOT_MAIN), "root_deck_sha": _sha(ROOT_DECK)}


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    cand_main, cand_deck, info = _build_plan()
    plan = info["plan"]
    progress = _load_progress(info["ref_ids"])
    progress["ref_ids"] = info["ref_ids"]
    games = progress["games"]

    pending = [e for e in plan if _key(e) not in games]
    if not pending:
        return _finalize(progress)

    start = time.time()
    ran = 0
    for e in pending:
        if time.time() - start > INVOCATION_WALL_BUDGET and ran > 0:
            break
        res = _run_game(cand_main, cand_deck, e)
        games[_key(e)] = res
        PROGRESS.write_text(json.dumps(progress, indent=2, default=str), encoding="utf-8")
        ran += 1
        flag = "OK" if (res["completed"] and not res["error"]) else "FAIL"
        print(f"[{flag}] {_key(e)}  {res['seconds']}s won={res.get('candidate_won')} "
              f"err={res.get('error')}")

    remaining = [e for e in plan if _key(e) not in games]
    if remaining:
        print(f"TICK DONE: ran {ran}, {len(remaining)} remaining — re-invoke")
        return 2
    return _finalize(progress)


if __name__ == "__main__":
    raise SystemExit(main())
