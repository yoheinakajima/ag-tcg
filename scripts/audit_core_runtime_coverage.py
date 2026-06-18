#!/usr/bin/env python3
"""Pass 15 — fixture-to-live runtime coverage audit.

The reduced-model core-competency gate proves the *lab decision layer*. It does
NOT prove that the compiled candidate actually applies that layer at the matching
*live* cabt context. This audit makes that gap explicit and honest.

For each core-competency fixture it records:

  * fixture id, decision kind, hard/advisory,
  * the reduced-model gate result (via the candidate's embedded
    ``core_pilot_decide``),
  * the live cabt ``select.context`` integer(s) the fixture's kind corresponds
    to (only ``7=search_draw`` and ``8=discard`` are reliably named today),
  * whether the compiled runtime actually intercepts that live context,
  * the risk of wiring it, and a recommended action.

It also EMPIRICALLY records which ``select.context`` integers actually occur in
live cabt self-play (with the candidate piloting both seats) and what option
shapes accompany them, so the safe/unsafe classification is evidence-grounded,
not guessed. If cabt is unavailable it still writes the static audit and records
that empirical evidence could not be gathered.

Outputs:
  data/experiments/pass15_core_runtime_coverage.json
  data/experiments/pass15_core_runtime_coverage.md

LOCAL ONLY. No upload, no submission, no GitHub push.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tarfile
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from ptcg_activegraph.pilot import fixtures as FX  # noqa: E402

DEFAULT_CAND = (REPO / "data" / "submissions" / "candidates_pass14"
                / "core_pilot_water_v1.tar.gz")
FIXTURES_DIR = REPO / "data" / "fixtures" / "core_competency"
OUT_JSON = REPO / "data" / "experiments" / "pass15_core_runtime_coverage.json"
OUT_MD = REPO / "data" / "experiments" / "pass15_core_runtime_coverage.md"

# Reliably-named cabt select.context integers (src/ptcg_activegraph/pilot/state.py
# _CONTEXT_NAMES + docs/CABT_SCHEMA_NOTES.md). Everything else is unconfirmed.
NAMED_CONTEXTS = {7: "search_draw", 8: "discard"}

# Decision kind -> how the live context is identified, plus today's wiring risk.
# context=None means "no dedicated confirmed context integer; the phase is only
# distinguishable by option shape, which is less reliable".
KIND_LIVE_MAP = {
    "setup_active": {"live_context": None, "live_signal": "setup phase; place-basic options (type 3) with empty active",
                     "risk": "medium"},
    "setup_bench": {"live_context": None, "live_signal": "setup phase; place-basic options (type 3) onto bench",
                    "risk": "medium"},
    "promote_after_ko": {"live_context": None, "live_signal": "choose-new-active after KO; place/select-basic options",
                         "risk": "medium"},
    "attach_energy": {"live_context": None, "live_signal": "Main phase in-play action (type 8) attaching energy",
                      "risk": "high"},
    "attach_tool": {"live_context": None, "live_signal": "Main phase in-play action (type 8) attaching a tool",
                    "risk": "high"},
    "evolve": {"live_context": None, "live_signal": "Main phase evolve action",
               "risk": "high"},
    "discard": {"live_context": 8, "live_signal": "context==8 (pay costs / discard)",
                "risk": "low"},
    "search_to_hand": {"live_context": 7, "live_signal": "context==7 (search/draw to hand)",
                       "risk": "low"},
    "main_action": {"live_context": None, "live_signal": "broad Main-phase action ranking",
                    "risk": "very_high"},
}


def _import_candidate(main_path: Path):
    old_cwd = os.getcwd()
    added = str(main_path.parent)
    sys.path.insert(0, added)
    os.chdir(main_path.parent)
    try:
        spec = importlib.util.spec_from_file_location("cand_audit", main_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["cand_audit"] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod
    finally:
        os.chdir(old_cwd)
        if added in sys.path:
            sys.path.remove(added)


def _runtime_intercepts(mod, live_context) -> bool:
    """True if the candidate's runtime actually refines this live context.

    The compiled runtime hook is ``_cp_embedded``; it only refines when
    ``select.context`` is one of the contexts it explicitly handles. We probe the
    candidate's declared coverage set if present, else fall back to {7}."""
    covered = getattr(mod, "_CP_RUNTIME_CONTEXTS", None)
    if isinstance(covered, (list, tuple, set)):
        covered = set(covered)
    else:
        covered = {7}  # v1 default: only the ToHand-search context
    return live_context in covered


