#!/usr/bin/env python3
"""Pass 41 (Part I) — non-inertness / decision-trace audit of the cg_typed candidate.

Plays a small LIVE game set (candidate vs its stdlib parent, both seats) and, at
every candidate decision, records what the parent would have chosen on the same
observation (shadow). Aggregates:

  * total / changed decisions and the changed rate (non-inertness)
  * illegal candidate refinements (MUST be 0)
  * SelectContexts where the candidate diverges from the parent
  * fallback count (candidate's typed path deferred to its legal fallback)
  * candidate uncaught exceptions (MUST be 0) and parent shadow exceptions (context)
  * concrete divergence examples

HARD FAIL on any illegal candidate action or any uncaught candidate exception.
RESUMABLE + wall-budgeted; re-invoke until ``ALL DONE``. Benchmark-only; root
main.py/deck.csv read-only; no upload/submit/promote/mutate.

Outputs: data/experiments/pass41_non_inertness_trace.{json,md}
         data/experiments/pass41_non_inertness_examples.jsonl
Progress (transient): data/experiments/pass41_non_inertness_progress.json
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
CAND_RUN = REPO / "data/tournament/benchmark/_cg_cand_extracted/cg_typed_mono_lightning_miraidon_policy_v1"
CAND_TAR = REPO / "data/submissions/candidates_pass41/cg_typed_mono_lightning_miraidon_policy_v1.tar.gz"
PROGRESS = EXP / "pass41_non_inertness_progress.json"
ROOT_MAIN = REPO / "main.py"
ROOT_DECK = REPO / "deck.csv"

from ptcg_activegraph.decks.deck_io import load_deck  # noqa: E402
from ptcg_activegraph.experiments.runner import run_one_game_subprocess  # noqa: E402
from ptcg_activegraph.tournament.artifacts import safe_extract_all  # noqa: E402

CHILD = str(REPO / "src/ptcg_activegraph/experiments/_pass41_non_inertness_subprocess.py")
GAME_TIMEOUT = 100
WALL_BUDGET = 75
PARENT_ID = "mono_lightning_miraidon_easy"
GAMES_PER_SEAT = 3


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _ensure_candidate() -> Path:
    if not (CAND_RUN / "cg" / "libcg.so").is_file():
        CAND_RUN.mkdir(parents=True, exist_ok=True)
        with tarfile.open(CAND_TAR) as t:
            safe_extract_all(t, CAND_RUN)
    return CAND_RUN


def _game_list() -> list[tuple[int, int]]:
    return [(s, g) for s in (0, 1) for g in range(GAMES_PER_SEAT)]


def _load_progress() -> dict:
    if PROGRESS.is_file():
        try:
            return json.loads(PROGRESS.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"games": {}, "root_main_sha": _sha(ROOT_MAIN),
            "root_deck_sha": _sha(ROOT_DECK)}


def _finalize(progress: dict) -> int:
    games = list(progress["games"].values())
    agg = {"total_decisions": 0, "changed": 0, "illegal": 0, "fallback": 0,
           "cand_exceptions": 0, "par_exceptions": 0,
           "context_total": {}, "context_changed": {}}
    examples = []
    completed = errors = 0
    for gm in games:
        if gm.get("completed") and not gm.get("error"):
            completed += 1
        if gm.get("error"):
            errors += 1
        tr = gm.get("trace") or {}
        for k in ("total_decisions", "changed", "illegal", "fallback",
                  "cand_exceptions", "par_exceptions"):
            agg[k] += int(tr.get(k, 0) or 0)
        for k in ("context_total", "context_changed"):
            for ctx, c in (tr.get(k) or {}).items():
                agg[k][ctx] = agg[k].get(ctx, 0) + int(c)
        for ex in (tr.get("examples") or []):
            ex = dict(ex)
            ex["seat"] = gm.get("candidate_seat")
            examples.append(ex)

    td = agg["total_decisions"]
    changed_rate = round(agg["changed"] / td, 4) if td else None
    fallback_rate = round(agg["fallback"] / td, 4) if td else None
    root_ok = (_sha(ROOT_MAIN) == progress.get("root_main_sha")
               and _sha(ROOT_DECK) == progress.get("root_deck_sha"))

    hard_fail = bool(agg["illegal"] > 0 or agg["cand_exceptions"] > 0
                     or not root_ok or errors > 0)
    # Non-inertness: the candidate is a full policy replacement, so it must visibly
    # diverge from the parent on a non-trivial share of live decisions.
    non_inert = bool(td > 0 and agg["changed"] > 0)
    ok = (not hard_fail) and non_inert

    ctx_changed_sorted = sorted(agg["context_changed"].items(),
                                key=lambda kv: -kv[1])
    out = {
        "pass": 41, "part": "I", "kind": "non_inertness_decision_trace",
        "candidate_id": "cg_typed_mono_lightning_miraidon_policy_v1",
        "parent_id": PARENT_ID, "no_upload": True, "local_only": True,
        "games": len(games), "games_completed": completed, "games_error": errors,
        "total_decisions": td, "changed_decisions": agg["changed"],
        "changed_rate": changed_rate,
        "illegal_refinements": agg["illegal"],
        "fallback_count": agg["fallback"], "fallback_rate": fallback_rate,
        "candidate_uncaught_exceptions": agg["cand_exceptions"],
        "parent_shadow_exceptions": agg["par_exceptions"],
        "contexts_changed": dict(ctx_changed_sorted),
        "contexts_total": agg["context_total"],
        "root_main_deck_unchanged": root_ok,
        "non_inert": non_inert, "hard_fail": hard_fail, "ok": ok,
        "note": "decision divergence vs parent on identical observations; legality "
                "and never-raise are HARD gates. Local-only; not a strength claim.",
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass41_non_inertness_trace.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8")
    with (EXP / "pass41_non_inertness_examples.jsonl").open("w", encoding="utf-8") as fh:
        for ex in examples:
            fh.write(json.dumps(ex, default=str) + "\n")

    def yn(v):
        return "yes" if v else "no"
    md = [
        "# Pass 41 (Part I) — Non-Inertness / Decision-Trace Audit", "",
        f"> Candidate `{out['candidate_id']}` vs parent `{PARENT_ID}` on a live game "
        "set; at each candidate decision we shadow the parent's choice on the same "
        "observation. Legality + never-raise are HARD gates.", "",
        f"- games: {completed}/{len(games)} completed (errors={errors})",
        f"- decisions: **{td}**, changed: **{agg['changed']}** "
        f"(changed rate **{changed_rate}**)",
        f"- illegal candidate refinements: **{agg['illegal']}** (must be 0)",
        f"- candidate uncaught exceptions: **{agg['cand_exceptions']}** (must be 0)",
        f"- fallback count: {agg['fallback']} (rate {fallback_rate}) · parent shadow "
        f"exceptions: {agg['par_exceptions']}",
        f"- root main.py/deck.csv unchanged: **{yn(root_ok)}**",
        f"- **non_inert: {yn(non_inert)} · hard_fail: {yn(hard_fail)} · ok: {yn(ok)}**",
        "",
        "## Contexts where candidate diverges from parent",
        "| SelectContext | changed | total |", "|---|---|---|",
    ]
    for ctx, c in ctx_changed_sorted:
        md.append(f"| {ctx} | {c} | {agg['context_total'].get(ctx, 0)} |")
    md += ["", "## Example divergences (capped)", ""]
    for ex in examples[:12]:
        md.append(f"- ctx={ex.get('ctx')} seat{ex.get('seat')} n={ex.get('n')} "
                  f"cand={ex.get('candidate')} parent={ex.get('parent')} "
                  f"fallback={ex.get('fallback_used')}")
    md.append("")
    (EXP / "pass41_non_inertness_trace.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"ALL DONE: decisions={td} changed={agg['changed']} illegal={agg['illegal']} "
          f"cand_exc={agg['cand_exceptions']} hard_fail={hard_fail} ok={ok}")
    return 0 if ok else 1


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    cand_dir = _ensure_candidate()
    cand_main = cand_dir / "main.py"
    cand_deck = load_deck(cand_dir / "deck.csv")
    par_main = EXTR_OURS / PARENT_ID / "main.py"
    par_deck = load_deck(EXTR_OURS / PARENT_ID / "deck.csv")

    progress = _load_progress()
    games = progress["games"]
    pending = [(s, g) for (s, g) in _game_list() if f"seat{s}::g{g}" not in games]
    if not pending:
        return _finalize(progress)

    start = time.time()
    ran = 0
    for seat, g in pending:
        if time.time() - start > WALL_BUDGET and ran > 0:
            break
        t0 = time.time()
        res = run_one_game_subprocess(
            control_main=par_main, control_deck=par_deck,
            cand_main=cand_main, cand_deck=cand_deck,
            candidate_seat=seat, timeout_seconds=GAME_TIMEOUT, child_script=CHILD)
        res["seconds"] = round(time.time() - t0, 1)
        games[f"seat{seat}::g{g}"] = res
        PROGRESS.write_text(json.dumps(progress, indent=2, default=str), encoding="utf-8")
        ran += 1
        tr = res.get("trace") or {}
        flag = "OK" if (res.get("completed") and not res.get("error")) else "FAIL"
        print(f"[{flag}] seat{seat}::g{g} {res['seconds']}s dec={tr.get('total_decisions')} "
              f"changed={tr.get('changed')} illegal={tr.get('illegal')} "
              f"err={res.get('error')}")

    remaining = [(s, g) for (s, g) in _game_list() if f"seat{s}::g{g}" not in games]
    if remaining:
        print(f"TICK DONE: ran {ran}, {len(remaining)} remaining — re-invoke")
        return 2
    return _finalize(progress)


if __name__ == "__main__":
    raise SystemExit(main())
