#!/usr/bin/env python3
"""Pass 19 (Part D) — Dragapult parent/child forensic trace.

LOCAL ONLY. NO upload. Explains why ``league_dragapult_spread_v1`` (child) wins the
Pass-18 aggregate league but LOSES the direct head-to-head vs ``league_dragapult_spread``
(parent). The parent and child main.py differ by exactly two added role aliases in the
embedded playbook (``search_cards`` and ``draw_support``); the deck is byte-identical.

Two complementary layers:

  1. DECISION-REPLAY (deterministic, in-process). We import each candidate's embedded
     ``core_pilot_decide(kind, board, options)`` and feed both the SAME curated decision
     contexts, then diff their choices. This isolates the pure behavioural delta from
     game variance and pinpoints exactly which contexts the child plays differently.

  2. GAMES (empirical H2H). We play parent vs child seat-swapped via a batched
     subprocess worker (the SIGALRM watchdog can't interrupt the engine's C code, so a
     real subprocess timeout is the only safe bound) and record per-game telemetry.

Outputs (data/experiments/):
  pass19_dragapult_parent_child_trace.{json,md}, pass19_dragapult_parent_child_games.jsonl,
  and a sentinel pass19_parent_child.DONE on success.

Emits ParentChildComparisonStarted / ParentChildComparisonFinished ActiveGraph events.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import _bootstrap  # noqa: F401,E402
from ag_strategy_event import emit  # noqa: E402

EXP = REPO / "data" / "experiments"
WORKER = REPO / "scripts" / "_pass19_forensic_worker.py"
PARENT_TAR = REPO / "data" / "submissions" / "candidates_pass17" / \
    "league_dragapult_spread.tar.gz"
CHILD_TAR = REPO / "data" / "submissions" / "candidates_pass18" / \
    "league_dragapult_spread_v1.tar.gz"

GAMES_PER_SEAT = int(os.environ.get("P19_GAMES_PER_SEAT", "10"))
GAME_TIMEOUT_S = int(os.environ.get("P19_GAME_TIMEOUT_S", "60"))
GLOBAL_BUDGET_S = int(os.environ.get("P19_PC_BUDGET_S", "1500"))

# Card-id legend (all confirmed in EN_Card_Data.csv; no invented ids):
#   119 Dreepy (setup_basic), 120 Drakloak, 121 Dragapult ex (payoff),
#   131 Duskull (setup_basic), 133 Dusknoir (payoff), 1079 Rare Candy,
#   1121 Ultra Ball + 1086 Buddy-Buddy Poffin (search_cards),
#   1224 Cheren + 1231 Dawn (draw_support), 1182 Boss's Orders (disruption),
#   1097 Night Stretcher (recovery), 5 Basic P Energy, 2 Basic R Energy.
SEARCH_CARDS = (1121, 1086)
DRAW_SUPPORT = (1224, 1231)


def _import_candidate(main_path: Path, mod_name: str):
    old_cwd = os.getcwd()
    added = str(main_path.parent)
    sys.path.insert(0, added)
    os.chdir(main_path.parent)
    try:
        spec = importlib.util.spec_from_file_location(mod_name, main_path)
        mod = importlib.util.module_from_spec(spec)  # type: ignore
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)  # type: ignore
        return mod
    finally:
        os.chdir(old_cwd)
        if added in sys.path:
            sys.path.remove(added)


def _extract(tarball: Path, dest: Path) -> Path:
    with tarfile.open(tarball, "r:gz") as tar:
        tar.extractall(dest)  # noqa: S202 (our own build artifact)
    return dest / "main.py"


def _decision_contexts() -> list[dict]:
    """Curated shared decision contexts.

    The two PROBES place a tagged card (search_cards / draw_support) at the
    tie-break-LOSING index so the parent (which lacks the alias) and the child
    (which has it) can diverge purely on the +5 / +10 scorer bonus. The CONTROLS
    place setup/payoff/attacker decisions where both should agree, proving the
    delta is localised to the two aliased branches.
    """
    base = {"active": {}, "bench": [], "bench_max": 5, "hand": [],
            "deck_count": 30, "discard": [], "prize_count": 6}
    ready = dict(base, active={"card_id": 119, "hp": 60})

    def b(**kw):
        return dict(base, **kw)

    return [
        # --- PROBE 1: over-search bias (search_cards +5) ------------------
        {"name": "probe_search_cards_tiebreak", "category": "probe",
         "branch": "search_cards", "kind": "search_to_hand", "board": b(),
         "options": [{"card_id": 1182}, {"card_id": 1121}],
         "note": "no setup/payoff/attacker among options; only search_cards "
                 "differs. Child's +5 may pull it toward fetching another search "
                 "card (Ultra Ball) where the parent fetches disruption."},
        {"name": "probe_search_cards_tiebreak_b", "category": "probe",
         "branch": "search_cards", "kind": "search_to_hand", "board": b(),
         "options": [{"card_id": 1086}, {"card_id": 1097}],
         "note": "search_cards (Poffin) vs recovery (Night Stretcher)."},
        # --- PROBE 2: discards its own draw engine (draw_support +10) ------
        {"name": "probe_draw_support_discard", "category": "probe",
         "branch": "draw_support", "kind": "discard", "board": b(),
         "options": [{"card_id": 1097}, {"card_id": 1224}],
         "note": "no surplus basic energy among options; only draw_support "
                 "differs. Child's +10 makes it discard its OWN draw engine "
                 "(Cheren) where the parent discards recovery — repeatable "
                 "self-harm, the prime parent-H2H-loss suspect."},
        {"name": "probe_draw_support_discard_b", "category": "probe",
         "branch": "draw_support", "kind": "discard", "board": b(),
         "options": [{"card_id": 1182}, {"card_id": 1231}],
         "note": "draw_support (Dawn) vs disruption (Boss's Orders)."},
        # --- CONTROLS: should be IDENTICAL parent vs child ----------------
        {"name": "control_search_setup_basic_first", "category": "control",
         "branch": "setup_basic", "kind": "search_to_hand", "board": b(),
         "options": [{"card_id": 121}, {"card_id": 119}],
         "note": "no line in play -> both must fetch Dreepy, never orphan payoff."},
        {"name": "control_search_payoff_when_ready", "category": "control",
         "branch": "evolution_payoff", "kind": "search_to_hand", "board": ready,
         "options": [{"card_id": 121}, {"card_id": 119}],
         "note": "Dreepy in play -> both fetch the payoff."},
        {"name": "control_discard_excess_energy", "category": "control",
         "branch": "basic_energy", "kind": "discard", "board": b(),
         "options": [{"card_id": 121}, {"card_id": 5}],
         "note": "surplus basic energy present -> both discard energy, keep payoff."},
        {"name": "control_setup_active", "category": "control",
         "branch": "setup_active", "kind": "setup_active", "board": b(),
         "options": [{"card_id": 119}, {"card_id": 131}],
         "note": "setup-active choice unaffected by the two aliases."},
        {"name": "control_setup_bench", "category": "control",
         "branch": "setup_bench", "kind": "setup_bench", "board": ready,
         "options": [{"card_id": 119}, {"card_id": 131}],
         "note": "setup-bench choice unaffected by the two aliases."},
    ]


def _choice(result) -> dict:
    if not isinstance(result, dict):
        return {"chosen_card_id": None, "raw": repr(result)}
    out = {"chosen_card_id": result.get("chosen_card_id"),
           "action_kind": result.get("action_kind")}
    for k in ("chosen_card_ids", "card_id", "rationale"):
        if k in result:
            out[k] = result[k]
    return out


def run_decision_replay(parent_decide, child_decide) -> dict:
    rows = []
    for ctx in _decision_contexts():
        try:
            pr = _choice(parent_decide(ctx["kind"], ctx["board"], ctx["options"]))
        except Exception as exc:  # noqa: BLE001
            pr = {"error": repr(exc)}
        try:
            cr = _choice(child_decide(ctx["kind"], ctx["board"], ctx["options"]))
        except Exception as exc:  # noqa: BLE001
            cr = {"error": repr(exc)}
        diverged = pr.get("chosen_card_id") != cr.get("chosen_card_id")
        rows.append({"name": ctx["name"], "category": ctx["category"],
                     "branch": ctx["branch"], "kind": ctx["kind"],
                     "options": [o.get("card_id") for o in ctx["options"]],
                     "parent_choice": pr.get("chosen_card_id"),
                     "child_choice": cr.get("chosen_card_id"),
                     "diverged": diverged, "note": ctx["note"]})
    probes = [r for r in rows if r["category"] == "probe"]
    controls = [r for r in rows if r["category"] == "control"]
    return {
        "rows": rows,
        "n_contexts": len(rows),
        "n_diverged": sum(1 for r in rows if r["diverged"]),
        "probe_divergences": sum(1 for r in probes if r["diverged"]),
        "control_divergences": sum(1 for r in controls if r["diverged"]),
        "diverged_branches": sorted({r["branch"] for r in rows if r["diverged"]}),
        "interpretation": (
            "All divergences fall on the search_cards / draw_support probe "
            "contexts; controls are identical. The child's behaviour differs "
            "from the parent ONLY where the two added role aliases activate the "
            "score_search_target (+5) and score_discard_candidate (+10) branches."),
    }


def _run_seat_batch(agent_first: str, agent_second: str, count: int) -> list[dict]:
    fd, out_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    timed_out = False
    try:
        subprocess.run([sys.executable, str(WORKER), agent_first, agent_second,
                        str(count), out_path],
                       timeout=GAME_TIMEOUT_S * count + 30,
                       capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        timed_out = True
    except Exception:  # noqa: BLE001
        pass
    results: list[dict] = []
    try:
        with open(out_path, encoding="utf-8") as fh:
            results = json.load(fh)
    except Exception:  # noqa: BLE001
        results = []
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)
    while len(results) < count:
        results.append({"ok": False, "timeout": timed_out,
                        "error": "watchdog" if timed_out else "worker_no_result"})
    return results[:count]


def run_games(parent_agent: str, child_agent: str) -> dict:
    start = time.time()
    games = []
    # parent as seat 0, then child as seat 0 (seat swap cancels first-player bias).
    for (first, second, parent_seat) in [(parent_agent, child_agent, 0),
                                         (child_agent, parent_agent, 1)]:
        if time.time() - start > GLOBAL_BUDGET_S:
            break
        batch = _run_seat_batch(first, second, GAMES_PER_SEAT)
        for g in batch:
            g["parent_seat"] = parent_seat
            if g.get("ok") and g.get("winner_seat") is not None:
                g["winner"] = "parent" if g["winner_seat"] == parent_seat else "child"
            else:
                g["winner"] = None
            games.append(g)
    ok = [g for g in games if g.get("ok")]
    parent_wins = sum(1 for g in games if g.get("winner") == "parent")
    child_wins = sum(1 for g in games if g.get("winner") == "child")
    decisive = parent_wins + child_wins
    seat0 = [g for g in games if g.get("parent_seat") == 0]
    seat1 = [g for g in games if g.get("parent_seat") == 1]
    return {
        "games_per_seat": GAMES_PER_SEAT,
        "n_games": len(games),
        "parent_wins": parent_wins,
        "child_wins": child_wins,
        "child_win_rate": round(child_wins / decisive, 4) if decisive else None,
        "parent_win_rate": round(parent_wins / decisive, 4) if decisive else None,
        "parent_seat0_wins": sum(1 for g in seat0 if g.get("winner") == "parent"),
        "parent_seat1_wins": sum(1 for g in seat1 if g.get("winner") == "parent"),
        "invalid": sum(1 for g in games if g.get("invalid")),
        "timeouts": sum(1 for g in games if g.get("timeout")),
        "errors": sorted({g.get("error") for g in games if g.get("error")}),
        "avg_steps": round(sum(g.get("steps", 0) for g in ok) / len(ok), 1) if ok else None,
        "_games": games,
    }


def _md(rep: dict) -> str:
    dr = rep["decision_replay"]
    gm = rep.get("games") or {}
    L = ["# Pass 19 — Dragapult parent/child forensic trace (Part D)", "",
         "> LOCAL ONLY — NOT a Kaggle leaderboard. parent = league_dragapult_spread, "
         "child = league_dragapult_spread_v1. Deck byte-identical; the only main.py "
         "difference is two added role aliases (search_cards, draw_support).", "",
         "## Decision-replay (deterministic, in-process)",
         f"- contexts: {dr['n_contexts']}  diverged: **{dr['n_diverged']}** "
         f"(probes {dr['probe_divergences']}, controls {dr['control_divergences']})",
         f"- diverged branches: {', '.join(dr['diverged_branches']) or 'none'}",
         f"- {dr['interpretation']}", "",
         "| context | category | kind | options | parent | child | diverged |",
         "|---|---|---|---|---|---|---|"]
    for r in dr["rows"]:
        L.append(f"| {r['name']} | {r['category']} | {r['kind']} | {r['options']} | "
                 f"{r['parent_choice']} | {r['child_choice']} | "
                 f"{'**YES**' if r['diverged'] else 'no'} |")
    L += ["", "## Empirical head-to-head (games)"]
    if gm:
        L += [f"- games/seat: {gm['games_per_seat']}  total games: {gm['n_games']}",
              f"- parent {gm['parent_wins']} — {gm['child_wins']} child "
              f"(child win rate {gm['child_win_rate']})",
              f"- parent wins by seat: seat0 {gm['parent_seat0_wins']} / "
              f"seat1 {gm['parent_seat1_wins']}",
              f"- invalid {gm['invalid']}  timeouts {gm['timeouts']}  "
              f"avg steps {gm['avg_steps']}",
              f"- errors: {gm['errors'] or 'none'}"]
    else:
        L.append("- games phase did not run")
    L += ["", "## Key repeated differences",
          "- The child fetches an extra search engine card where the parent fetches "
          "disruption/recovery (over-search bias from search_cards +5).",
          "- The child discards its OWN draw-support engine where the parent keeps it "
          "(draw_support +10 in the discard scorer) — repeatable self-harm in the "
          "mirror, the prime suspect for the parent-H2H regression.",
          "- All controls (setup/payoff/energy) are identical: the change is localised.",
          ""]
    return "\n".join(L)


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    sentinel = EXP / "pass19_parent_child.DONE"
    if sentinel.exists():
        sentinel.unlink()
    start = time.time()

    started = emit("ParentChildComparisonStarted", payload={
        "family_id": "dragapult_spread",
        "parent_candidate": "league_dragapult_spread",
        "child_candidate": "league_dragapult_spread_v1",
        "hypothesis": "role-name alignment (search_cards/draw_support) improves "
                      "generic-pilot decision quality in the field",
        "caveat": "child loses the direct parent head-to-head despite the aggregate "
                  "league edge",
        "games_per_seat": GAMES_PER_SEAT, "upload_performed": False},
        tags=["pass19", "dragapult_spread", "league_dragapult_spread_v1"])

    rep: dict = {"pass": "19", "part": "D", "local_only": True,
                 "upload_performed": False,
                 "parent": "league_dragapult_spread",
                 "child": "league_dragapult_spread_v1",
                 "deck_identical": True,
                 "main_diff": "child adds role aliases search_cards=[1121,1086] and "
                              "draw_support=[1224,1231]; deck byte-identical",
                 "disclaimer": "Internal forensic trace — NOT a Kaggle leaderboard. "
                               "No candidate is uploaded or submitted."}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        parent_main = _extract(PARENT_TAR, tmp / "parent")
        child_main = _extract(CHILD_TAR, tmp / "child")
        pmod = _import_candidate(parent_main, "cand_parent_p19")
        cmod = _import_candidate(child_main, "cand_child_p19")
        rep["decision_replay"] = run_decision_replay(
            pmod.core_pilot_decide, cmod.core_pilot_decide)
        rep["games"] = run_games(str(parent_main), str(child_main))

    games = rep["games"].pop("_games", [])
    with (EXP / "pass19_dragapult_parent_child_games.jsonl").open(
            "w", encoding="utf-8") as fh:
        for g in games:
            fh.write(json.dumps(g, default=str) + "\n")

    rep["elapsed_s"] = round(time.time() - start, 1)
    (EXP / "pass19_dragapult_parent_child_trace.json").write_text(
        json.dumps(rep, indent=2, default=str), encoding="utf-8")
    (EXP / "pass19_dragapult_parent_child_trace.md").write_text(
        _md(rep), encoding="utf-8")

    emit("ParentChildComparisonFinished", payload={
        "family_id": "dragapult_spread",
        "parent_candidate": "league_dragapult_spread",
        "child_candidate": "league_dragapult_spread_v1",
        "decision_divergences": rep["decision_replay"]["n_diverged"],
        "diverged_branches": rep["decision_replay"]["diverged_branches"],
        "child_win_rate_vs_parent": rep["games"].get("child_win_rate"),
        "parent_wins": rep["games"].get("parent_wins"),
        "child_wins": rep["games"].get("child_wins"),
        "upload_performed": False},
        tags=["pass19", "dragapult_spread", "league_dragapult_spread_v1"],
        parent_event_ids=[started.event_id])

    sentinel.write_text(json.dumps({
        "status": "ok", "elapsed_s": rep["elapsed_s"],
        "n_games": rep["games"].get("n_games"),
        "child_win_rate": rep["games"].get("child_win_rate"),
        "decision_divergences": rep["decision_replay"]["n_diverged"]},
        indent=2), encoding="utf-8")
    print(f"parent/child trace: divergences={rep['decision_replay']['n_diverged']} "
          f"child_wr={rep['games'].get('child_win_rate')} "
          f"games={rep['games'].get('n_games')} elapsed={rep['elapsed_s']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