def _empirical_contexts(main_path: Path, games: int):
    """Run cabt self-play and record context -> option-shape signatures."""
    try:
        from kaggle_environments import make  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"kaggle_environments unavailable: {exc!r}",
                "contexts": {}, "games": 0}

    records: dict = defaultdict(lambda: {"count": 0, "type_sets": set(),
                                         "min_counts": set(), "max_counts": set(),
                                         "has_deck": 0, "has_inplay": 0})

    # Compile+exec the candidate (like kaggle) and wrap its last callable so we
    # can observe every select.context it is asked to decide.
    src = main_path.read_text(encoding="utf-8")
    env_ns: dict = {"__file__": str(main_path), "__name__": "cand_live"}
    old_cwd = os.getcwd()
    os.chdir(main_path.parent)
    try:
        exec(compile(src, str(main_path), "exec"), env_ns)  # noqa: S102
        callables = [v for v in env_ns.values() if callable(v)]
        base_agent = callables[-1]

        def recording_agent(obs, *a, **k):
            try:
                sel = obs.get("select") if isinstance(obs, dict) else None
                if isinstance(sel, dict):
                    ctx = sel.get("context")
                    opts = sel.get("option") or sel.get("options") or []
                    if isinstance(opts, list) and opts:
                        rec = records[ctx]
                        rec["count"] += 1
                        tset = tuple(sorted({o.get("type") for o in opts
                                             if isinstance(o, dict)
                                             and isinstance(o.get("type"), int)}))
                        rec["type_sets"].add(tset)
                        if isinstance(sel.get("minCount"), int):
                            rec["min_counts"].add(sel.get("minCount"))
                        if isinstance(sel.get("maxCount"), int):
                            rec["max_counts"].add(sel.get("maxCount"))
                        if isinstance(sel.get("deck"), list):
                            rec["has_deck"] += 1
                        if any(isinstance(o, dict) and "inPlayArea" in o for o in opts):
                            rec["has_inplay"] += 1
            except Exception:  # noqa: BLE001
                pass
            return base_agent(obs)

        n = 0
        for cfg in ({}, {"actTimeout": 30}):
            try:
                game_env = make("cabt", configuration=cfg)
                break
            except Exception:
                game_env = None
        if game_env is None:
            return {"available": False, "reason": "make('cabt') failed",
                    "contexts": {}, "games": 0}
        for _ in range(max(1, games)):
            game_env.run([recording_agent, recording_agent])
            n += 1
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"live run error: {exc!r}",
                "contexts": dict(_serialize_records(records)), "games": 0}
    finally:
        os.chdir(old_cwd)

    return {"available": True, "reason": "", "games": n,
            "contexts": _serialize_records(records)}


def _serialize_records(records) -> dict:
    out = {}
    for ctx, rec in records.items():
        out[str(ctx)] = {
            "context": ctx,
            "name": NAMED_CONTEXTS.get(ctx, "unknown"),
            "count": rec["count"],
            "option_type_sets": sorted([list(t) for t in rec["type_sets"]]),
            "min_counts": sorted(rec["min_counts"]),
            "max_counts": sorted(rec["max_counts"]),
            "saw_deck_in_select": rec["has_deck"],
            "saw_inplay_targets": rec["has_inplay"],
        }
    return out


