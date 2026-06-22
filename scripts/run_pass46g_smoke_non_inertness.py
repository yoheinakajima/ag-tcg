#!/usr/bin/env python3
"""PASS 46G (Part G) — smoke + non-inertness + INTERNAL distinguishability.

Two complementary, honest measurements; NO online Search, NO upload, NO events,
NO Object Storage, NO tick. LOCAL / READ-ONLY (only writes its own experiment
artifacts + a transient progress file).

A. NON-INERTNESS vs PARENT (deterministic — no game execution):
   replays each source PARENT's own ACTIVE decision frames (from the Pass-46C trace
   panel) through the BUILT candidate's actual ``agent()`` (hard-timeout subprocess)
   and reports the fraction of frames where the turn-planner picks a DIFFERENT
   option-set than the parent's native logic did, plus legality / never-raise /
   fallback / family-spread. The turn-planner is a wholly different policy, so this
   is expected to be clearly non-inert — it proves the policy is ACTIVE and SAFE,
   NOT that it is stronger.

B. INTERNAL PROFILE DISTINGUISHABILITY (deterministic, in-process diagnostic):
   on the SAME live parent frames, scores every profile (phase_aware, role_aware,
   family-only reference, balanced_control) with the repo scorer and reports the
   pairwise top-1 change-rate (phase_aware vs role_aware, and EACH vs family-only).
   This is the architect-mandated check: if the internal phase/role layer barely
   changes the top-1 pick versus the family-only floor, only ONE representative
   profile per family should be admitted to the expensive Part-H eval, and any
   parent edge must be reported as a FAMILY-WEIGHTED TRANSFER result, NOT a
   phase/role success.

C. RUNNABILITY SMOKE (real cabt games, resumable, wall-budgeted):
   each candidate plays self + its internal parent from its immutable Part-E
   tarball, in a KILLABLE child. Proves zero import/deck/runtime/timeout failures.
   Win/loss is FEASIBILITY CONTEXT ONLY — NOT a strength or Kaggle-score claim.

Phase/role are observable heuristic labels — NO exact-damage / lethal / KO /
Boss-gust / spread / best-action claim. Re-invoke until ``ALL DONE``.

Outputs: data/experiments/pass46g_smoke_non_inertness.{json,md}
Progress (transient): data/experiments/pass46g_smoke_non_inertness_progress.json
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

from ptcg_activegraph.analysis import search_oracle as O  # noqa: E402
from ptcg_activegraph.analysis import turn_planner_profiles as TP  # noqa: E402
from ptcg_activegraph.decks.deck_io import load_deck  # noqa: E402
from ptcg_activegraph.experiments.runner import run_one_game_subprocess  # noqa: E402
from ptcg_activegraph.tournament.artifacts import safe_extract_all  # noqa: E402

EXP = REPO / "data" / "experiments"
TRACES = EXP / "pass46c_traces"
BUILD_JSON = EXP / "pass46g_candidate_build.json"
CATALOG_JSON = EXP / "pass46g_profile_catalog.json"
PROGRESS = EXP / "pass46g_smoke_non_inertness_progress.json"
EXTR_OURS = REPO / "data/tournament/benchmark/_our_extracted"
CAND_EXTRACT = REPO / "data/tournament/benchmark/_cg_cand_extracted"
ROOT_MAIN = REPO / "main.py"
ROOT_DECK = REPO / "deck.csv"
CG_CHILD = str(REPO / "src/ptcg_activegraph/experiments/_pass41_cg_duel_subprocess.py")

FAMILY_ONLY_ID = "search_seeded_family_only_v1"
BUILD_PROFILE_IDS = ["phase_aware_tempo_v1", "role_aware_energy_v1"]
DISTINGUISH_PROFILE_IDS = [FAMILY_ONLY_ID, "phase_aware_tempo_v1",
                           "role_aware_energy_v1", "balanced_control_v1"]
REPRESENTATIVE_PROFILE = "phase_aware_tempo_v1"
PARENT_CHANGED_FLOOR = 0.05      # min changed-rate vs parent for "non-inert"
INTERNAL_DISTINCT_FLOOR = 0.05   # below this, admit only ONE representative/family
GAME_TIMEOUT = 70
INVOCATION_WALL_BUDGET = 95


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


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
                chosen0 = action[0] if action else None
                pfam = (TP.family_for_option(opts[chosen0])
                        if isinstance(chosen0, int) and 0 <= chosen0 < len(opts)
                        else "unknown")
                frames.append({
                    "trace": Path(tp).name, "step": i, "seat": seat,
                    "select": sel, "current": cur, "n_options": len(opts),
                    "min_count": sel.get("minCount"), "max_count": sel.get("maxCount"),
                    "parent_selected": list(action), "parent_family": pfam})
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


def _ensure_candidate(cand_id: str, tar_rel: str) -> Path:
    run = CAND_EXTRACT / cand_id
    if not (run / "main.py").is_file() or not (run / "cg" / "libcg.so").is_file():
        run.mkdir(parents=True, exist_ok=True)
        with tarfile.open(REPO / tar_rel) as t:
            safe_extract_all(t, run)
    return run


def _replay(cand_dir: Path, frames: list[dict]) -> list[dict] | None:
    with tempfile.TemporaryDirectory() as td:
        fp, op, sp = (Path(td) / "frames.json", Path(td) / "out.json",
                      Path(td) / "snip.py")
        fp.write_text(json.dumps([{"select": f["select"], "current": f["current"]}
                                  for f in frames]), encoding="utf-8")
        sp.write_text(_REPLAY_SNIPPET, encoding="utf-8")
        try:
            subprocess.run([sys.executable, str(sp), str(cand_dir), str(fp), str(op)],
                           capture_output=True, text=True, timeout=110)
        except subprocess.TimeoutExpired:
            return None
        if not op.is_file():
            return None
        return json.loads(op.read_text(encoding="utf-8"))


def _non_inertness(frames: list[dict], decisions: list[dict]) -> dict:
    n = len(frames)
    changed = exceptions = illegal = fallback = decisive = 0
    fam_hist: Counter = Counter()
    first_idx: Counter = Counter()
    for fr, dec in zip(frames, decisions):
        opts = fr["select"].get("option") or []
        nopt = len(opts)
        d = dec.get("decision")
        if dec.get("raised"):
            exceptions += 1
        legal = (isinstance(d, list) and O._is_index_action(
            d, nopt, fr["min_count"], fr["max_count"])) or (
            d == [] and fr["min_count"] in (0, None))
        if isinstance(d, list) and not legal:
            illegal += 1
        if isinstance(d, list) and set(d) != set(fr["parent_selected"]):
            changed += 1
        if isinstance(d, list) and d:
            decisive += 1
            c0 = d[0]
            if isinstance(c0, int) and 0 <= c0 < nopt:
                fam_hist[TP.family_for_option(opts[c0])] += 1
                first_idx[c0] += 1
        elif isinstance(d, list) and not d:
            fallback += 1
    changed_rate = round(changed / n, 4) if n else 0.0
    distinct_families = len(fam_hist)
    top_idx_share = (round(max(first_idx.values()) / decisive, 4)
                     if decisive else None)
    non_inert = changed_rate >= PARENT_CHANGED_FLOOR and distinct_families >= 2
    safe = exceptions == 0 and illegal == 0
    return {"n_parent_frames": n, "changed_vs_parent": changed,
            "changed_rate": changed_rate,
            "agreement_with_parent": round(1 - changed_rate, 4),
            "scorer_decisive": decisive, "fallback_used": fallback,
            "illegal_decisions": illegal, "exceptions": exceptions,
            "candidate_family_histogram": dict(fam_hist.most_common()),
            "candidate_distinct_families": distinct_families,
            "candidate_top_first_index_share": top_idx_share,
            "non_inert": non_inert, "safe": safe}


def _first_pick(select, board, profile):
    dec = TP.choose_indices(select, board, profile)
    return dec[0] if isinstance(dec, list) and dec else None


def _internal_distinguishability(frames: list[dict], profiles: dict) -> dict:
    """In-process pairwise top-1 change-rate between profiles on the SAME frames."""
    multi = [f for f in frames if f["n_options"] >= 2]
    pairs = [("phase_aware_tempo_v1", "role_aware_energy_v1"),
             ("phase_aware_tempo_v1", FAMILY_ONLY_ID),
             ("role_aware_energy_v1", FAMILY_ONLY_ID)]
    picks = {pid: [_first_pick(f["select"], f["current"], profiles[pid])
                   for f in multi] for pid in DISTINGUISH_PROFILE_IDS}
    out = {"n_multi_option_frames": len(multi), "pairs": {}}
    for a, b in pairs:
        diff = sum(1 for x, y in zip(picks[a], picks[b]) if x != y)
        out["pairs"][f"{a}__vs__{b}"] = {
            "top1_diff": diff,
            "top1_diff_rate": round(diff / len(multi), 4) if multi else 0.0}
    return out


# ---------------------------------------------------------------------------
# Runnability smoke (real cabt games).
# ---------------------------------------------------------------------------
def _game_specs(cands: list[dict]) -> list[tuple]:
    specs = []
    for c in cands:
        specs.append((c["candidate_id"], "self", 0))
        specs.append((c["candidate_id"], f"parent:{c['parent_candidate_id']}", 0))
    return specs


def _run_game(cand_dir: Path, cand_deck: list[int], opp_main: Path,
              opp_deck: list[int], seat: int) -> dict:
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
    return {"deterministic": None, "games": {},
            "root_main_sha": _sha(ROOT_MAIN), "root_deck_sha": _sha(ROOT_DECK)}


def _save_progress(progress: dict) -> None:
    PROGRESS.write_text(json.dumps(progress, indent=2, default=str),
                        encoding="utf-8")


def _compute_deterministic(cands: list[dict], profiles: dict) -> dict:
    parents = sorted({c["parent_candidate_id"] for c in cands})
    frames_by_parent = {p: _parent_frames(p) for p in parents}
    for p, fr in frames_by_parent.items():
        if not fr:
            raise SystemExit(f"no parent ACTIVE frames for {p}")

    per_candidate = {}
    for c in cands:
        cand_dir = _ensure_candidate(c["candidate_id"], c["tarball"])
        frames = frames_by_parent[c["parent_candidate_id"]]
        decisions = _replay(cand_dir, frames)
        if decisions is None or len(decisions) != len(frames):
            raise SystemExit(f"replay failed/incomplete for {c['candidate_id']}")
        ni = _non_inertness(frames, decisions)
        ni.update({"parent_candidate_id": c["parent_candidate_id"],
                   "parent_family": c["parent_family"],
                   "profile_id": c["profile_id"]})
        per_candidate[c["candidate_id"]] = ni

    internal = {}
    for fam in sorted({c["parent_family"] for c in cands}):
        src = next(c["parent_candidate_id"] for c in cands
                   if c["parent_family"] == fam)
        dist = _internal_distinguishability(frames_by_parent[src], profiles)
        phase_role = dist["pairs"]["phase_aware_tempo_v1__vs__role_aware_energy_v1"]
        p_fo = dist["pairs"][f"phase_aware_tempo_v1__vs__{FAMILY_ONLY_ID}"]
        r_fo = dist["pairs"][f"role_aware_energy_v1__vs__{FAMILY_ONLY_ID}"]
        dist["phase_role_distinguishable"] = (
            phase_role["top1_diff_rate"] >= INTERNAL_DISTINCT_FLOOR)
        dist["each_vs_family_only_distinguishable"] = (
            p_fo["top1_diff_rate"] >= INTERNAL_DISTINCT_FLOOR
            and r_fo["top1_diff_rate"] >= INTERNAL_DISTINCT_FLOOR)
        internal[fam] = dist

    # Admit recommendation: if phase/role indistinguishable in a family, admit ONE
    # representative profile only; else admit both build profiles.
    admit = []
    for c in cands:
        fam = c["parent_family"]
        if internal[fam]["phase_role_distinguishable"]:
            admit.append(c["candidate_id"])
        elif c["profile_id"] == REPRESENTATIVE_PROFILE:
            admit.append(c["candidate_id"])
    return {"per_candidate": per_candidate, "internal_distinguishability": internal,
            "admit_to_part_h": sorted(admit),
            "parent_changed_floor": PARENT_CHANGED_FLOOR,
            "internal_distinct_floor": INTERNAL_DISTINCT_FLOOR}


def _finalize(progress: dict, cands: list[dict]) -> int:
    det = progress["deterministic"]
    games = list(progress["games"].values())
    completed = [g for g in games if g["completed"] and not g["error"]]
    errors = [g for g in games if g["error"] and not g["timeout"]]
    timeouts = [g for g in games if g["timeout"]]
    id_fail = [g for g in games if g.get("import_or_deck_failure")]
    root_ok = (_sha(ROOT_MAIN) == progress.get("root_main_sha")
               and _sha(ROOT_DECK) == progress.get("root_deck_sha"))

    pc = det["per_candidate"]
    all_non_inert = all(v["non_inert"] for v in pc.values())
    all_safe = all(v["safe"] for v in pc.values())
    smoke_ok = (not id_fail and root_ok and len(errors) == 0 and len(timeouts) == 0
                and len(completed) >= len(games) and bool(games))
    all_ok = bool(smoke_ok and all_non_inert and all_safe)

    out = {
        "pass": "46g", "part": "G", "local_only": True, "read_only": True,
        "no_upload": True, "production_mutated": False,
        "n_candidates": len(cands),
        "parent_changed_floor": det["parent_changed_floor"],
        "internal_distinct_floor": det["internal_distinct_floor"],
        "non_inertness_vs_parent": pc,
        "internal_distinguishability": det["internal_distinguishability"],
        "admit_to_part_h": det["admit_to_part_h"],
        "all_non_inert_vs_parent": all_non_inert, "all_safe": all_safe,
        "smoke": {"games_total": len(games), "games_completed": len(completed),
                  "games_error": len(errors), "games_timeout": len(timeouts),
                  "import_or_deck_failures": len(id_fail),
                  "root_main_deck_unchanged": root_ok, "smoke_ok": smoke_ok,
                  "games": progress["games"]},
        "all_ok": all_ok,
        "note": ("Non-inertness + legality of an ACTIVE never-raising policy and "
                 "runnability of the tarball. Internal distinguishability shows "
                 "whether the phase/role layer changes the top-1 pick vs the "
                 "family-only floor. NONE of this is a strength / win-rate / Kaggle "
                 "claim; phase/role are observable heuristic labels (no exact-damage "
                 "/ lethal / KO / Boss-gust / spread / best-action)."),
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46g_smoke_non_inertness.json").write_text(
        json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        "# Pass 46G (Part G) — smoke + non-inertness + internal distinguishability",
        "", "_LOCAL / READ-ONLY. Non-inertness/legality + tarball runnability + the "
        "phase/role-vs-family-only top-1 change-rate. NOT a strength / win-rate / "
        "Kaggle claim. Phase/role are observable heuristic labels — no exact-damage "
        "/ lethal / KO / Boss-gust / spread / best-action claim._", "",
        f"- **ALL OK:** **{all_ok}** (smoke_ok={smoke_ok}, "
        f"non_inert={all_non_inert}, safe={all_safe})",
        f"- **smoke games:** {len(completed)}/{len(games)} completed, "
        f"errors={len(errors)}, timeouts={len(timeouts)}, "
        f"import/deck failures={len(id_fail)}, root unchanged={root_ok}",
        f"- **admit to Part H:** {', '.join(det['admit_to_part_h'])}", "",
        "## A. Non-inertness vs parent (deterministic replay)",
        "| candidate | family | profile | parent frames | changed-rate | "
        "distinct fams | fallback | illegal | exc | non-inert | safe |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|:---:|:---:|",
    ]
    for cid, v in pc.items():
        md.append(
            f"| `{cid}` | {v['parent_family']} | `{v['profile_id']}` | "
            f"{v['n_parent_frames']} | {v['changed_rate']:.0%} | "
            f"{v['candidate_distinct_families']} | {v['fallback_used']} | "
            f"{v['illegal_decisions']} | {v['exceptions']} | {v['non_inert']} | "
            f"{v['safe']} |")
    md += ["", "## B. Internal profile distinguishability (in-process, same frames)",
           "_top-1 change-rate between profiles. ~0 => the phase/role layer collapses "
           "to the family-only floor; any parent edge is a FAMILY-WEIGHTED TRANSFER "
           "result, NOT a phase/role success._", "",
           "| family | frames | phase_vs_role | phase_vs_family_only | "
           "role_vs_family_only | phase/role distinct? |",
           "|---|---:|---:|---:|---:|:---:|"]
    for fam, dist in det["internal_distinguishability"].items():
        pr = dist["pairs"]["phase_aware_tempo_v1__vs__role_aware_energy_v1"]
        pf = dist["pairs"][f"phase_aware_tempo_v1__vs__{FAMILY_ONLY_ID}"]
        rf = dist["pairs"][f"role_aware_energy_v1__vs__{FAMILY_ONLY_ID}"]
        md.append(
            f"| {fam} | {dist['n_multi_option_frames']} | "
            f"{pr['top1_diff_rate']:.0%} | {pf['top1_diff_rate']:.0%} | "
            f"{rf['top1_diff_rate']:.0%} | {dist['phase_role_distinguishable']} |")
    md += ["", "## C. Runnability smoke (real cabt games — feasibility context only)",
           "| candidate::opponent::seat | completed | won | draw | steps | secs | "
           "err | timeout |", "|---|:---:|:---:|:---:|---:|---:|---|:---:|"]
    for key, g in progress["games"].items():
        md.append(
            f"| `{key}` | {g['completed']} | {g.get('candidate_won')} | "
            f"{g.get('draw')} | {g.get('steps')} | {g['seconds']} | "
            f"{g.get('error')} | {g['timeout']} |")
    (EXP / "pass46g_smoke_non_inertness.md").write_text("\n".join(md) + "\n",
                                                        encoding="utf-8")
    print(f"ALL DONE: all_ok={all_ok} smoke_ok={smoke_ok} "
          f"non_inert={all_non_inert} safe={all_safe} "
          f"admit={det['admit_to_part_h']}")
    return 0 if all_ok else 1


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    build = json.loads(BUILD_JSON.read_text(encoding="utf-8"))
    cands = build["candidates"]
    catalog = json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
    profiles = catalog["profiles"]

    progress = _load_progress()
    if progress.get("deterministic") is None:
        progress["deterministic"] = _compute_deterministic(cands, profiles)
        _save_progress(progress)
        print("DETERMINISTIC DONE: "
              f"admit={progress['deterministic']['admit_to_part_h']}", flush=True)

    specs = _game_specs(cands)
    pending = [s for s in specs if f"{s[0]}::{s[1]}::seat{s[2]}" not in progress["games"]]
    if not pending:
        return _finalize(progress, cands)

    cand_by_id = {c["candidate_id"]: c for c in cands}
    start = time.time()
    ran = 0
    for cid, opp_key, seat in pending:
        if time.time() - start > INVOCATION_WALL_BUDGET and ran > 0:
            break
        c = cand_by_id[cid]
        cand_dir = _ensure_candidate(cid, c["tarball"])
        cand_deck = load_deck(cand_dir / "deck.csv")
        if opp_key == "self":
            opp_main, opp_deck = cand_dir / "main.py", cand_deck
        else:
            pid = opp_key.split(":", 1)[1]
            opp_main = EXTR_OURS / pid / "main.py"
            opp_deck = load_deck(EXTR_OURS / pid / "deck.csv")
        res = _run_game(cand_dir, cand_deck, opp_main, opp_deck, seat)
        progress["games"][f"{cid}::{opp_key}::seat{seat}"] = res
        _save_progress(progress)
        ran += 1
        flag = "OK" if (res["completed"] and not res["error"]) else "FAIL"
        print(f"[{flag}] {cid}::{opp_key}::seat{seat} {res['seconds']}s "
              f"steps={res.get('steps')} won={res.get('candidate_won')} "
              f"err={res.get('error')}", flush=True)

    remaining = [s for s in specs
                 if f"{s[0]}::{s[1]}::seat{s[2]}" not in progress["games"]]
    if remaining:
        print(f"TICK DONE: ran {ran}, {len(remaining)} remaining — re-invoke",
              flush=True)
        return 2
    return _finalize(progress, cands)


if __name__ == "__main__":
    raise SystemExit(main())
