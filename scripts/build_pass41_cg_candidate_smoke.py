#!/usr/bin/env python3
"""Pass 41 (Part G) — subprocess-isolated smoke matrix for the OWNED cg_typed candidate.

Proves the Pass-41 cg_typed candidate is *runnable* in the local cabt harness from
its immutable Part E tarball (``cg/`` alongside ``main.py`` + ``deck.csv``), across a
spread of opponents:

  * self                      — candidate vs itself
  * parent (both seats)       — vs its stdlib parent family
  * best internal anchor (2)  — vs our strongest internal family (from the Part B matrix)
  * >=2 public references (2)  — vs cg_typed public references (both seats)

Each game runs in a killable child (``run_one_game_subprocess`` + the dedicated
``_pass41_cg_duel_subprocess`` child, which seats OUR candidate as subject and
chdirs into the opponent dir). RESUMABLE + wall-budgeted: every finished game is
persisted and skipped on re-run; re-invoke until ``ALL DONE``.

Benchmark-only / feasibility: win/loss is context, NOT a strength claim and NOT a
Kaggle score. NO upload/submit/promote/mutate; root main.py/deck.csv read-only;
references never enter our pool/queue/lifecycle/rankings.

Outputs: data/experiments/pass41_cg_candidate_smoke.{json,md}
Progress (transient): data/experiments/pass41_cg_candidate_smoke_progress.json
"""
from __future__ import annotations

import hashlib
import json
import sys
import tarfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
EXP = REPO / "data" / "experiments"
EXTR_OURS = REPO / "data/tournament/benchmark/_our_extracted"
EXTR_REFS = REPO / "data/reference_agents/tarballs/_extracted"
CAND_TAR = REPO / "data/submissions/candidates_pass41/cg_typed_mono_lightning_miraidon_policy_v1.tar.gz"
CAND_RUN = REPO / "data/tournament/benchmark/_cg_cand_extracted/cg_typed_mono_lightning_miraidon_policy_v1"
MATRIX = REPO / "data/tournament/benchmark/projections/pass41_public_benchmark_matrix.json"
PROGRESS = EXP / "pass41_cg_candidate_smoke_progress.json"
ROOT_MAIN = REPO / "main.py"
ROOT_DECK = REPO / "deck.csv"
POOL = REPO / "data/tournament/candidate_pool.json"

from ptcg_activegraph.decks.deck_io import load_deck  # noqa: E402
from ptcg_activegraph.experiments.runner import run_one_game_subprocess  # noqa: E402
from ptcg_activegraph.tournament.artifacts import safe_extract_all  # noqa: E402
from ptcg_activegraph.tournament.benchmark import load_opponents  # noqa: E402

CG_CHILD = str(REPO / "src/ptcg_activegraph/experiments/_pass41_cg_duel_subprocess.py")
GAME_TIMEOUT = 110
INVOCATION_WALL_BUDGET = 80
PARENT_ID = "mono_lightning_miraidon_easy"
PUBLIC_REFS = ["public_ref_kiyotah_dragapult", "public_ref_kiyotah_iono"]


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


def _best_anchor() -> str:
    """Pick our strongest internal family (excluding the parent) by decisive WR
    against the public references, from the Part B benchmark matrix."""
    data = json.loads(MATRIX.read_text(encoding="utf-8"))
    cells = data.get("cells", {})
    best, best_key = None, None
    for subj, row in cells.items():
        if subj == PARENT_ID:
            continue
        ow = sum(v.get("our_win", 0) for v in row.values())
        rw = sum(v.get("reference_win", 0) for v in row.values())
        dec = ow + rw
        wr = (ow / dec) if dec else 0.0
        key = (wr, ow, subj)
        if best is None or key > best_key:
            best, best_key = subj, key
    return best or "water_basic_density_v1"


def _opponents() -> list[dict]:
    cand_dir = _ensure_candidate()
    cand_main = cand_dir / "main.py"
    cand_deck = load_deck(cand_dir / "deck.csv")
    anchor_id = _best_anchor()

    opps = [
        {"key": "self", "main": cand_main, "deck": cand_deck, "kind": "self"},
        {"key": f"parent:{PARENT_ID}", "main": EXTR_OURS / PARENT_ID / "main.py",
         "deck": load_deck(EXTR_OURS / PARENT_ID / "deck.csv"), "kind": "parent"},
        {"key": f"anchor:{anchor_id}", "main": EXTR_OURS / anchor_id / "main.py",
         "deck": load_deck(EXTR_OURS / anchor_id / "deck.csv"), "kind": "anchor"},
    ]
    for rid in PUBLIC_REFS:
        rdir = _ensure_ref(rid)
        opps.append({"key": f"ref:{rid}", "main": rdir / "main.py",
                     "deck": load_deck(rdir / "deck.csv"), "kind": "public_reference"})
    return cand_main, cand_deck, anchor_id, opps


