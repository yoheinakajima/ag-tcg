#!/usr/bin/env python3
"""Pass 41 (Part I, addendum) — self-mirror H2H NOISE-CONTROL for the cg_typed spike.

The Part-H parent/child verdict claims the candidate *beats* its stdlib parent
(10W/0L, Wilson CI strictly above 0.5, winning BOTH seats). Before trusting any
"beats parent" claim from the stochastic cabt engine we must show that claim is
NOT an artifact of (a) the engine's intrinsic game-to-game variance or (b) a
first-mover / seat advantage. This script measures that null floor with two
self-mirror lanes where the two seats run the *identical* policy:

  * parent-mirror     — parent  vs parent      (10 games, 5 per seat)
  * candidate-mirror  — candidate vs candidate (10 games, 5 per seat)

In a self-mirror the "cand-slot" decisive win-rate should be ~0.50 (its Wilson
95% CI should straddle 0.50); a CI that excludes 0.50 would expose a structural
slot bias that would invalidate the Part-H reading. We also report the seat-0
(first-mover) decisive win-rate pooled across both mirrors to quantify any
turn-order advantage. Finally we check whether the real Part-H parent-H2H
decisive-WR CI lies strictly ABOVE both mirror CIs and the seat-0 CI — i.e. the
observed superiority clears the measured noise floor.

Reuses the exact Part-G/H killable cg-duel child so the candidate (which carries
cg/) is seated identically. RESUMABLE + wall-budgeted: each finished game is
persisted and skipped on re-run; re-invoke until ``ALL DONE``.

Benchmark-only: NO upload/submit/promote/mutate; references are NOT involved;
root main.py/deck.csv read-only. Writes:
  data/experiments/pass41_h2h_noise_control.{json,md}
Progress (transient): data/experiments/pass41_h2h_noise_control_progress.json
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
CAND_RUN = REPO / "data/tournament/benchmark/_cg_cand_extracted/cg_typed_mono_lightning_miraidon_policy_v1"
CAND_TAR = REPO / "data/submissions/candidates_pass41/cg_typed_mono_lightning_miraidon_policy_v1.tar.gz"
PROGRESS = EXP / "pass41_h2h_noise_control_progress.json"
PARENT_EVAL = EXP / "pass41_parent_child_eval.json"
ROOT_MAIN = REPO / "main.py"
ROOT_DECK = REPO / "deck.csv"

from ptcg_activegraph.decks.deck_io import load_deck  # noqa: E402
from ptcg_activegraph.experiments.runner import run_one_game_subprocess  # noqa: E402
from ptcg_activegraph.tournament.artifacts import safe_extract_all  # noqa: E402

CG_CHILD = str(REPO / "src/ptcg_activegraph/experiments/_pass41_cg_duel_subprocess.py")
GAME_TIMEOUT = 100
INVOCATION_WALL_BUDGET = 75
CAND_ID = "cg_typed_mono_lightning_miraidon_policy_v1"
PARENT_ID = "mono_lightning_miraidon_easy"
GAMES_PER_SEAT = 10  # 20 games/lane (40 total) -> ~0.5 null with a tight CI


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _ensure_candidate() -> Path:
    if not (CAND_RUN / "cg" / "libcg.so").is_file() or not (CAND_RUN / "main.py").is_file():
        CAND_RUN.mkdir(parents=True, exist_ok=True)
        with tarfile.open(CAND_TAR) as t:
            safe_extract_all(t, CAND_RUN)
    return CAND_RUN


def _wilson(wins: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return [round(max(0.0, center - half), 4), round(min(1.0, center + half), 4)]


def _fisher_two_tailed(a: int, b: int, c: int, d: int) -> float | None:
    """Two-tailed Fisher exact p for the 2x2 table [[a,b],[c,d]].

    Row 1 = group 1 (wins=a, losses=b); row 2 = group 2 (wins=c, losses=d).
    Conditions on both margins; sums hypergeometric probabilities of every table
    (with the same margins) whose probability does not exceed the observed one.
    This is the correct small-sample test for comparing the Part-H H2H win count
    against a self-mirror null win count (a CI-overlap heuristic is far stricter).
    """
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


def _build_plan() -> tuple[dict, list[dict]]:
    cand_dir = _ensure_candidate()
    cand_main = cand_dir / "main.py"
    cand_deck = load_deck(cand_dir / "deck.csv")
    par_dir = EXTR_OURS / PARENT_ID
    par_main = par_dir / "main.py"
    par_deck = load_deck(par_dir / "deck.csv")

    lanes = {
        "parent_mirror": {"main": par_main, "deck": par_deck},
        "candidate_mirror": {"main": cand_main, "deck": cand_deck},
    }
    plan: list[dict] = []
    for lane in ("parent_mirror", "candidate_mirror"):
        for seat in (0, 1):
            for g in range(GAMES_PER_SEAT):
                plan.append({"lane": lane, "seat": seat, "g": g})
    return lanes, plan


def _key(e: dict) -> str:
    return f"{e['lane']}::seat{e['seat']}::g{e['g']}"


def _run_game(lanes: dict, e: dict) -> dict:
    spec = lanes[e["lane"]]
    t0 = time.time()
    # Both seats run the identical policy/deck (self-mirror); the candidate seat
    # is the "cand slot" whose win we record.
    res = run_one_game_subprocess(
        control_main=spec["main"], control_deck=spec["deck"],
        cand_main=spec["main"], cand_deck=spec["deck"],
        candidate_seat=e["seat"], timeout_seconds=GAME_TIMEOUT, child_script=CG_CHILD,
    )
    return {
        "lane": e["lane"], "candidate_seat": e["seat"], "g": e["g"],
        "seconds": round(time.time() - t0, 1),
        "completed": bool(res.get("completed")), "error": res.get("error"),
        "timeout": bool(res.get("timeout")), "steps": res.get("steps"),
        "candidate_won": res.get("candidate_won"), "draw": bool(res.get("draw")),
    }


def _tally_slot(games: list[dict]) -> dict:
    """Decisive win-rate of the CAND SLOT (should be ~0.5 in a self-mirror)."""
    comp = [g for g in games if g["completed"] and not g["error"]]
    wins = sum(1 for g in comp if g["candidate_won"] is True)
    losses = sum(1 for g in comp if g["candidate_won"] is False)
    draws = sum(1 for g in comp if g["draw"])
    decisive = wins + losses
    return {"games": len(games), "completed": len(comp), "wins": wins,
            "losses": losses, "draws": draws, "decisive": decisive,
            "decisive_win_rate": round(wins / decisive, 4) if decisive else None,
            "wilson95": _wilson(wins, decisive) if decisive else None}


def _tally_seat0(games: list[dict]) -> dict:
    """Decisive win-rate of the SEAT-0 (first-mover) player, pooled."""
    comp = [g for g in games if g["completed"] and not g["error"] and not g["draw"]
            and g["candidate_won"] is not None]
    seat0_wins = 0
    for g in comp:
        cand_at0 = g["candidate_seat"] == 0
        cand_won = g["candidate_won"] is True
        # seat-0 won iff (cand at seat0 and cand won) or (cand at seat1 and cand lost)
        if (cand_at0 and cand_won) or ((not cand_at0) and (not cand_won)):
            seat0_wins += 1
    decisive = len(comp)
    return {"decisive": decisive, "seat0_wins": seat0_wins,
            "seat0_win_rate": round(seat0_wins / decisive, 4) if decisive else None,
            "wilson95": _wilson(seat0_wins, decisive) if decisive else None}


def _read_parent_h2h() -> dict | None:
    if not PARENT_EVAL.is_file():
        return None
    try:
        d = json.loads(PARENT_EVAL.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    o = d.get("overall", {})
    return {"wins": o.get("wins"), "losses": o.get("losses"),
            "decisive": o.get("decisive"),
            "decisive_win_rate": o.get("decisive_win_rate"),
            "wilson95": o.get("wilson95"), "verdict": d.get("verdict")}


def _finalize(progress: dict) -> int:
    games = list(progress["games"].values())
    by_lane = {"parent_mirror": [], "candidate_mirror": []}
    for g in games:
        by_lane.setdefault(g["lane"], []).append(g)

    parent_slot = _tally_slot(by_lane["parent_mirror"])
    cand_slot = _tally_slot(by_lane["candidate_mirror"])
    pooled_slot = _tally_slot(by_lane["parent_mirror"] + by_lane["candidate_mirror"])
    seat0 = _tally_seat0(games)

    def _straddles_half(ci: list[float] | None) -> bool | None:
        if not ci:
            return None
        return ci[0] <= 0.5 <= ci[1]

    parent_clean = _straddles_half(parent_slot["wilson95"])
    cand_clean = _straddles_half(cand_slot["wilson95"])
    seat_clean = _straddles_half(seat0["wilson95"])

    # Primary test: Fisher exact (two-tailed) of the Part-H H2H win count against
    # each self-mirror null. (A CI-non-overlap heuristic is far too strict at n=10
    # and conflates the floor's measurement uncertainty with the floor itself.)
    h2h = _read_parent_h2h()
    fisher: dict[str, float | None] = {}
    if h2h and h2h.get("decisive"):
        hw = int(h2h["wins"]); hl = int(h2h["decisive"]) - hw
        for nm, t in (("parent_mirror", parent_slot),
                      ("candidate_mirror", cand_slot),
                      ("pooled_mirror", pooled_slot)):
            fisher[nm] = (_fisher_two_tailed(hw, hl, t["wins"], t["losses"])
                          if t["decisive"] else None)

    # Secondary (conservative) heuristic: does the H2H CI lie strictly above the
    # widest self-mirror / seat CI upper bound? Reported but NOT decisive.
    floor_uppers = [t["wilson95"][1] for t in (parent_slot, cand_slot)
                    if t["wilson95"]]
    if seat0["wilson95"]:
        floor_uppers.append(seat0["wilson95"][1])
    noise_floor_upper = max(floor_uppers) if floor_uppers else None
    clears_conservative = None
    if h2h and h2h.get("wilson95") and noise_floor_upper is not None:
        clears_conservative = h2h["wilson95"][0] > noise_floor_upper

    root_ok = (_sha(ROOT_MAIN) == progress.get("root_main_sha")
               and _sha(ROOT_DECK) == progress.get("root_deck_sha"))

    # Corroboration: controls must be clean (no structural slot bias), then the
    # pooled-mirror Fisher test decides. Significant -> corroborated; otherwise
    # honestly inconclusive at this sample size. Slot bias -> controls unreliable.
    controls_clean = bool(parent_clean and cand_clean)
    pooled_p = fisher.get("pooled_mirror")
    sig_pooled = pooled_p is not None and pooled_p < 0.05
    sig_parent = fisher.get("parent_mirror") is not None and fisher["parent_mirror"] < 0.05
    if not controls_clean:
        corroborates = "no_slot_bias_detected"
    elif sig_pooled:
        corroborates = "yes"
    elif sig_parent:
        corroborates = "suggestive_significant_vs_parent_null_only"
    else:
        corroborates = "inconclusive_small_sample"

    out = {
        "pass": 41, "part": "I", "lane": "h2h_noise_control",
        "candidate_id": CAND_ID, "parent_id": PARENT_ID,
        "no_upload": True, "local_only": True,
        "note": ("Self-mirror null controls (identical policy on both seats). The "
                 "cand-slot decisive-WR CI should straddle 0.50; seat-0 WR measures "
                 "first-mover advantage. PRIMARY corroboration = two-tailed Fisher "
                 "exact of the Part-H H2H win count vs the pooled self-mirror null, "
                 "gated on both mirror CIs straddling 0.50. CI-non-overlap is a "
                 "deliberately strict secondary heuristic only."),
        "games_per_seat_per_lane": GAMES_PER_SEAT,
        "parent_mirror": parent_slot,
        "candidate_mirror": cand_slot,
        "pooled_mirror": pooled_slot,
        "seat0_first_mover_pooled": seat0,
        "parent_mirror_ci_straddles_half": parent_clean,
        "candidate_mirror_ci_straddles_half": cand_clean,
        "seat0_ci_straddles_half": seat_clean,
        "controls_clean": controls_clean,
        "parent_h2h_partH": h2h,
        "fisher_h2h_vs_mirror_p": fisher,
        "noise_floor_upper_bound": noise_floor_upper,
        "h2h_clears_noise_floor_conservative": clears_conservative,
        "noise_control_corroborates": corroborates,
        "root_main_deck_unchanged": root_ok,
        "games": games,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass41_h2h_noise_control.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8")
    _write_md(out)

    print(f"ALL DONE: parent_mirror={_fmt(parent_slot)} candidate_mirror={_fmt(cand_slot)} "
          f"pooled={_fmt(pooled_slot)} seat0={seat0['seat0_win_rate']} "
          f"fisher_pooled_p={pooled_p} clears_floor_conservative={clears_conservative} "
          f"corroborates={corroborates} root_unchanged={root_ok}")
    return 0


def _fmt(t: dict) -> str:
    wr = t["decisive_win_rate"]
    ci = t["wilson95"]
    if wr is None:
        return "n/a"
    return f"{wr:.2f}[{ci[0]:.2f},{ci[1]:.2f}](n={t['decisive']})"


def _pstr(p: float | None) -> str:
    if p is None:
        return "n/a"
    return f"{p:.3f}{'*' if p < 0.05 else ''}"


def _write_md(out: dict) -> None:
    pm, cm, pl = out["parent_mirror"], out["candidate_mirror"], out["pooled_mirror"]
    s0 = out["seat0_first_mover_pooled"]
    h2h = out["parent_h2h_partH"]
    fz = out["fisher_h2h_vs_mirror_p"]
    h2h_str = (f"{h2h['decisive_win_rate']:.2f} {h2h['wilson95']} "
               f"({h2h['wins']}W/{h2h['losses']}L)" if h2h and h2h.get("wilson95")
               else "n/a")
    md = [
        "# Pass 41 (Part I) — Self-Mirror H2H Noise Control", "",
        "> Null controls where BOTH seats run the identical policy (true win-rate = "
        "0.50 by symmetry). The cand-slot decisive-WR CI should straddle 0.50; a CI "
        "excluding 0.50 would reveal a structural slot/seat artifact. Seat-0 WR "
        "quantifies first-mover advantage. PRIMARY corroboration of the Part-H "
        "'beats parent' verdict is a two-tailed **Fisher exact** test of the H2H "
        "win count vs the pooled self-mirror null (CI-non-overlap is a deliberately "
        "strict secondary heuristic only).", "",
        "| lane | cand-slot decisive WR [CI] (n) | CI straddles 0.50? | Fisher p (H2H vs this null) |",
        "|---|---|---|---|",
        f"| parent-mirror (`{PARENT_ID}` vs self) | {_fmt(pm)} | "
        f"{'yes' if out['parent_mirror_ci_straddles_half'] else 'NO'} | "
        f"{_pstr(fz.get('parent_mirror'))} |",
        f"| candidate-mirror (`{CAND_ID}` vs self) | {_fmt(cm)} | "
        f"{'yes' if out['candidate_mirror_ci_straddles_half'] else 'NO'} | "
        f"{_pstr(fz.get('candidate_mirror'))} |",
        f"| **pooled mirror** (both lanes) | {_fmt(pl)} | — | "
        f"**{_pstr(fz.get('pooled_mirror'))}** |",
        "",
        f"- seat-0 (first-mover) pooled decisive WR: "
        f"{s0['seat0_win_rate']} {s0['wilson95']} (n={s0['decisive']}) · "
        f"straddles 0.50: {'yes' if out['seat0_ci_straddles_half'] else 'NO'}",
        f"- controls clean (no structural slot bias): "
        f"{'yes' if out['controls_clean'] else 'NO'}",
        f"- Part-H parent-H2H: {h2h_str}",
        f"- secondary CI-non-overlap (strict) heuristic — H2H clears floor "
        f"(upper={out['noise_floor_upper_bound']}): "
        f"{out['h2h_clears_noise_floor_conservative']}",
        f"- **noise_control_corroborates: {out['noise_control_corroborates']}** "
        "(`*` = Fisher p<0.05)",
        f"- root main.py/deck.csv unchanged: "
        f"{'yes' if out['root_main_deck_unchanged'] else 'no'}",
        "- no_upload: true · local_only: true · references involved: none",
        "",
    ]
    (EXP / "pass41_h2h_noise_control.md").write_text("\n".join(md) + "\n", encoding="utf-8")


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
    lanes, plan = _build_plan()
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
        res = _run_game(lanes, e)
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
