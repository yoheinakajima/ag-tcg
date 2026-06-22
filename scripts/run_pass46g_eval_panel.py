#!/usr/bin/env python3
"""PASS 46G (Part H) — fast eval panel (parent-H2H + intra-family + ref context).

Bounded, resumable cabt tournament over ONLY the Part-G-admitted candidates. Each
pairing plays GAMES split across both seats in a KILLABLE child. Produces Wilson
95% bounds on the candidate's decisive win-rate per pairing. This is the expensive
panel the architect gated to the *distinct* policies only.

The decision-relevant comparisons:
  * candidate vs its INTERNAL parent (H2H) — is the parent edge clearer than 46F?
  * diamond phase_aware vs diamond role_aware (intra-family) — since the role profile
    is operationally the family-only floor (0% top-1 divergence on live frames), this
    DIRECTLY measures whether the phase layer changes anything in actual gameplay;
  * representative candidates vs >=2 public references (benchmark-only opponents) —
    absolute feasibility context.

HONESTY: win/loss/draw is RELATIVE feasibility context, NOT a Kaggle score and NOT a
strength guarantee. References are benchmark-only opponents — never entered into any
pool / queue / lifecycle / ranking. Phase/role are observable heuristic labels — no
exact-damage / lethal / KO / Boss-gust / spread / best-action claim. LOCAL / READ-ONLY:
no Object Storage, no tick, no upload, no events, no promotion. Root main.py/deck.csv
untouched.

Outputs: data/experiments/pass46g_eval_panel.{json,md}
Progress (transient): data/experiments/pass46g_eval_panel_progress.json
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

from ptcg_activegraph.decks.deck_io import load_deck  # noqa: E402
from ptcg_activegraph.experiments.runner import run_one_game_subprocess  # noqa: E402
from ptcg_activegraph.tournament.artifacts import safe_extract_all  # noqa: E402

EXP = REPO / "data" / "experiments"
BUILD_JSON = EXP / "pass46g_candidate_build.json"
SMOKE_JSON = EXP / "pass46g_smoke_non_inertness.json"
PROGRESS = EXP / "pass46g_eval_panel_progress.json"
EXTR_OURS = REPO / "data/tournament/benchmark/_our_extracted"
EXTR_REFS = REPO / "data/reference_agents/tarballs/_extracted"
CAND_EXTRACT = REPO / "data/tournament/benchmark/_cg_cand_extracted"
ROOT_MAIN = REPO / "main.py"
ROOT_DECK = REPO / "deck.csv"
POOL = REPO / "data/tournament/candidate_pool.json"
CG_CHILD = str(REPO / "src/ptcg_activegraph/experiments/_pass41_cg_duel_subprocess.py")

REPRESENTATIVE_PROFILE = "phase_aware_tempo_v1"
PUBLIC_REFS = ["public_ref_kiyotah_dragapult", "public_ref_kiyotah_mega_lucario"]
GAMES_H2H = 10     # parent-H2H + intra-family (5 per seat)
GAMES_REF = 4      # reference context (2 per seat)
GAME_TIMEOUT = 70
INVOCATION_WALL_BUDGET = 95


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _wilson(wins: int, decisive: int, z: float = 1.96) -> tuple[float, float]:
    if decisive <= 0:
        return (0.0, 0.0)
    p = wins / decisive
    d = 1 + z * z / decisive
    c = p + z * z / (2 * decisive)
    m = z * math.sqrt(p * (1 - p) / decisive + z * z / (4 * decisive * decisive))
    return (round((c - m) / d, 4), round((c + m) / d, 4))


def _ensure_candidate(cand_id: str, tar_rel: str) -> Path:
    run = CAND_EXTRACT / cand_id
    if not (run / "main.py").is_file() or not (run / "cg" / "libcg.so").is_file():
        run.mkdir(parents=True, exist_ok=True)
        with tarfile.open(REPO / tar_rel) as t:
            safe_extract_all(t, run)
    return run


def _ensure_ref(ref_id: str) -> Path:
    run = EXTR_REFS / ref_id
    if not (run / "cg" / "libcg.so").is_file() or not (run / "main.py").is_file():
        run.mkdir(parents=True, exist_ok=True)
        with tarfile.open(REPO / "data/reference_agents/tarballs" / f"{ref_id}.tar.gz") as t:
            safe_extract_all(t, run)
    return run


def _build_pairings(cands_by_id: dict, admit: list[str]) -> list[dict]:
    """Each pairing: subject candidate vs an opponent, N games split over seats."""
    pairings: list[dict] = []
    admitted = [cands_by_id[c] for c in admit if c in cands_by_id]
    by_family: dict[str, dict[str, dict]] = {}
    for c in admitted:
        by_family.setdefault(c["parent_family"], {})[c["profile_id"]] = c

    # 1) candidate vs its internal parent (H2H).
    for c in admitted:
        pairings.append({"kind": "parent_h2h", "subject": c["candidate_id"],
                         "family": c["parent_family"], "profile": c["profile_id"],
                         "opp_kind": "parent", "opp_id": c["parent_candidate_id"],
                         "games": GAMES_H2H})

    # 2) intra-family phase vs role (role == family-only floor) — gameplay
    #    distinguishability of the phase layer.
    for fam, byp in by_family.items():
        ph = byp.get("phase_aware_tempo_v1")
        ro = byp.get("role_aware_energy_v1")
        if ph and ro:
            pairings.append({"kind": "intra_family_phase_vs_role",
                             "subject": ph["candidate_id"], "family": fam,
                             "profile": ph["profile_id"],
                             "opp_kind": "sibling_candidate",
                             "opp_id": ro["candidate_id"], "games": GAMES_H2H})

    # 3) representative candidates vs public references (benchmark-only context).
    for c in admitted:
        if c["profile_id"] != REPRESENTATIVE_PROFILE:
            continue
        for rid in PUBLIC_REFS:
            pairings.append({"kind": "reference_context",
                             "subject": c["candidate_id"], "family": c["parent_family"],
                             "profile": c["profile_id"], "opp_kind": "public_reference",
                             "opp_id": rid, "games": GAMES_REF})
    return pairings


def _resolve_opponent(opp_kind: str, opp_id: str, cands_by_id: dict):
    if opp_kind == "parent":
        d = EXTR_OURS / opp_id
        return d / "main.py", load_deck(d / "deck.csv")
    if opp_kind == "sibling_candidate":
        c = cands_by_id[opp_id]
        d = _ensure_candidate(opp_id, c["tarball"])
        return d / "main.py", load_deck(d / "deck.csv")
    if opp_kind == "public_reference":
        d = _ensure_ref(opp_id)
        return d / "main.py", load_deck(d / "deck.csv")
    raise ValueError(f"unknown opp_kind {opp_kind}")


def _run_game(cand_dir: Path, cand_deck, opp_main: Path, opp_deck, seat: int) -> dict:
    t0 = time.time()
    res = run_one_game_subprocess(
        control_main=opp_main, control_deck=opp_deck,
        cand_main=cand_dir / "main.py", cand_deck=cand_deck,
        candidate_seat=seat, timeout_seconds=GAME_TIMEOUT, child_script=CG_CHILD)
    err = res.get("error")
    return {"seat": seat, "seconds": round(time.time() - t0, 1),
            "completed": bool(res.get("completed")), "error": err,
            "timeout": bool(res.get("timeout")), "steps": res.get("steps"),
            "candidate_won": res.get("candidate_won"), "draw": bool(res.get("draw"))}


def _game_keys(pairings: list[dict]) -> list[tuple]:
    keys = []
    for p in pairings:
        for i in range(p["games"]):
            keys.append((f"{p['subject']}__vs__{p['opp_id']}", i, i % 2, p))
    return keys


def _load_progress() -> dict:
    if PROGRESS.is_file():
        try:
            return json.loads(PROGRESS.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"games": {}, "root_main_sha": _sha(ROOT_MAIN),
            "root_deck_sha": _sha(ROOT_DECK)}


def _refs_not_in_pool() -> dict:
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


def _finalize(progress: dict, pairings: list[dict]) -> int:
    games = progress["games"]
    by_pair: dict[str, dict] = {}
    for p in pairings:
        by_pair[f"{p['subject']}__vs__{p['opp_id']}"] = {
            "kind": p["kind"], "subject": p["subject"], "family": p["family"],
            "profile": p["profile"], "opp_kind": p["opp_kind"], "opp_id": p["opp_id"],
            "wins": 0, "losses": 0, "draws": 0, "errors": 0, "timeouts": 0,
            "games": 0}
    for key, g in games.items():
        pk = key.rsplit("::g", 1)[0]
        rec = by_pair.get(pk)
        if rec is None:
            continue
        rec["games"] += 1
        if g.get("error") and not g.get("timeout"):
            rec["errors"] += 1
            continue
        if g.get("timeout"):
            rec["timeouts"] += 1
            continue
        if g.get("candidate_won") is True:
            rec["wins"] += 1
        elif g.get("candidate_won") is False:
            rec["losses"] += 1
        elif g.get("draw"):
            rec["draws"] += 1
    for rec in by_pair.values():
        dec = rec["wins"] + rec["losses"]
        rec["decisive"] = dec
        rec["win_rate_decisive"] = round(rec["wins"] / dec, 4) if dec else None
        lo, hi = _wilson(rec["wins"], dec)
        rec["wilson_low"], rec["wilson_high"] = lo, hi
        rec["beats_opp_95"] = bool(dec and lo > 0.5)
        rec["loses_to_opp_95"] = bool(dec and hi < 0.5)

    root_ok = (_sha(ROOT_MAIN) == progress.get("root_main_sha")
               and _sha(ROOT_DECK) == progress.get("root_deck_sha"))
    pool_check = _refs_not_in_pool()
    all_games = list(games.values())
    errors = sum(1 for g in all_games if g.get("error") and not g.get("timeout"))
    timeouts = sum(1 for g in all_games if g.get("timeout"))

    parent_h2h = {r["subject"]: r for r in by_pair.values()
                  if r["kind"] == "parent_h2h"}
    intra = {r["subject"]: r for r in by_pair.values()
             if r["kind"] == "intra_family_phase_vs_role"}

    # Honest verdict: does any candidate clearly beat its parent (wilson_low>0.5)?
    any_parent_edge = [s for s, r in parent_h2h.items() if r["beats_opp_95"]]
    # Phase-layer gameplay effect: intra-family phase-vs-role Wilson spanning 0.5
    # => phase indistinguishable from family-only floor in actual games.
    phase_indistinct = {s: (not r["beats_opp_95"] and not r["loses_to_opp_95"])
                        for s, r in intra.items()}

    out = {
        "pass": "46g", "part": "H", "local_only": True, "read_only": True,
        "no_upload": True, "production_mutated": False, "no_promotion": True,
        "games_h2h": GAMES_H2H, "games_ref": GAMES_REF,
        "n_pairings": len(by_pair), "n_games": len(all_games),
        "games_error": errors, "games_timeout": timeouts,
        "root_main_deck_unchanged": root_ok, "references_not_in_pool": pool_check,
        "pairings": list(by_pair.values()),
        "parent_h2h_edge_candidates_95": any_parent_edge,
        "phase_vs_role_indistinct_in_gameplay": phase_indistinct,
        "note": ("Win/loss/draw is RELATIVE feasibility context, NOT a Kaggle score. "
                 "References are benchmark-only opponents (never pooled/queued/ranked). "
                 "The role profile == the family-only floor at top-1, so intra-family "
                 "phase-vs-role measures the phase layer's actual gameplay effect. "
                 "Phase/role are observable heuristic labels; no exact-damage / lethal "
                 "/ KO / Boss-gust / spread / best-action claim."),
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46g_eval_panel.json").write_text(
        json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")

    def row(r):
        wr = (f"{r['win_rate_decisive']:.0%}" if r["win_rate_decisive"] is not None
              else "n/a")
        return (f"| `{r['subject']}` | {r['kind']} | `{r['opp_id']}` | "
                f"{r['wins']}/{r['losses']}/{r['draws']} | {wr} | "
                f"[{r['wilson_low']:.2f}, {r['wilson_high']:.2f}] | "
                f"{r['beats_opp_95']} | {r['errors']+r['timeouts']} |")
    md = [
        "# Pass 46G (Part H) — fast eval panel (parent-H2H + intra-family + refs)", "",
        "_LOCAL / READ-ONLY. Win/loss/draw is RELATIVE feasibility context, NOT a "
        "Kaggle score. References are benchmark-only opponents (never pooled / queued "
        "/ ranked). Phase/role are observable heuristic labels — no exact-damage / "
        "lethal / KO / Boss-gust / spread / best-action claim._", "",
        f"- **pairings:** {len(by_pair)} · **games:** {len(all_games)} "
        f"(errors={errors}, timeouts={timeouts})",
        f"- **root main.py/deck.csv unchanged:** {root_ok} · **public refs absent "
        f"from pool:** {pool_check['clean']}",
        f"- **candidates with parent edge (wilson_low>0.5):** "
        f"{any_parent_edge or 'NONE'}",
        f"- **phase-vs-role indistinct in gameplay:** {phase_indistinct}", "",
        "| subject | kind | opponent | W/L/D | win% | Wilson95 | beats opp? | err+to |",
        "|---|---|---|---|---:|---|:---:|---:|",
    ]
    order = {"parent_h2h": 0, "intra_family_phase_vs_role": 1, "reference_context": 2}
    for r in sorted(by_pair.values(), key=lambda x: (order.get(x["kind"], 9),
                                                     x["subject"], x["opp_id"])):
        md.append(row(r))
    md.append("")
    (EXP / "pass46g_eval_panel.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"ALL DONE: pairings={len(by_pair)} games={len(all_games)} "
          f"parent_edge={any_parent_edge or 'NONE'} "
          f"phase_indistinct={phase_indistinct}")
    return 0


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    build = json.loads(BUILD_JSON.read_text(encoding="utf-8"))
    cands_by_id = {c["candidate_id"]: c for c in build["candidates"]}
    smoke = json.loads(SMOKE_JSON.read_text(encoding="utf-8"))
    admit = smoke["admit_to_part_h"]
    pairings = _build_pairings(cands_by_id, admit)

    progress = _load_progress()
    keys = _game_keys(pairings)
    pending = [k for k in keys
               if f"{k[0]}::g{k[1]}" not in progress["games"]]
    if not pending:
        return _finalize(progress, pairings)

    start = time.time()
    ran = 0
    for pair_key, idx, seat, p in pending:
        if time.time() - start > INVOCATION_WALL_BUDGET and ran > 0:
            break
        subj = cands_by_id[p["subject"]]
        cand_dir = _ensure_candidate(subj["candidate_id"], subj["tarball"])
        cand_deck = load_deck(cand_dir / "deck.csv")
        opp_main, opp_deck = _resolve_opponent(p["opp_kind"], p["opp_id"], cands_by_id)
        res = _run_game(cand_dir, cand_deck, opp_main, opp_deck, seat)
        progress["games"][f"{pair_key}::g{idx}"] = res
        PROGRESS.write_text(json.dumps(progress, indent=2, default=str),
                            encoding="utf-8")
        ran += 1
        flag = "OK" if (res["completed"] and not res["error"]) else "FAIL"
        print(f"[{flag}] {pair_key}::g{idx} seat{seat} {res['seconds']}s "
              f"won={res.get('candidate_won')} draw={res.get('draw')} "
              f"err={res.get('error')}", flush=True)

    remaining = [k for k in keys if f"{k[0]}::g{k[1]}" not in progress["games"]]
    if remaining:
        print(f"TICK DONE: ran {ran}, {len(remaining)} remaining — re-invoke",
              flush=True)
        return 2
    return _finalize(progress, pairings)


if __name__ == "__main__":
    raise SystemExit(main())