def _game_list(opps: list[dict]) -> list[tuple[str, int]]:
    games = []
    for o in opps:
        seats = [0] if o["kind"] == "self" else [0, 1]
        for s in seats:
            games.append((o["key"], s))
    return games


def _load_progress() -> dict:
    if PROGRESS.is_file():
        try:
            return json.loads(PROGRESS.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"games": {}, "root_main_sha": _sha(ROOT_MAIN), "root_deck_sha": _sha(ROOT_DECK)}


def _run_game(cand_main: Path, cand_deck: list[int], opp: dict, seat: int) -> dict:
    t0 = time.time()
    res = run_one_game_subprocess(
        control_main=opp["main"], control_deck=opp["deck"],
        cand_main=cand_main, cand_deck=cand_deck,
        candidate_seat=seat, timeout_seconds=GAME_TIMEOUT, child_script=CG_CHILD,
    )
    err = res.get("error")
    is_import_or_deck = bool(err) and any(
        s in str(err).lower() for s in ("import", "modulenotfound", "deck", "no module", "cg"))
    return {
        "opponent": opp["key"], "kind": opp["kind"], "candidate_seat": seat,
        "seconds": round(time.time() - t0, 1),
        "completed": bool(res.get("completed")), "error": err,
        "import_or_deck_failure": is_import_or_deck,
        "timeout": bool(res.get("timeout")), "steps": res.get("steps"),
        "status": res.get("status"), "candidate_won": res.get("candidate_won"),
        "draw": bool(res.get("draw")), "decisions": res.get("decisions"),
        "fallbacks": res.get("fallbacks"), "attacks": res.get("attacks"),
        "passes": res.get("passes"),
    }


def _refs_not_in_pool() -> dict:
    ref_ids = {o.agent_id for o in load_opponents(include_optional=True)}
    pool_ids = set()
    if POOL.is_file():
        try:
            pj = json.loads(POOL.read_text(encoding="utf-8"))
            cands = pj.get("candidates", pj if isinstance(pj, list) else [])
            for c in (cands.values() if isinstance(cands, dict) else cands):
                cid = c.get("candidate_id") or c.get("id") if isinstance(c, dict) else None
                if cid:
                    pool_ids.add(cid)
        except Exception:  # noqa: BLE001
            pass
    leaked = sorted(ref_ids & pool_ids)
    return {"reference_ids": sorted(ref_ids), "leaked_into_pool": leaked,
            "clean": not leaked}


