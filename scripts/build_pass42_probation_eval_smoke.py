#!/usr/bin/env python3
"""Pass 42 (Part H) — probation evaluation smoke (LOCAL, ledger-free).

A *liveness* smoke for the freshly admitted probation candidates: each one is
played end-to-end against

  * its source parent at BOTH seats          (internal lane),
  * one distinct portfolio anchor            (internal lane),
  * one public reference opponent            (SEPARATE benchmark lane),

to prove the generated tarballs actually run inside the engine. This is a smoke /
placement seed ONLY — it is deliberately NOT recorded to any ledger and is NOT
promotion evidence: no win here elevates a candidate, and the public reference is
exercised purely on the benchmark lane (reference is the subprocess 'cand' whose
bundled ``cg/`` the child uses), never entering the lab pool or the main ledger.

Native cabt games run in hard-timeout subprocesses; the script is resumable —
each tick runs games until a wall budget elapses, persists progress, and exits
with code 2 until every game is done (then 0). Never starts the root workflow.

Outputs: data/experiments/pass42_probation_eval_smoke.{json,md}
"""

from __future__ import annotations

import json
import shutil
import sys
import tarfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.experiments.runner import run_one_game_subprocess  # noqa: E402
from ptcg_activegraph.tournament import benchmark as B  # noqa: E402
from ptcg_activegraph.tournament import generation as G  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool, PROBATION  # noqa: E402
from ptcg_activegraph.graph.events import EventType  # noqa: E402

EXP = REPO / "data" / "experiments"
POOL_PATH = REPO / "data" / "tournament" / "candidate_pool.json"
MANIFEST = EXP / "pass42_generated_candidates_manifest.json"
VALIDATION = EXP / "pass42_generated_candidate_validation.json"
PROGRESS = EXP / ".pass42_probation_eval_smoke_progress.json"
EXTRACT_DIR = REPO / "data" / "tmp" / "pass42_eval_smoke"
BENCH_LEDGER = REPO / "data" / "tournament" / "benchmark_events.jsonl"

GAME_TIMEOUT = 90
WALL_BUDGET = 20
CG_REF_CHILD = str(REPO / "src/ptcg_activegraph/experiments/_cg_reference_game_subprocess.py")


