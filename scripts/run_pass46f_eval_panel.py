#!/usr/bin/env python3
"""PASS 46F (Part H) — subprocess-isolated EVAL PANEL for the owned cg_typed candidate.

Four LOCAL-ONLY lanes, all played in a KILLABLE child (`run_one_game_subprocess`
+ the Pass-41 cg-duel child, reused verbatim), RESUMABLE + wall-budgeted (every
finished game is persisted and skipped on re-run; re-invoke until ``ALL DONE``):

  1. parent_h2h          — candidate vs its INTERNAL parent source, >=20 games,
                           seat-balanced (10/seat). Decisive Wilson 95% CI; per-seat
                           breakdown. This is the only lane that may support a
                           LOCAL-ONLY "edges parent" reading (never a promotion).
  2. internal_anchor_eval— candidate vs an INTERNAL water baseline (NOT a public
                           ref). Supportive context only.
  3. public_reference_eval—candidate vs >=2 PUBLIC references. BENCHMARK-ONLY delta:
                           references are never source/parent/candidate, never enter
                           pool/queue/lifecycle/rankings, and a ref result NEVER
                           becomes a "beats reference"/promotion claim.
  4. noise_control       — parent-mirror + candidate-mirror self-mirror nulls
                           (identical policy both seats; true WR = 0.50 by symmetry).
                           PRIMARY corroboration of the parent_h2h reading is a
                           two-tailed Fisher exact of the H2H win count vs the pooled
                           self-mirror null, GATED on both mirror CIs straddling 0.50.

All win/loss numbers are local cabt outcomes — NOT Kaggle scores. NO upload / submit
/ promote / mutate; root main.py/deck.csv read-only; no exact-damage / lethal /
missed-KO / Boss-gust / spread / best-action claims.

Outputs (data/experiments/):
  pass46f_parent_h2h.{json,md}
  pass46f_internal_anchor_eval.{json,md}
  pass46f_public_reference_eval.{json,md}
  pass46f_noise_control.{json,md}
  pass46f_eval_panel.json                (combined index)
Progress (transient): pass46f_eval_panel_progress.json
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
CAND_ID = "cg_typed_water_anti_disruption_searchcal_v1"
CAND_TAR = REPO / "data/submissions/candidates_pass46f" / f"{CAND_ID}.tar.gz"
CAND_RUN = REPO / "data/tournament/benchmark/_cg_cand_extracted" / CAND_ID
PROGRESS = EXP / "pass46f_eval_panel_progress.json"
ROOT_MAIN = REPO / "main.py"
ROOT_DECK = REPO / "deck.csv"
POOL = REPO / "data/tournament/candidate_pool.json"

from ptcg_activegraph.decks.deck_io import load_deck  # noqa: E402
from ptcg_activegraph.experiments.runner import run_one_game_subprocess  # noqa: E402
from ptcg_activegraph.tournament.artifacts import safe_extract_all  # noqa: E402

CG_CHILD = str(REPO / "src/ptcg_activegraph/experiments/_pass41_cg_duel_subprocess.py")
GAME_TIMEOUT = 70
INVOCATION_WALL_BUDGET = 95
PARENT_ID = "league_water_anti_disruption_pivot_v1"
ANCHOR_ID = "league_water_core_reference"   # INTERNAL water baseline (NOT a public ref)
PUBLIC_REFS = ["public_ref_kiyotah_dragapult", "public_ref_kiyotah_mega_lucario"]

H2H_PER_SEAT = 10      # 20 games seat-balanced (pre-registered minimum)
ANCHOR_PER_SEAT = 5    # 10 games
REF_PER_SEAT = 3       # 6 games/ref (benchmark-only)
MIRROR_PER_SEAT = 5    # 10 games/mirror lane


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _wilson(wins: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return [round(max(0.0, center - half), 4), round(min(1.0, center + half), 4)]


def _fisher_two_tailed(a: int, b: int, c: int, d: int) -> float | None:
    """Two-tailed Fisher exact p for 2x2 [[a,b],[c,d]] (row1=H2H, row2=null)."""
    n1, n2 = a + b, c + d
    w, loss = a + c, b + d
    n = n1 + n2
    if n == 0 or n1 == 0 or n2 == 0 or w == 0 or loss == 0:
        return None
    denom = math.comb(n, n1)

    def prob(x: int) -> float:
        return math.comb(w, x) * math.comb(loss, n1 - x) / denom

    p_obs = prob(a)
    lo, hi = max(0, n1 - loss), min(w, n1)
    total = sum(prob(x) for x in range(lo, hi + 1) if prob(x) <= p_obs + 1e-12)
    return round(min(1.0, total), 4)


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


def _build_specs() -> dict:
    """lane -> {slot_main/slot_deck (recorded slot), opp_main/opp_deck, kind}."""
    cand_dir = _ensure_candidate()
    cand_main, cand_deck = cand_dir / "main.py", load_deck(cand_dir / "deck.csv")
    par_dir = EXTR_OURS / PARENT_ID
    par_main, par_deck = par_dir / "main.py", load_deck(par_dir / "deck.csv")
    anc_dir = EXTR_OURS / ANCHOR_ID
    anc_main, anc_deck = anc_dir / "main.py", load_deck(anc_dir / "deck.csv")

    specs = {
        "parent_h2h": {"slot_main": cand_main, "slot_deck": cand_deck,
                       "opp_main": par_main, "opp_deck": par_deck, "kind": "parent_h2h"},
        "internal_anchor": {"slot_main": cand_main, "slot_deck": cand_deck,
                            "opp_main": anc_main, "opp_deck": anc_deck,
                            "kind": "internal_anchor"},
        "parent_mirror": {"slot_main": par_main, "slot_deck": par_deck,
                          "opp_main": par_main, "opp_deck": par_deck,
                          "kind": "noise_control"},
        "candidate_mirror": {"slot_main": cand_main, "slot_deck": cand_deck,
                             "opp_main": cand_main, "opp_deck": cand_deck,
                             "kind": "noise_control"},
    }
    for rid in PUBLIC_REFS:
        rdir = _ensure_ref(rid)
        specs[f"ref:{rid}"] = {"slot_main": cand_main, "slot_deck": cand_deck,
                               "opp_main": rdir / "main.py",
                               "opp_deck": load_deck(rdir / "deck.csv"),
                               "kind": "public_reference"}
    return specs


def _build_plan(specs: dict) -> list[dict]:
    plan: list[dict] = []

    def add(lane: str, per_seat: int):
        for seat in (0, 1):
            for g in range(per_seat):
                plan.append({"lane": lane, "seat": seat, "g": g})

    add("parent_h2h", H2H_PER_SEAT)
    add("internal_anchor", ANCHOR_PER_SEAT)
    for rid in PUBLIC_REFS:
        add(f"ref:{rid}", REF_PER_SEAT)
    add("parent_mirror", MIRROR_PER_SEAT)
    add("candidate_mirror", MIRROR_PER_SEAT)
    return plan


def _key(e: dict) -> str:
    return f"{e['lane']}::seat{e['seat']}::g{e['g']}"


def _run_game(specs: dict, e: dict) -> dict:
    s = specs[e["lane"]]
    t0 = time.time()
    res = run_one_game_subprocess(
        control_main=s["opp_main"], control_deck=s["opp_deck"],
        cand_main=s["slot_main"], cand_deck=s["slot_deck"],
        candidate_seat=e["seat"], timeout_seconds=GAME_TIMEOUT, child_script=CG_CHILD)
    return {"lane": e["lane"], "kind": s["kind"], "candidate_seat": e["seat"],
            "g": e["g"], "seconds": round(time.time() - t0, 1),
            "completed": bool(res.get("completed")), "error": res.get("error"),
            "timeout": bool(res.get("timeout")), "steps": res.get("steps"),
            "candidate_won": res.get("candidate_won"), "draw": bool(res.get("draw")),
            "fallbacks": res.get("fallbacks")}


def _tally(games: list[dict]) -> dict:
    comp = [g for g in games if g["completed"] and not g["error"]]
    wins = sum(1 for g in comp if g["candidate_won"] is True)
    losses = sum(1 for g in comp if g["candidate_won"] is False)
    draws = sum(1 for g in comp if g["draw"])
    decisive = wins + losses
    return {"games": len(games), "completed": len(comp), "errors": len(games) - len(comp),
            "wins": wins, "losses": losses, "draws": draws, "decisive": decisive,
            "decisive_win_rate": round(wins / decisive, 4) if decisive else None,
            "wilson95": _wilson(wins, decisive) if decisive else None}


def _by_seat(games: list[dict]) -> dict:
    return {"seat0": _tally([g for g in games if g["candidate_seat"] == 0]),
            "seat1": _tally([g for g in games if g["candidate_seat"] == 1])}


def _straddles_half(ci: list[float] | None) -> bool | None:
    if not ci:
        return None
    return ci[0] <= 0.5 <= ci[1]


def _refs_clean() -> dict:
    pool_ids = set()
    if POOL.is_file():
        try:
            pj = json.loads(POOL.read_text(encoding="utf-8"))
            cands = pj.get("candidates", pj if isinstance(pj, list) else [])
            for c in (cands.values() if isinstance(cands, dict) else cands):
                cid = (c.get("candidate_id") or c.get("id")) if isinstance(c, dict) else None
                if cid:
                    pool_ids.add(cid)
        except Exception:  # noqa: BLE001
            pass
    leaked = sorted(set(PUBLIC_REFS) & pool_ids)
    return {"public_refs": PUBLIC_REFS, "leaked_into_pool": leaked, "clean": not leaked}


def _fmt(t: dict) -> str:
    wr, ci = t["decisive_win_rate"], t["wilson95"]
    if wr is None:
        return "n/a"
    return f"{wr:.2f}[{ci[0]:.2f},{ci[1]:.2f}](n={t['decisive']})"


def _pstr(p: float | None) -> str:
    return "n/a" if p is None else f"{p:.3f}{'*' if p < 0.05 else ''}"


def _write_json_md(name: str, payload: dict, md_lines: list[str]) -> None:
    (EXP / f"{name}.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    (EXP / f"{name}.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")


def _finalize(progress: dict) -> int:
    games = list(progress["games"].values())
    by_lane: dict[str, list[dict]] = {}
    for g in games:
        by_lane.setdefault(g["lane"], []).append(g)

    root_ok = (_sha(ROOT_MAIN) == progress.get("root_main_sha")
               and _sha(ROOT_DECK) == progress.get("root_deck_sha"))
    refs_clean = _refs_clean()
    common = {"pass": "46f", "candidate_id": CAND_ID, "no_upload": True,
              "local_only": True, "upload_performed": False,
              "root_main_deck_unchanged": root_ok,
              "note": "Local cabt outcomes only — NOT Kaggle scores. No exact-damage/"
                      "lethal/missed-KO/Boss-gust/spread/best-action claims."}

    # ---- Lane 1: parent_h2h -------------------------------------------------
    h2h_games = by_lane.get("parent_h2h", [])
    h2h = _tally(h2h_games)
    h2h_seat = _by_seat(h2h_games)
    seat0_wr = h2h_seat["seat0"]["decisive_win_rate"]
    seat1_wr = h2h_seat["seat1"]["decisive_win_rate"]
    both_seats_winning = bool(seat0_wr is not None and seat1_wr is not None
                              and seat0_wr > 0.5 and seat1_wr > 0.5)
    h2h_lower = h2h["wilson95"][0] if h2h["wilson95"] else None
    edges_parent_local = bool(h2h_lower is not None and h2h_lower > 0.5
                              and both_seats_winning and h2h["decisive"] >= 20)
    parent_payload = {**common, "part": "H", "lane": "parent_h2h", "parent_id": PARENT_ID,
                      "games_min_required": 2 * H2H_PER_SEAT, "overall": h2h,
                      "by_seat": h2h_seat, "both_seats_winning": both_seats_winning,
                      "decisive_wilson_lower_gt_half": (h2h_lower is not None and h2h_lower > 0.5),
                      "edges_parent_local_only": edges_parent_local}
    _write_json_md("pass46f_parent_h2h", parent_payload, [
        "# Pass 46F (Part H) — candidate vs INTERNAL parent (H2H)", "",
        f"> Local cabt H2H, seat-balanced ({H2H_PER_SEAT}/seat). Win-rate is a "
        "**local-only** signal, **not** a Kaggle score and **not** a promotion.", "",
        f"- overall cand decisive WR: **{_fmt(h2h)}** · both seats winning: "
        f"**{'yes' if both_seats_winning else 'no'}**",
        f"- seat0 (cand first): {_fmt(h2h_seat['seat0'])} · seat1: {_fmt(h2h_seat['seat1'])}",
        f"- decisive Wilson lower > 0.5: "
        f"**{'yes' if (h2h_lower is not None and h2h_lower > 0.5) else 'no'}** · "
        f"**edges_parent_local_only: {'yes' if edges_parent_local else 'no'}**",
        f"- parent: `{PARENT_ID}` · root unchanged: {'yes' if root_ok else 'no'} · "
        "no_upload: true", ""])

    # ---- Lane 2: internal_anchor_eval --------------------------------------
    anc_games = by_lane.get("internal_anchor", [])
    anc = _tally(anc_games)
    anc_payload = {**common, "part": "H", "lane": "internal_anchor_eval",
                   "anchor_id": ANCHOR_ID, "is_public_reference": False,
                   "overall": anc, "by_seat": _by_seat(anc_games),
                   "context_only": True}
    _write_json_md("pass46f_internal_anchor_eval", anc_payload, [
        "# Pass 46F (Part H) — candidate vs INTERNAL water anchor", "",
        f"> Supportive context only. `{ANCHOR_ID}` is an **internal** water baseline, "
        "NOT a public reference.", "",
        f"- cand decisive WR vs anchor: **{_fmt(anc)}**",
        f"- root unchanged: {'yes' if root_ok else 'no'} · no_upload: true", ""])

    # ---- Lane 3: public_reference_eval (BENCHMARK-ONLY) --------------------
    ref_lanes = {lane: g for lane, g in by_lane.items() if lane.startswith("ref:")}
    per_ref = {lane: _tally(g) for lane, g in ref_lanes.items()}
    pooled_ref = _tally([g for gs in ref_lanes.values() for g in gs])
    ref_payload = {**common, "part": "H", "lane": "public_reference_eval",
                   "benchmark_only": True, "public_refs": PUBLIC_REFS,
                   "references_not_in_pool": refs_clean,
                   "references_as_source_parent_candidate": False,
                   "per_reference": per_ref, "pooled": pooled_ref,
                   "promotion_relevant": False,
                   "note": common["note"] + " References are BENCHMARK-ONLY: never "
                   "source/parent/candidate, never promoted, never in pool/queue/"
                   "lifecycle/rankings. A ref result is NEVER a 'beats reference' claim."}
    ref_md = [
        "# Pass 46F (Part H) — candidate vs PUBLIC references (BENCHMARK-ONLY)", "",
        "> **Benchmark-only delta.** Public references are never source/parent/"
        "candidate, never promoted, never entered into pool/queue/lifecycle/rankings. "
        "These numbers are a local sanity delta, **never** a 'beats reference' or "
        "promotion claim.", "",
        f"- pooled cand decisive WR vs refs: **{_fmt(pooled_ref)}**",
        f"- references absent from candidate_pool: "
        f"**{'yes' if refs_clean['clean'] else 'NO'}**", "",
        "| reference | cand decisive WR [CI] (n) |", "|---|---|"]
    for lane, t in per_ref.items():
        ref_md.append(f"| `{lane[4:]}` | {_fmt(t)} |")
    ref_md.append("")
    _write_json_md("pass46f_public_reference_eval", ref_payload, ref_md)

    # ---- Lane 4: noise_control (self-mirror) ------------------------------
    pm = _tally(by_lane.get("parent_mirror", []))
    cm = _tally(by_lane.get("candidate_mirror", []))
    pooled_mirror = _tally(by_lane.get("parent_mirror", [])
                           + by_lane.get("candidate_mirror", []))
    pm_clean = _straddles_half(pm["wilson95"])
    cm_clean = _straddles_half(cm["wilson95"])
    controls_clean = bool(pm_clean and cm_clean)

    fisher = {}
    if h2h["decisive"]:
        hw, hl = h2h["wins"], h2h["losses"]
        for nm, t in (("parent_mirror", pm), ("candidate_mirror", cm),
                      ("pooled_mirror", pooled_mirror)):
            fisher[nm] = (_fisher_two_tailed(hw, hl, t["wins"], t["losses"])
                          if t["decisive"] else None)
    pooled_p = fisher.get("pooled_mirror")
    sig_pooled = pooled_p is not None and pooled_p < 0.05
    if not controls_clean:
        corroborates = "no_slot_bias_detected"
    elif sig_pooled:
        corroborates = "yes"
    elif fisher.get("parent_mirror") is not None and fisher["parent_mirror"] < 0.05:
        corroborates = "suggestive_significant_vs_parent_null_only"
    else:
        corroborates = "inconclusive_small_sample"
    noise_payload = {**common, "part": "H", "lane": "noise_control",
                     "parent_id": PARENT_ID, "parent_mirror": pm,
                     "candidate_mirror": cm, "pooled_mirror": pooled_mirror,
                     "parent_mirror_ci_straddles_half": pm_clean,
                     "candidate_mirror_ci_straddles_half": cm_clean,
                     "controls_clean": controls_clean,
                     "fisher_h2h_vs_mirror_p": fisher,
                     "noise_control_corroborates": corroborates}
    _write_json_md("pass46f_noise_control", noise_payload, [
        "# Pass 46F (Part H) — self-mirror noise control", "",
        "> Null controls (identical policy both seats; true WR = 0.50 by symmetry). "
        "The cand-slot CI should straddle 0.50. PRIMARY corroboration of the "
        "parent-H2H reading is a two-tailed **Fisher exact** of the H2H win count vs "
        "the pooled self-mirror null, gated on both mirror CIs straddling 0.50.", "",
        "| lane | cand-slot decisive WR [CI] (n) | straddles 0.50? | Fisher p (H2H vs null) |",
        "|---|---|---|---|",
        f"| parent-mirror | {_fmt(pm)} | {'yes' if pm_clean else 'NO'} | "
        f"{_pstr(fisher.get('parent_mirror'))} |",
        f"| candidate-mirror | {_fmt(cm)} | {'yes' if cm_clean else 'NO'} | "
        f"{_pstr(fisher.get('candidate_mirror'))} |",
        f"| **pooled mirror** | {_fmt(pooled_mirror)} | — | "
        f"**{_pstr(pooled_p)}** |", "",
        f"- controls clean (no slot bias): {'yes' if controls_clean else 'NO'}",
        f"- **noise_control_corroborates: {corroborates}** (`*` = Fisher p<0.05)", ""])

    # ---- Combined index ----------------------------------------------------
    panel = {**common, "part": "H", "kind": "eval_panel",
             "parent_id": PARENT_ID, "anchor_id": ANCHOR_ID, "public_refs": PUBLIC_REFS,
             "references_not_in_pool": refs_clean,
             "games_total": len(games),
             "lanes": {
                 "parent_h2h": {"overall": h2h, "by_seat": h2h_seat,
                                "both_seats_winning": both_seats_winning,
                                "edges_parent_local_only": edges_parent_local},
                 "internal_anchor_eval": {"overall": anc},
                 "public_reference_eval": {"pooled": pooled_ref, "per_reference": per_ref,
                                           "benchmark_only": True, "promotion_relevant": False},
                 "noise_control": {"parent_mirror": pm, "candidate_mirror": cm,
                                   "pooled_mirror": pooled_mirror,
                                   "controls_clean": controls_clean,
                                   "fisher_h2h_vs_mirror_p": fisher,
                                   "noise_control_corroborates": corroborates}}}
    (EXP / "pass46f_eval_panel.json").write_text(
        json.dumps(panel, indent=2, default=str) + "\n", encoding="utf-8")

    print(f"ALL DONE: H2H={_fmt(h2h)} both_seats={both_seats_winning} "
          f"edges_parent_local={edges_parent_local} | anchor={_fmt(anc)} | "
          f"refs_pooled={_fmt(pooled_ref)} | mirror_pooled={_fmt(pooled_mirror)} "
          f"controls_clean={controls_clean} fisher_pooled={_pstr(pooled_p)} "
          f"corroborates={corroborates} | root_ok={root_ok} refs_clean={refs_clean['clean']}",
          flush=True)
    return 0


def _load_progress() -> dict:
    if PROGRESS.is_file():
        try:
            return json.loads(PROGRESS.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"games": {}, "root_main_sha": _sha(ROOT_MAIN),
            "root_deck_sha": _sha(ROOT_DECK)}


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    specs = _build_specs()
    plan = _build_plan(specs)
    progress = _load_progress()
    games = progress["games"]

    pending = [e for e in plan if _key(e) not in games]
    if not pending:
        return _finalize(progress)

    start = time.time()
    ran = 0
    for e in pending:
        if time.time() - start > INVOCATION_WALL_BUDGET and ran > 0:
            break
        res = _run_game(specs, e)
        games[_key(e)] = res
        PROGRESS.write_text(json.dumps(progress, indent=2, default=str), encoding="utf-8")
        ran += 1
        flag = "OK" if (res["completed"] and not res["error"]) else "FAIL"
        print(f"[{flag}] {_key(e)}  {res['seconds']}s won={res.get('candidate_won')} "
              f"err={res.get('error')}", flush=True)

    remaining = [e for e in plan if _key(e) not in games]
    if remaining:
        done = len(plan) - len(remaining)
        print(f"TICK DONE: ran {ran}, {done}/{len(plan)} total — {len(remaining)} "
              "remaining — re-invoke", flush=True)
        return 2
    return _finalize(progress)


if __name__ == "__main__":
    raise SystemExit(main())
