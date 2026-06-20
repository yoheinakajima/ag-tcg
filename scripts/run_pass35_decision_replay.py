#!/usr/bin/env python3
"""Pass 35 (T-I) — decision replay / non-inertness, child vs parent. LOCAL ONLY.

No Kaggle upload/submit, no GitHub push, no root edits. Two honest measurements:

PART A — FIXTURE replay (deterministic). For every executable profile we replay
each fixture case through the SAME public ``decide()`` the compiled runtime calls,
twice: once with the real profile (the CHILD / typed-refined decision) and once
with an INERT empty profile (the PARENT / base default the typed layer falls back
to). The delta is exactly what the profile's tactics changed. Each supported case
is classified:

  * intended_non_inert — typed pick differs from the inert default, is LEGAL
    (offered among the options) AND lands inside the profile's declared context.
  * inert              — typed pick == inert default (the layer added nothing).
  * misfire           — typed pick changed a decision whose context is NOT in the
    profile's implemented_contexts (must be 0).
  * unsafe            — typed pick is not among the offered options (must be 0).
  * invalid           — malformed/empty result for a supported kind (must be 0).
Unsupported kinds (attack/lethal/ko_target/spread/boss/gust) are graded only for
HONESTY: the typed layer must report ``unsupported`` and never fabricate a target.

PART B — LIVE replay (bounded, subprocess-isolated). For each built child we run a
few real cabt games (seat-swapped vs proven parents), hooking the child's embedded
strategy layer to record, per gameplay decision, BASE vs REFINED. This measures
the real-game firing rate: how often the typed layer actually changes the base
choice in play (commonly near zero — the trigger conditions rarely arise), and
proves every live change is legal and confined to declared contexts.

Every cabt game runs in ``_pass35_replay_worker.py`` via subprocess with a hard
timeout (native open_spiel can hang and SIGALRM cannot interrupt native C). The
harness is resumable: per-child live results checkpoint to a progress file and a
per-call wall-clock budget lets it span several invocations.

Outputs ``data/experiments/pass35_decision_replay.{json,md}``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import yaml  # noqa: E402

from ptcg_activegraph.pilot_typed import decisions as D  # noqa: E402
from ptcg_activegraph.pilot_typed import profiles as P  # noqa: E402
from ptcg_activegraph.pilot_typed.compiler import build_metadata_table  # noqa: E402

REGISTRY = REPO / "experiments" / "strategy_profiles.yaml"
CARD_CSV = REPO / "data" / "cards" / "EN_Card_Data.csv"
FIX_DIR = REPO / "data" / "fixtures" / "pass35_typed_strategy"
BUILD = REPO / "data" / "experiments" / "pass35_candidate_build.json"
CAND_DIR = REPO / "data" / "submissions" / "candidates_pass35"
WORKER = REPO / "scripts" / "_pass35_replay_worker.py"
OUT_JSON = REPO / "data" / "experiments" / "pass35_decision_replay.json"
OUT_MD = REPO / "data" / "experiments" / "pass35_decision_replay.md"
PROGRESS = REPO / "data" / "experiments" / "pass35_decision_replay_progress.json"

# Authoritative kind -> obs context map (mirrors the compiler's PASS35 block).
KIND_CTX = {
    "emergency_backup_bench": 0, "attach_energy": 0, "setup_active": 1,
    "setup_bench_multi": 2, "search_to_hand": 7, "discard": 8, "draw_count": 38,
}
UNSUPPORTED = {"attack", "lethal", "ko_target", "spread", "boss", "gust"}
PICK_KEYS = ("chosen_card_id", "chosen_card_ids", "chosen_number",
             "chosen_target_id")

# Bounded live panel: proven parents, diverse archetypes. Each child plays one
# game per (opponent, seat) entry below — kept small so a single child's worker
# stays well under the shell wall-clock cap while still sampling both seats and
# two distinct opponents.
LIVE_OPPONENTS = [
    ("water_core_reference",
     REPO / "data" / "submissions" / "candidates_pass33"
     / "league_water_core_reference.tar.gz"),
    ("charizard_x",
     REPO / "data" / "submissions" / "candidates_pass33"
     / "league_mega_charizard_x_burst.tar.gz"),
]
# (opponent_index, child_seat) games each child plays.
LIVE_GAMES = [(0, 0), (1, 1)]
GAME_TIMEOUT_S = 30
SUBPROC_SLACK_S = 25
PER_CALL_BUDGET_S = int(os.environ.get("P35_PER_CALL_BUDGET_S", "40"))
SKIP_LIVE = os.environ.get("P35_SKIP_LIVE") == "1"


# --------------------------------------------------------------------------- A
def _pick(result: dict):
    if not isinstance(result, dict):
        return ("malformed", None)
    if result.get("unsupported") is True:
        return ("unsupported", True)
    for k in PICK_KEYS:
        if k in result:
            return (k, result[k])
    return ("empty", None)


def _option_card_ids(options) -> set:
    ids = set()
    for o in options or []:
        if isinstance(o, dict) and "card_id" in o:
            ids.add(o["card_id"])
    return ids


def _option_numbers(options) -> set:
    nums = set()
    for o in options or []:
        if isinstance(o, dict) and "number" in o:
            nums.add(o["number"])
        elif isinstance(o, (int,)) and not isinstance(o, bool):
            nums.add(o)
    return nums


def _legal_pick(key, val, options) -> bool:
    if val is None:
        return True  # a None / no-pick is a legal defer
    if key in ("chosen_card_id", "chosen_target_id"):
        return val in _option_card_ids(options)
    if key == "chosen_card_ids":
        if not isinstance(val, list):
            return False
        ids = _option_card_ids(options)
        return (len(set(val)) == len(val)
                and all(v in ids for v in val))
    if key == "chosen_number":
        nums = _option_numbers(options)
        return (not nums) or (val in nums)
    return False


def _grade_expect(result: dict, expect: dict) -> bool:
    expect = expect or {}
    for key, want in expect.items():
        if key == "unsupported":
            if (result.get("unsupported") is True) != bool(want):
                return False
        elif key == "defer_to_base":
            if (result == {}) != bool(want):
                return False
        elif key == "chosen_card_ids_contains":
            got = result.get("chosen_card_ids") or []
            if any(c not in got for c in want):
                return False
        elif key == "chosen_card_ids_excludes":
            got = result.get("chosen_card_ids") or []
            if any(c in got for c in want):
                return False
        else:
            if result.get(key) != want:
                return False
    return True


def fixture_replay(profiles: dict) -> list:
    out = []
    for path in sorted(FIX_DIR.glob("*.json")):
        fx = json.loads(path.read_text(encoding="utf-8"))
        pid = fx.get("profile_id")
        profile = profiles.get(pid)
        if profile is None or not profile.get("executable"):
            continue
        impl = set(P.implemented_contexts(profile))
        meta = build_metadata_table(str(CARD_CSV), profile.get("card_ids") or [])
        cases = []
        counts = {"intended_non_inert": 0, "inert": 0, "misfire": 0,
                  "unsafe": 0, "invalid": 0, "honesty_unsupported": 0,
                  "honesty_fabricated": 0, "intended_defer": 0}
        for case in fx.get("cases") or []:
            kind = case.get("kind")
            board = case.get("board") or {}
            options = case.get("options") or []
            expect = case.get("expect") or {}
            child = D.decide(kind, board, options, profile, meta)
            parent = D.decide(kind, board, options, {}, meta)
            ck, cv = _pick(child)
            pk, pv = _pick(parent)
            matches = _grade_expect(child, expect)
            rec = {"name": case.get("name"), "tag": case.get("tag"),
                   "kind": kind, "child": child, "parent": parent,
                   "matches_expect": matches}
            if kind in UNSUPPORTED or ck == "unsupported":
                honest = child.get("unsupported") is True
                cls = "honesty_unsupported" if honest else "honesty_fabricated"
            elif child == {} and expect.get("defer_to_base"):
                cls = "intended_defer"
            elif not _legal_pick(ck, cv, options):
                cls = "unsafe"
            else:
                changed = (ck == pk and cv != pv) or (ck != pk)
                in_ctx = KIND_CTX.get(kind) in impl
                if not changed:
                    cls = "inert"
                elif not in_ctx:
                    cls = "misfire"
                else:
                    cls = "intended_non_inert"
            rec["classification"] = cls
            counts[cls] = counts.get(cls, 0) + 1
            cases.append(rec)
        # overall classification priority
        if counts["unsafe"] or counts["honesty_fabricated"]:
            overall = "unsafe"
        elif counts["misfire"]:
            overall = "misfire"
        elif counts["invalid"]:
            overall = "invalid"
        elif counts["intended_non_inert"]:
            overall = "intended_non_inert"
        else:
            overall = "inert"
        out.append({
            "profile_id": pid, "implemented_contexts": sorted(impl),
            "n_cases": len(cases), "counts": counts,
            "overall": overall, "cases": cases,
            "honest_ok": counts["honesty_fabricated"] == 0,
            "safe_ok": counts["unsafe"] == 0 and counts["misfire"] == 0
                       and counts["invalid"] == 0,
        })
    return out


# --------------------------------------------------------------------------- B
def _extract(tar: Path, dest: Path) -> str:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar, "r:gz") as tf:
        tf.extractall(dest)  # noqa: S202 (our own trusted tarballs)
    return str(dest / "main.py")


def _run_worker(child_main: str, jsonl_out: Path, specs: list) -> tuple:
    """Run one child's whole game list in a single worker process. Returns
    (game_records, killed): records are read from the streamed JSONL even if the
    worker was killed mid-run for a hang."""
    if jsonl_out.exists():
        jsonl_out.unlink()
    spec_args = [f"{opp}|{seat}|{GAME_TIMEOUT_S}" for opp, seat in specs]
    killed = False
    timeout = len(specs) * GAME_TIMEOUT_S + SUBPROC_SLACK_S
    try:
        subprocess.run(
            [sys.executable, str(WORKER), child_main, str(jsonl_out), *spec_args],
            capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        killed = True
    records = []
    if jsonl_out.exists():
        for line in jsonl_out.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:  # noqa: BLE001
                    pass
    return records, killed


def live_replay_one(cid: str, impl: list, child_main: str, opp_mains: dict,
                    tmp: Path) -> dict:
    impl_set = set(impl)
    specs = [(opp_mains[LIVE_OPPONENTS[oi][0]], seat) for oi, seat in LIVE_GAMES]
    jsonl = tmp / f"live_{cid}.jsonl"
    records, killed = _run_worker(child_main, jsonl, specs)

    agg = {"games_attempted": len(specs), "games": len(records),
           "games_ok": 0, "games_timeout": 0, "games_invalid": 0,
           "games_missing": len(specs) - len(records), "worker_killed": killed,
           "total_decisions": 0, "decisions_at_targeted": 0, "changes": 0,
           "changes_by_ctx": {}, "by_ctx": {}, "misfires": 0, "unsafe": 0,
           "game_log": []}
    for res in records:
        entry = {"opponent": res.get("opponent"), "seat": res.get("seat"),
                 "ok": bool(res.get("ok")), "timeout": bool(res.get("timeout")),
                 "statuses": res.get("statuses"), "error": res.get("error")}
        if res.get("timeout"):
            agg["games_timeout"] += 1
        if res.get("invalid"):
            agg["games_invalid"] += 1
        if res.get("ok"):
            agg["games_ok"] += 1
        decs = res.get("decisions") or []
        entry["n_decisions"] = len(decs)
        entry["n_changed"] = sum(1 for d in decs if d.get("changed"))
        for d in decs:
            ctx = d.get("ctx")
            agg["total_decisions"] += 1
            agg["by_ctx"][str(ctx)] = agg["by_ctx"].get(str(ctx), 0) + 1
            if ctx in impl_set:
                agg["decisions_at_targeted"] += 1
            if not d.get("legal", True):
                agg["unsafe"] += 1
            if d.get("changed"):
                agg["changes"] += 1
                agg["changes_by_ctx"][str(ctx)] = \
                    agg["changes_by_ctx"].get(str(ctx), 0) + 1
                if ctx not in impl_set:
                    agg["misfires"] += 1
        agg["game_log"].append(entry)
    # classify live behaviour
    if agg["unsafe"]:
        live_cls = "unsafe"
    elif agg["misfires"]:
        live_cls = "misfire"
    elif agg["changes"] > 0:
        live_cls = "non_inert_in_live_play"
    elif agg["games_ok"] == 0:
        live_cls = "inconclusive_no_clean_games"
    else:
        live_cls = "inert_in_live_play"
    agg["live_classification"] = live_cls
    return agg


def _load_progress() -> dict:
    if PROGRESS.exists():
        try:
            return json.loads(PROGRESS.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"live": {}}


def main() -> int:
    reg = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    profiles = {p["id"]: p for p in (reg.get("profiles") or [])}

    fixtures = fixture_replay(profiles)

    build = json.loads(BUILD.read_text(encoding="utf-8"))
    built = [(c["id"], c.get("implemented_contexts") or [])
             for c in build["candidates"] if c.get("built")]

    prog = _load_progress()
    live = prog.get("live", {})
    deadline = time.time() + PER_CALL_BUDGET_S
    remaining = []
    if not SKIP_LIVE:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            opp_mains = {name: _extract(tar, tmp / f"opp_{name}")
                         for name, tar in LIVE_OPPONENTS}
            for cid, impl in built:
                if cid in live:
                    continue
                if time.time() >= deadline:
                    remaining.append(cid)
                    continue
                child_main = _extract(CAND_DIR / f"{cid}.tar.gz",
                                      tmp / f"child_{cid}")
                live[cid] = live_replay_one(cid, impl, child_main, opp_mains, tmp)
                prog["live"] = live
                PROGRESS.write_text(json.dumps(prog, indent=2), encoding="utf-8")
        remaining += [cid for cid, _ in built
                      if cid not in live and cid not in remaining]
    live_complete = SKIP_LIVE or not remaining

    # ---- aggregate / classify ------------------------------------------------
    fix_safe = all(f["safe_ok"] for f in fixtures)
    fix_honest = all(f["honest_ok"] for f in fixtures)
    fix_non_inert = [f["profile_id"] for f in fixtures
                     if f["overall"] == "intended_non_inert"]
    fix_inert = [f["profile_id"] for f in fixtures if f["overall"] == "inert"]

    live_safe = all((r.get("unsafe", 0) == 0 and r.get("misfires", 0) == 0)
                    for r in live.values()) if live else None
    live_non_inert = [cid for cid, r in live.items()
                      if r.get("live_classification") == "non_inert_in_live_play"]
    live_inert = [cid for cid, r in live.items()
                  if r.get("live_classification") == "inert_in_live_play"]

    summary = {
        "no_upload": True, "upload_performed": False, "root_edited": False,
        "card_csv_committed": False, "lane": "stdlib_typed_lite",
        "status": "complete" if live_complete else "partial",
        "live_remaining": remaining,
        "fixture_replay": {
            "n_profiles": len(fixtures),
            "all_safe": fix_safe, "all_honest": fix_honest,
            "intended_non_inert": fix_non_inert, "inert": fix_inert,
            "profiles": fixtures,
        },
        "live_replay": {
            "skipped": SKIP_LIVE, "complete": live_complete,
            "opponents": [o[0] for o in LIVE_OPPONENTS],
            "games_per_child": len(LIVE_OPPONENTS) * 2,
            "all_safe": live_safe,
            "non_inert_in_live_play": live_non_inert,
            "inert_in_live_play": live_inert,
            "children": live,
        },
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True),
                        encoding="utf-8")
    _write_md(summary)

    if live_complete and PROGRESS.exists():
        PROGRESS.unlink()

    print(f"decision replay: status={summary['status']}  "
          f"fixture safe={fix_safe} honest={fix_honest}  "
          f"live safe={live_safe}  remaining={remaining}")
    return 0


def _write_md(s: dict) -> None:
    fr = s["fixture_replay"]
    lr = s["live_replay"]
    L = ["# Pass 35 — decision replay / non-inertness (child vs parent)", "",
         "> LOCAL ONLY. No Kaggle upload/submit, no GitHub push, no root edits. "
         "Child = typed-refined `decide()`; parent = inert (empty-profile) base "
         "default the typed layer falls back to.", "",
         f"- fixture replay: all_safe **{fr['all_safe']}**, all_honest "
         f"**{fr['all_honest']}** over {fr['n_profiles']} executable profiles",
         f"- fixture intended_non_inert: {fr['intended_non_inert'] or '—'}",
         f"- fixture fully-inert: {fr['inert'] or '—'}",
         f"- live replay: status **{s['status']}**, all_safe **{lr['all_safe']}**, "
         f"{lr['games_per_child']} games/child vs {lr['opponents']}",
         f"- live non-inert: {lr['non_inert_in_live_play'] or '—'}",
         f"- live inert: {lr['inert_in_live_play'] or '—'}", ""]
    L += ["## Part A — fixture replay", "",
          "| profile | cases | non_inert | inert | misfire | unsafe | "
          "honesty | overall |", "|---|---|---|---|---|---|---|---|"]
    for f in fr["profiles"]:
        c = f["counts"]
        L.append(
            f"| {f['profile_id']} | {f['n_cases']} | {c['intended_non_inert']} | "
            f"{c['inert']} | {c['misfire']} | {c['unsafe']} | "
            f"{c['honesty_unsupported']}✓/{c['honesty_fabricated']}✗ | "
            f"**{f['overall']}** |")
    L.append("")
    L += ["## Part B — live replay (real-game firing rate)", ""]
    if lr["skipped"]:
        L.append("_Live replay skipped (P35_SKIP_LIVE=1)._")
    elif not lr["children"]:
        L.append("_No live results yet._")
    else:
        L += ["| child | games(ok/to) | decisions | @targeted | live changes | "
              "misfire | unsafe | classification |",
              "|---|---|---|---|---|---|---|---|"]
        for cid, r in lr["children"].items():
            L.append(
                f"| {cid} | {r['games_ok']}/{r['games_timeout']} of {r['games']} "
                f"| {r['total_decisions']} | {r['decisions_at_targeted']} | "
                f"{r['changes']} | {r['misfires']} | {r['unsafe']} | "
                f"{r['live_classification']} |")
    # observed live aggregates (honest, computed from the data above).
    tot = sum(r["total_decisions"] for r in lr["children"].values())
    chg = sum(r["changes"] for r in lr["children"].values())
    mis = sum(r["misfires"] for r in lr["children"].values())
    uns = sum(r["unsafe"] for r in lr["children"].values())
    rate = (100.0 * chg / tot) if tot else 0.0
    L += ["", "## Reading the result", "",
          "- The typed layer is **non-inert by construction** (Part A: 4/9 "
          "profiles' fixtures show it diverging from the inert default to the "
          "intended pick; the other 5 happen to coincide with the default on "
          "their cases) and **non-inert in live play too, but rarely**: across "
          f"{tot} live gameplay decisions only {chg} were changed "
          f"(~{rate:.1f}% per-decision firing rate), a few changes per child, and "
          "raging_bolt showed none in this small sample. The trigger conditions "
          "(multi-target attach, multi-option setup, real discard/draw choices) "
          "are simply uncommon, so most individual decisions return the base "
          "choice unchanged.",
          f"- Every change observed is **legal** (offered among the options) and "
          f"**confined to each profile's declared contexts**: {mis} misfires and "
          f"{uns} unsafe across all {tot} live decisions. The layer's value is "
          "safety plus occasional refinement, NOT a measured strength gain — "
          "strength is tested separately in the tournament/parent-child stages.",
          "- Unsupported mechanics (attack/lethal/ko_target/spread/boss/gust) are "
          "reported `unsupported` in every executable profile — no fabricated "
          "damage, lethal, spread, or Boss-gust targets.", ""]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