def _extract(tarball: Path, dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:gz") as t:
        t.extractall(dest)  # noqa: S202  (trusted local tarballs we built/ship)
    # flatten if single top dir
    if not (dest / "main.py").is_file():
        subs = [p for p in dest.iterdir() if p.is_dir()]
        if len(subs) == 1 and (subs[0] / "main.py").is_file():
            return subs[0]
    return dest


def _deck_ints(path: Path) -> list[int]:
    out: list[int] = []
    for tok in path.read_text(encoding="utf-8").replace(",", " ").split():
        tok = tok.strip()
        if tok:
            try:
                out.append(int(tok))
            except ValueError:
                pass
    return out


def _load_progress() -> dict:
    if PROGRESS.is_file():
        try:
            return json.loads(PROGRESS.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {}


def _save_progress(p: dict) -> None:
    PROGRESS.write_text(json.dumps(p, indent=2, default=str), encoding="utf-8")


def _resolve_dir(pool: CandidatePool, cid: str, kind: str) -> Path | None:
    c = pool.by_id(cid)
    if c is None:
        return None
    tar = G.resolve_tarball(c.tarball_path)
    if tar is None or not tar.is_file():
        return None
    return _extract(tar, EXTRACT_DIR / kind / cid)


def _build_plan(pool: CandidatePool, manifest: dict, admitted: list[str]) -> list[dict]:
    man_by_id = {m["generated_candidate_id"]: m for m in manifest["candidates"]}
    anchors = sorted(c.candidate_id for c in pool.candidates
                     if c.status == "portfolio_anchor")
    plan = []
    for gid in sorted(admitted):
        m = man_by_id[gid]
        parent = m["parent_candidate_id"]
        anchor = next((a for a in anchors if a != parent and a != gid), None)
        plan.append({"candidate_id": gid, "family_id": m["family_id"],
                     "parent": parent, "anchor": anchor})
    return plan


def _internal_game(cand_dir: Path, opp_dir: Path, seat: int) -> dict:
    res = run_one_game_subprocess(
        control_main=opp_dir / "main.py", control_deck=_deck_ints(opp_dir / "deck.csv"),
        cand_main=cand_dir / "main.py", cand_deck=_deck_ints(cand_dir / "deck.csv"),
        candidate_seat=seat, timeout_seconds=GAME_TIMEOUT)
    return {"completed": bool(res.get("completed")), "candidate_won": res.get("candidate_won"),
            "draw": bool(res.get("draw")), "steps": res.get("steps"),
            "timeout": bool(res.get("timeout")), "error": res.get("error"),
            "candidate_seat": seat}


def _reference_game(cand_dir: Path, ref_dir: Path) -> dict:
    # Reference is the subprocess 'cand' (its dir holds the bundled cg/); our
    # probation candidate is the 'control'. classify_result inverts to OUR view.
    res = run_one_game_subprocess(
        control_main=cand_dir / "main.py", control_deck=_deck_ints(cand_dir / "deck.csv"),
        cand_main=ref_dir / "main.py", cand_deck=_deck_ints(ref_dir / "deck.csv"),
        candidate_seat=0, timeout_seconds=GAME_TIMEOUT, child_script=CG_REF_CHILD)
    return {"completed": bool(res.get("completed")), "our_result": B.classify_result(res),
            "draw": bool(res.get("draw")), "steps": res.get("steps"),
            "timeout": bool(res.get("timeout")), "error": res.get("error"),
            "reference_as_cand": True}


def _count_lines(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(1 for _ in path.open("r", encoding="utf-8"))


def main() -> int:
    if not (MANIFEST.is_file() and VALIDATION.is_file()):
        print("FAIL: manifest/validation missing; run Parts D+E first.")
        return 1
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    validation = json.loads(VALIDATION.read_text(encoding="utf-8"))
    pool = CandidatePool.load(POOL_PATH)

    admitted = [gid for gid in validation.get("admitted_ids", [])
                if (pool.by_id(gid) and pool.by_id(gid).status == PROBATION)]
    plan = _build_plan(pool, manifest, admitted)

    prog = _load_progress()
    if "ledger_count_start" not in prog:
        prog["ledger_count_start"] = TournamentLedger().count()
        prog["bench_ledger_lines_start"] = _count_lines(BENCH_LEDGER)
        prog["games"] = {}
        _save_progress(prog)

    # deterministic reference opponent (benchmark lane)
    opponents = B.load_opponents()
    ref = opponents[0] if opponents else None
    ref_dir = None
    if ref is not None:
        ref_tar = REPO / ref.tarball
        if ref_tar.is_file():
            ref_dir = _extract(ref_tar, EXTRACT_DIR / "reference" / ref.agent_id)

    # build the deterministic work list
    units: list[tuple[str, dict]] = []
    for row in plan:
        gid = row["candidate_id"]
        units.append((f"{gid}::vs_parent_seat0",
                      {"gid": gid, "kind": "vs_parent", "opp": row["parent"],
                       "lane": "internal", "seat": 0}))
        units.append((f"{gid}::vs_parent_seat1",
                      {"gid": gid, "kind": "vs_parent", "opp": row["parent"],
                       "lane": "internal", "seat": 1}))
        units.append((f"{gid}::vs_anchor",
                      {"gid": gid, "kind": "vs_anchor", "opp": row["anchor"],
                       "lane": "internal", "seat": 0}))
        if ref_dir is not None:
            units.append((f"{gid}::vs_reference",
                          {"gid": gid, "kind": "vs_reference", "opp": ref.agent_id,
                           "lane": "benchmark", "seat": 0}))

    start = time.time()
    ran = 0
    dir_cache: dict[str, Path | None] = {}

    def cand_dir(cid: str) -> Path | None:
        if cid not in dir_cache:
            dir_cache[cid] = _resolve_dir(pool, cid, "candidate")
        return dir_cache[cid]

    def opp_dir(cid: str) -> Path | None:
        if cid not in dir_cache:
            dir_cache[cid] = _resolve_dir(pool, cid, "opponent")
        return dir_cache[cid]

    for key, u in units:
        if key in prog["games"]:
            continue
        if ran > 0 and (time.time() - start) > WALL_BUDGET:
            _save_progress(prog)
            print(f"tick: ran={ran} done={len(prog['games'])}/{len(units)} (resume)")
            return 2
        cd = cand_dir(u["gid"])
        if cd is None:
            prog["games"][key] = {**u, "completed": False,
                                  "error": "candidate tarball unresolved"}
            ran += 1
            _save_progress(prog)
            continue
        if u["lane"] == "benchmark":
            rec = _reference_game(cd, ref_dir)
        else:
            od = opp_dir(u["opp"]) if u["opp"] else None
            if od is None:
                rec = {"completed": False, "error": f"opponent {u['opp']} unresolved"}
            else:
                rec = _internal_game(cd, od, u["seat"])
        prog["games"][key] = {**u, **rec}
        ran += 1
        _save_progress(prog)

    return _finalize(prog, plan, ref, units)


def _finalize(prog: dict, plan: list[dict], ref, units: list) -> int:
    games = prog["games"]
    per_candidate = []
    all_live = True
    for row in plan:
        gid = row["candidate_id"]
        p0 = games.get(f"{gid}::vs_parent_seat0", {})
        p1 = games.get(f"{gid}::vs_parent_seat1", {})
        an = games.get(f"{gid}::vs_anchor", {})
        rf = games.get(f"{gid}::vs_reference")
        mandatory = [p0, p1, an]
        live = all(g.get("completed") and not g.get("error") and not g.get("timeout")
                   for g in mandatory)
        all_live = all_live and live
        per_candidate.append({
            "candidate_id": gid, "family_id": row["family_id"],
            "parent": row["parent"], "anchor": row["anchor"],
            "liveness_ok": live,
            "vs_parent_seat0": _slim(p0), "vs_parent_seat1": _slim(p1),
            "vs_anchor": _slim(an),
            "vs_reference": (_slim_ref(rf) if rf else
                            {"lane": "benchmark", "status": "not_run"}),
        })

    # ---- guardrails (HARD) ----------------------------------------------
    ledger_now = TournamentLedger().count()
    no_main_events = (ledger_now == prog["ledger_count_start"])
    bench_now = _count_lines(BENCH_LEDGER)
    no_bench_events = (bench_now == prog.get("bench_ledger_lines_start", bench_now))

    # no reference id may appear in any MAIN GameFinished game
    ref_ids = {o.agent_id for o in B.load_opponents()}
    main_events = TournamentLedger().load()
    gf_t = EventType.GameFinished.value
    ref_in_main_gf = False
    for e in main_events:
        if e.event_type != gf_t:
            continue
        pl = e.payload or {}
        ids = {pl.get("candidate_a"), pl.get("candidate_b"),
               pl.get("a"), pl.get("b")}
        if ids & ref_ids:
            ref_in_main_gf = True
            break

    lanes = {g.get("lane") for g in games.values()}
    lane_separated = (ref is None) or ("benchmark" in lanes and "internal" in lanes)

    ok = bool(all_live and no_main_events and no_bench_events
              and not ref_in_main_gf)

    out = {
        "pass_id": "pass42", "part": "H",
        "local_only": True, "no_upload": True, "ledger_free": True,
        "promotion_evidence": False,
        "note": "Liveness smoke + placement seed ONLY. Deliberately not written "
                "to any ledger; no win here promotes a candidate. The public "
                "reference is exercised on the SEPARATE benchmark lane "
                "(reference-as-cand) and never enters the lab pool/main ledger.",
        "game_timeout_seconds": GAME_TIMEOUT,
        "reference_opponent": (ref.agent_id if ref else None),
        "n_candidates": len(plan),
        "n_games": len(games),
        "guardrails": {
            "no_events_emitted_to_main_ledger": no_main_events,
            "no_events_emitted_to_benchmark_ledger": no_bench_events,
            "no_reference_id_in_main_game_finished": not ref_in_main_gf,
            "lanes_kept_separate": lane_separated,
            "all_mandatory_internal_games_live": all_live,
        },
        "per_candidate": per_candidate,
        "ok": ok,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass42_probation_eval_smoke.json").write_text(
        json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    (EXP / "pass42_probation_eval_smoke.md").write_text(_md(out), encoding="utf-8")
    # tidy extraction scratch
    if EXTRACT_DIR.exists():
        shutil.rmtree(EXTRACT_DIR, ignore_errors=True)

    print(f"pass42 eval smoke: ok={ok} candidates={len(plan)} games={len(games)} "
          f"all_live={all_live} no_main_events={no_main_events} "
          f"no_ref_in_main_gf={not ref_in_main_gf}")
    return 0 if ok else 1


def _slim(g: dict) -> dict:
    return {"completed": g.get("completed"), "candidate_won": g.get("candidate_won"),
            "draw": g.get("draw"), "steps": g.get("steps"),
            "timeout": g.get("timeout"), "error": g.get("error"),
            "candidate_seat": g.get("candidate_seat")}


def _slim_ref(g: dict) -> dict:
    return {"lane": "benchmark", "completed": g.get("completed"),
            "our_result": g.get("our_result"), "draw": g.get("draw"),
            "steps": g.get("steps"), "timeout": g.get("timeout"),
            "error": g.get("error"), "reference_as_cand": True}


def _md(out: dict) -> str:
    def yn(b):
        return "yes" if b else "no"
    g = out["guardrails"]
    L = [
        "# Pass 42 (Part H) — Probation Evaluation Smoke", "",
        f"_{out['note']}_", "",
        f"- candidates: **{out['n_candidates']}**, games played: **{out['n_games']}**",
        f"- reference opponent (benchmark lane): `{out['reference_opponent']}`",
        f"- per-game timeout: {out['game_timeout_seconds']}s", "",
        "## Guardrails",
        f"- no events emitted to the main lab ledger: **{yn(g['no_events_emitted_to_main_ledger'])}**",
        f"- no events emitted to the benchmark ledger: **{yn(g['no_events_emitted_to_benchmark_ledger'])}**",
        f"- no reference id in any main GameFinished: **{yn(g['no_reference_id_in_main_game_finished'])}**",
        f"- internal vs benchmark lanes kept separate: **{yn(g['lanes_kept_separate'])}**",
        f"- all mandatory internal games ran end-to-end (liveness): **{yn(g['all_mandatory_internal_games_live'])}**",
        "", "## Per candidate", "",
        "| candidate | family | parent | anchor | live | parent s0 | parent s1 | anchor | reference (bench) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    def cell(g):
        if not g:
            return "—"
        if g.get("error"):
            return "err"
        if g.get("timeout"):
            return "timeout"
        if g.get("draw"):
            return f"draw/{g.get('steps')}"
        w = g.get("candidate_won")
        tag = "win" if w is True else ("loss" if w is False else "?")
        return f"{tag}/{g.get('steps')}"

    def refcell(g):
        if not g or g.get("status") == "not_run":
            return "not run"
        if g.get("error"):
            return "err"
        if g.get("timeout"):
            return "timeout"
        return f"{g.get('our_result')}/{g.get('steps')}"

    for c in out["per_candidate"]:
        L.append(
            f"| `{c['candidate_id']}` | {c['family_id']} | `{c['parent']}` "
            f"| `{c['anchor']}` | {yn(c['liveness_ok'])} | {cell(c['vs_parent_seat0'])} "
            f"| {cell(c['vs_parent_seat1'])} | {cell(c['vs_anchor'])} "
            f"| {refcell(c['vs_reference'])} |")
    L += ["", "_win/loss is from the probation candidate's perspective and is a "
          "liveness observation only — NOT ranked, NOT placement-recorded, NOT "
          "promotion evidence. Reference column is OUR-perspective on the "
          "benchmark lane._", "", f"**overall ok: {yn(out['ok'])}**", ""]
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