def audit(candidate: Path, games: int) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        with tarfile.open(candidate, "r:gz") as tar:
            tar.extractall(tmp_dir)  # noqa: S202
        main_path = tmp_dir / "main.py"
        mod = _import_candidate(main_path)
        decide_fn = lambda kind, board, opts: mod.core_pilot_decide(kind, board, opts)
        fxs = FX.load_fixtures(FIXTURES_DIR)
        gate = FX.grade_all(fxs, decide_fn, has_layer=True)
        gate_by_id = {r["id"]: r for r in gate["rows"]}

        rows = []
        for fx in fxs:
            kind = fx.get("kind")
            m = KIND_LIVE_MAP.get(kind, {"live_context": None,
                                         "live_signal": "unknown", "risk": "high"})
            live_ctx = m["live_context"]
            intercepts = (live_ctx is not None
                          and _runtime_intercepts(mod, live_ctx))
            gr = gate_by_id.get(fx["id"], {})
            if live_ctx is None:
                wired = "lab_only (no confirmed live context integer)"
            elif intercepts:
                wired = f"WIRED (live context=={live_ctx})"
            else:
                wired = f"not_wired (live context=={live_ctx} identifiable but runtime defers)"
            rows.append({
                "id": fx["id"],
                "kind": kind,
                "hard": bool(fx.get("hard", True)),
                "reduced_model_gate": gr.get("status"),
                "live_context": live_ctx,
                "live_context_name": NAMED_CONTEXTS.get(live_ctx),
                "live_signal": m["live_signal"],
                "runtime_intercepts": intercepts,
                "coverage": wired,
                "wiring_risk": m["risk"],
            })

        empirical = _empirical_contexts(main_path, games)

    wired_ct = sum(1 for r in rows if r["runtime_intercepts"])
    lab_only = sum(1 for r in rows if r["live_context"] is None)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate": candidate.name,
        "fixtures_total": len(rows),
        "reduced_model_hard_failures": gate["hard_failures"],
        "runtime_wired_fixtures": wired_ct,
        "lab_only_fixtures": lab_only,
        "named_contexts": NAMED_CONTEXTS,
        "rows": rows,
        "empirical": empirical,
    }


def write_md(doc: dict) -> None:
    L = []
    L.append("# Pass 15 — Core Runtime Coverage Audit\n")
    L.append(f"- generated: {doc['generated_at']}")
    L.append(f"- candidate: `{doc['candidate']}`")
    L.append(f"- fixtures: {doc['fixtures_total']}  "
             f"reduced-model hard failures: {doc['reduced_model_hard_failures']}")
    L.append(f"- runtime-wired fixtures: **{doc['runtime_wired_fixtures']}**  "
             f"lab-only fixtures: **{doc['lab_only_fixtures']}**\n")
    L.append("> The reduced-model gate proves the lab decision layer. A fixture is "
             "**runtime-wired** only if the compiled candidate actually intercepts "
             "the matching live cabt context. Today only context 7 (search) and 8 "
             "(discard) are reliably named.\n")
    L.append("| id | kind | hard | reduced-gate | live ctx | runtime | risk |")
    L.append("|---|---|---|---|---|---|---|")
    for r in doc["rows"]:
        L.append(f"| {r['id']} | {r['kind']} | {r['hard']} | "
                 f"{r['reduced_model_gate']} | "
                 f"{r['live_context'] if r['live_context'] is not None else '—'} | "
                 f"{r['coverage']} | {r['wiring_risk']} |")
    emp = doc["empirical"]
    L.append("\n## Empirical live context distribution\n")
    if not emp.get("available"):
        L.append(f"_Empirical evidence unavailable: {emp.get('reason')}_\n")
    else:
        L.append(f"Recorded over {emp['games']} live cabt self-play game(s).\n")
        L.append("| context | name | decisions | option type-sets | minCounts | maxCounts | deck-in-select | inplay-targets |")
        L.append("|---|---|---|---|---|---|---|---|")
        for _, c in sorted(emp["contexts"].items(),
                           key=lambda kv: kv[1]["count"], reverse=True):
            L.append(f"| {c['context']} | {c['name']} | {c['count']} | "
                     f"{c['option_type_sets']} | {c['min_counts']} | "
                     f"{c['max_counts']} | {c['saw_deck_in_select']} | "
                     f"{c['saw_inplay_targets']} |")
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate", default=str(DEFAULT_CAND))
    ap.add_argument("--games", type=int, default=1,
                    help="live cabt self-play games for empirical context recording")
    args = ap.parse_args()
    doc = audit(Path(args.candidate), args.games)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
    write_md(doc)
    print(f"Wrote {OUT_JSON} and {OUT_MD}")
    print(f"  runtime-wired={doc['runtime_wired_fixtures']} "
          f"lab-only={doc['lab_only_fixtures']} "
          f"empirical_available={doc['empirical'].get('available')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