def _finalize(progress: dict, anchor_id: str) -> int:
    games = progress["games"]
    vals = list(games.values())
    completed = [g for g in vals if g["completed"] and not g["error"]]
    errors = [g for g in vals if g["error"] and not g["timeout"]]
    timeouts = [g for g in vals if g["timeout"]]
    import_deck_fail = [g for g in vals if g.get("import_or_deck_failure")]

    root_ok = (_sha(ROOT_MAIN) == progress.get("root_main_sha")
               and _sha(ROOT_DECK) == progress.get("root_deck_sha"))
    pool_check = _refs_not_in_pool()

    # per-opponent rollup
    per_opp: dict[str, dict] = {}
    for g in vals:
        d = per_opp.setdefault(g["opponent"], {
            "opponent": g["opponent"], "kind": g["kind"], "games": 0,
            "completed": 0, "errors": 0, "timeouts": 0,
            "cand_wins": 0, "cand_losses": 0, "draws": 0})
        d["games"] += 1
        if g["completed"] and not g["error"]:
            d["completed"] += 1
            if g["candidate_won"] is True:
                d["cand_wins"] += 1
            elif g["candidate_won"] is False:
                d["cand_losses"] += 1
            elif g["draw"]:
                d["draws"] += 1
        if g["error"] and not g["timeout"]:
            d["errors"] += 1
        if g["timeout"]:
            d["timeouts"] += 1

    n = len(vals)
    # hard-fail gates: any import/deck failure, any root mutation, any ref leak,
    # or repeated (>1) ERROR/TIMEOUT.
    hard_fail = bool(
        import_deck_fail or not root_ok or not pool_check["clean"]
        or len(errors) > 1 or len(timeouts) > 1)
    ok = (not hard_fail) and (len(completed) >= max(1, n - 1))

    out = {
        "pass": 41, "part": "G", "kind": "cg_candidate_smoke",
        "candidate_id": "cg_typed_mono_lightning_miraidon_policy_v1",
        "local_only": True, "no_upload": True, "upload_performed": False,
        "anchor_id": anchor_id, "public_refs": PUBLIC_REFS,
        "note": "feasibility smoke: win/loss is context only, NOT a strength claim "
                "and NOT a Kaggle score",
        "games_total": n, "games_completed": len(completed),
        "games_error": len(errors), "games_timeout": len(timeouts),
        "import_or_deck_failures": len(import_deck_fail),
        "root_main_deck_unchanged": root_ok,
        "references_not_in_pool": pool_check,
        "hard_fail": hard_fail, "ok": ok,
        "per_opponent": list(per_opp.values()),
        "games": vals,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass41_cg_candidate_smoke.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8")

    def yn(v):
        return "yes" if v else "no"
    md = [
        "# Pass 41 (Part G) — cg_typed Candidate Smoke Matrix", "",
        "> Owned cg_typed candidate run locally in cabt from its immutable Part E "
        "tarball (`cg/` alongside `main.py`). Win/loss is **feasibility context "
        "only, not a strength or Kaggle score**.", "",
        f"- games: **{len(completed)}/{n} completed**, errors={len(errors)}, "
        f"timeouts={len(timeouts)}, import/deck failures={len(import_deck_fail)}",
        f"- root main.py/deck.csv unchanged: **{yn(root_ok)}**  ·  references absent "
        f"from candidate_pool: **{yn(pool_check['clean'])}**",
        f"- anchor: `{anchor_id}`  ·  public refs: {', '.join(PUBLIC_REFS)}",
        f"- **hard_fail: {yn(hard_fail)}  ·  ok: {yn(ok)}**", "",
        "| opponent | kind | games | completed | cand W/L/D | errors | timeouts |",
        "|---|---|---|---|---|---|---|",
    ]
    for d in per_opp.values():
        md.append(
            f"| `{d['opponent']}` | {d['kind']} | {d['games']} | {d['completed']} | "
            f"{d['cand_wins']}/{d['cand_losses']}/{d['draws']} | {d['errors']} | "
            f"{d['timeouts']} |")
    md.append("")
    (EXP / "pass41_cg_candidate_smoke.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"ALL DONE: completed={len(completed)}/{n} hard_fail={hard_fail} ok={ok}")
    return 0 if ok else 1


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    cand_main, cand_deck, anchor_id, opps = _opponents()
    progress = _load_progress()
    progress.setdefault("anchor_id", anchor_id)
    games = progress["games"]
    all_games = _game_list(opps)
    pending = [g for g in all_games if f"{g[0]}::seat{g[1]}" not in games]
    if not pending:
        return _finalize(progress, progress.get("anchor_id", anchor_id))

    opp_by_key = {o["key"]: o for o in opps}
    start = time.time()
    ran = 0
    for okey, seat in pending:
        if time.time() - start > INVOCATION_WALL_BUDGET and ran > 0:
            break
        res = _run_game(cand_main, cand_deck, opp_by_key[okey], seat)
        games[f"{okey}::seat{seat}"] = res
        PROGRESS.write_text(json.dumps(progress, indent=2, default=str), encoding="utf-8")
        ran += 1
        flag = "OK" if (res["completed"] and not res["error"]) else "FAIL"
        print(f"[{flag}] {okey}::seat{seat}  {res['seconds']}s steps={res.get('steps')} "
              f"won={res.get('candidate_won')} err={res.get('error')}")

    remaining = [g for g in all_games if f"{g[0]}::seat{g[1]}" not in games]
    if remaining:
        print(f"TICK DONE: ran {ran} this invocation, {len(remaining)} remaining "
              f"— re-invoke to continue")
        return 2
    return _finalize(progress, progress.get("anchor_id", anchor_id))


if __name__ == "__main__":
    raise SystemExit(main())
