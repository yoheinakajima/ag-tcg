#!/usr/bin/env python3
"""Pass 12 — two-stage meta-driven candidate evaluation (LOCAL only).

SURROGATE-BASED and DIRECTIONAL ONLY. Opponent replays give us DECK LISTS, not
policies; each replay deck is piloted by a stable generic surrogate. These
results never equal Kaggle results and are NEVER sufficient to promote/upload a
candidate. No upload, no submission, no GitHub push.

Protocol (config: experiments/pass12_meta_eval.yaml):
  * Stage 1 (scout): every validator-passing candidate + controls vs every
    opponent-archetype surrogate, seat-swapped, 3 games/seat. Also each candidate
    vs the live active control, plus an active-control self-mirror diagnostic.
  * Stage 2 (focused): the top scout candidates + active control + best transfer
    (+ best chaos, if any exist) re-run at 10 games/seat for confirmation.

Promotion gate (mirrors ranker.label_for): >= min_games completed, 80% Wilson
lower bound > 0.50, AND beats the active control AND not a mirror-overfit. At most
ONE candidate may enter the dry-run queue; upload_performed is always false.

Outputs (data/experiments/):
  pass12_scout_results.{json,md}, pass12_matchup_matrix.csv,
  pass12_candidate_metrics.json, pass12_focused_results.{json,md},
  pass12_focused_matchup_matrix.csv, pass12_ranking.{json,md},
  pass12_dry_run_queue.json
"""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import yaml  # noqa: E402

import run_meta_pool_eval as eng  # reuse proven game primitives  # noqa: E402
from ptcg_activegraph.experiments.ranker import wilson_interval, Z_80  # noqa: E402
from ptcg_activegraph.sim.surrogate_agents import materialize_surrogate_agent  # noqa: E402

CONFIG = REPO / "experiments" / "pass12_meta_eval.yaml"
REGISTRY = REPO / "data" / "kaggle_uploads" / "live_score_registry.json"
MANIFEST = REPO / "data" / "submissions" / "pass12_candidates_manifest.json"
CAND_DIR = REPO / "data" / "submissions" / "candidates"
CAND12_DIR = REPO / "data" / "submissions" / "candidates_pass12"
BASELINES = REPO / "data" / "baselines"
SURR_DIR = REPO / "data" / "meta_replays" / "surrogates"
OUT = REPO / "data" / "experiments"

DISCLAIMER = (
    "Surrogate-based and DIRECTIONAL ONLY. Opponent decks are piloted by a generic "
    "surrogate policy, not the real opponent policy. These results never equal "
    "Kaggle results and are not sufficient to promote or upload a candidate. Live "
    "Kaggle scores could not be refreshed this pass (kaggle CLI unavailable).")


# --------------------------------------------------------------------------- #
# Config + provenance
# --------------------------------------------------------------------------- #
def _load_config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}


def _registry_active_control() -> tuple[str, float | None]:
    if REGISTRY.exists():
        reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
        ac = reg.get("active_control") or {}
        fn = (ac.get("filename") or "").replace(".tar.gz", "")
        if fn:
            return fn, ac.get("public_score")
    return "combo_full_safety_v3_fixed", None


# --------------------------------------------------------------------------- #
# Part G: persistent surrogate opponent dirs + metadata
# --------------------------------------------------------------------------- #
def build_surrogates(cfg: dict) -> list[dict]:
    """Materialize one persistent surrogate dir per opponent archetype + the
    diagnostic self-mirror, each with a metadata.json honesty note."""
    SURR_DIR.mkdir(parents=True, exist_ok=True)
    out: list[dict] = []
    entries = list(cfg.get("opponent_archetypes", []))
    sm = cfg.get("self_mirror")
    if sm:
        # resolve self-mirror deck from meta_pool
        pool = yaml.safe_load((REPO / "experiments" / "meta_pool.yaml")
                              .read_text(encoding="utf-8")) or {}
        by_key = {a["key"]: a for a in pool.get("archetypes", [])}
        md = by_key.get(sm["key"], {})
        entries = entries + [{"key": sm["key"], "confidence": "diagnostic",
                              "surrogate_deck": md.get("surrogate_deck"),
                              "role": "diagnostic_only"}]
    weights = cfg.get("evaluation_weights", {})
    for a in entries:
        deck = a.get("surrogate_deck")
        if not deck or not (REPO / deck).exists():
            out.append({"key": a["key"], "status": "missing_deck", "deck": deck})
            continue
        dest = SURR_DIR / a["key"]
        main = materialize_surrogate_agent(REPO / deck, dest)
        meta = {
            "key": a["key"],
            "confidence": a.get("confidence"),
            "role": a.get("role", "opponent"),
            "weight": weights.get(a["key"], 0.0),
            "deck_source": str(deck),
            "pilot": "generic v1 surrogate brain (data/baselines/v1_kaggle_349_8)",
            "honesty": ("DECK-FAITHFUL, POLICY-APPROXIMATE: the 60-card deck is the "
                        "real replay-derived list (no invented ids); the policy is a "
                        "generic surrogate, NOT the opponent's real policy."),
        }
        (dest / "metadata.json").write_text(json.dumps(meta, indent=2),
                                            encoding="utf-8")
        out.append({"key": a["key"], "status": "ready",
                    "agent": str(main), "deck": str(deck),
                    "confidence": a.get("confidence"),
                    "role": a.get("role", "opponent"),
                    "weight": weights.get(a["key"], 0.0)})
    return out


# --------------------------------------------------------------------------- #
# Candidate resolution (validator-before-eval gate)
# --------------------------------------------------------------------------- #
def resolve_candidates(tmp: Path, ac_name: str) -> tuple[list[dict], list[str]]:
    cands: list[dict] = []
    notes: list[str] = []

    # Controls / anchors.
    ac_tar = CAND_DIR / f"{ac_name}.tar.gz"
    if ac_tar.exists() and eng._validate_tarball(ac_tar):
        cands.append({"id": ac_name, "role": "active_control", "kind": "control",
                      "group": "control", "agent": eng._extract_agent(ac_tar, tmp / ac_name)})
    else:
        notes.append(f"active control {ac_name} tarball missing/invalid")

    v1_main = BASELINES / "v1_kaggle_349_8" / "main.py"
    if v1_main.exists():
        cands.append({"id": "v1_kaggle_349_8", "role": "legacy_baseline",
                      "kind": "control", "group": "control", "agent": str(v1_main)})
    v2_tar = CAND_DIR / "deck_energy_trim_light.tar.gz"
    if ac_name != "deck_energy_trim_light" and v2_tar.exists() and eng._validate_tarball(v2_tar):
        cands.append({"id": "deck_energy_trim_light", "role": "reference_v2",
                      "kind": "control", "group": "control",
                      "agent": eng._extract_agent(v2_tar, tmp / "v2")})

    # Pass-12 built candidates (validator-before-eval: re-validate each tarball).
    man = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    for r in man.get("built", []):
        cid = r["id"]
        tar = REPO / r["tarball"]
        if not tar.exists():
            notes.append(f"{cid}: tarball missing ({r['tarball']})")
            continue
        if not eng._validate_tarball(tar):
            notes.append(f"{cid}: failed re-validation, EXCLUDED from eval")
            continue
        cands.append({"id": cid, "role": "candidate", "kind": r.get("kind"),
                      "group": r.get("group"),
                      "agent": eng._extract_agent(tar, tmp / cid)})
    for r in man.get("blocked", []):
        notes.append(f"{r['id']}: BLOCKED ({r.get('reason','')})")
    return cands, notes


# --------------------------------------------------------------------------- #
# Matchup runner (games_per_seat is a parameter, unlike the engine default)
# --------------------------------------------------------------------------- #
def run_matchup(cand_agent: str, opp_agent: str, gps: int, budget_left) -> dict:
    games = []
    for a, b, our in [(cand_agent, opp_agent, 0), (opp_agent, cand_agent, 1)]:
        for _ in range(gps):
            if budget_left() <= 0:
                games.append({"ok": False, "skipped": True,
                              "reason": "global_budget_exhausted", "our_seat": our})
                continue
            g = eng._run_game(a, b)
            g["our_seat"] = our
            g["outcome"] = eng._outcome_for_seat(g, our)
            games.append(g)
    wins = sum(1 for g in games if g.get("outcome") == "win")
    losses = sum(1 for g in games if g.get("outcome") == "loss")
    draws = sum(1 for g in games if g.get("outcome") == "draw")
    decisive = wins + losses
    completed = wins + losses + draws
    # tempo metric: average first-attack step for our seat across completed games.
    fa = [g.get("first_attack_step", {}).get(g["our_seat"])
          for g in games if g.get("ok")]
    fa = [x for x in fa if x is not None]
    return {
        "games": games, "wins": wins, "losses": losses, "draws": draws,
        "completed": completed,
        "win_rate": round(wins / decisive, 4) if decisive else None,
        "adjusted_win_rate": round((wins + 0.5 * draws) / completed, 4) if completed else None,
        "avg_first_attack_step": round(sum(fa) / len(fa), 2) if fa else None,
        "crashes": sum(1 for g in games if not g.get("ok") and not g.get("timeout")
                       and not g.get("skipped")),
        "timeouts": sum(1 for g in games if g.get("timeout")),
        "skipped": sum(1 for g in games if g.get("skipped")),
    }


def weighted_meta_score(per_arch: dict, weights: dict) -> float | None:
    acc = tot = 0.0
    for key, w in weights.items():
        wr = (per_arch.get(key) or {}).get("adjusted_win_rate")
        if wr is None:
            continue
        acc += float(w) * float(wr)
        tot += float(w)
    return round(acc / tot, 4) if tot > 0 else None


# --------------------------------------------------------------------------- #
# Stage runner
# --------------------------------------------------------------------------- #
def run_stage(stage: str, gps: int, candidates: list[dict], opponents: list[dict],
              weights: dict, ac_id: str | None, mirror_key: str | None,
              budget_left) -> dict:
    per_candidate: dict = {}
    ac = next((c for c in candidates if c["role"] == "active_control"), None)

    for c in candidates:
        per_arch: dict = {}
        for opp in opponents:
            m = run_matchup(c["agent"], opp["agent"], gps, budget_left)
            per_arch[opp["key"]] = {
                "win_rate": m["win_rate"], "adjusted_win_rate": m["adjusted_win_rate"],
                "wins": m["wins"], "losses": m["losses"], "draws": m["draws"],
                "completed": m["completed"], "weight": opp["weight"],
                "confidence": opp["confidence"], "role": opp["role"],
                "avg_first_attack_step": m["avg_first_attack_step"],
                "crashes": m["crashes"], "timeouts": m["timeouts"], "skipped": m["skipped"],
            }
        vs_ac = None
        if ac and c["id"] != ac["id"]:
            mac = run_matchup(c["agent"], ac["agent"], gps, budget_left)
            vs_ac = {"adjusted_win_rate": mac["adjusted_win_rate"],
                     "wins": mac["wins"], "losses": mac["losses"],
                     "draws": mac["draws"], "completed": mac["completed"],
                     "crashes": mac["crashes"], "timeouts": mac["timeouts"]}
        # exclude the diagnostic mirror key from the weighted meta score.
        ext_weights = {k: v for k, v in weights.items() if k != mirror_key}
        wms = weighted_meta_score(per_arch, ext_weights)
        # mirror-overfit signal: strong vs the self-mirror but weak on real meta.
        mirror_wr = (per_arch.get(mirror_key) or {}).get("adjusted_win_rate") if mirror_key else None
        per_candidate[c["id"]] = {
            "id": c["id"], "role": c["role"], "kind": c["kind"], "group": c["group"],
            "per_archetype": per_arch, "vs_active_control": vs_ac,
            "weighted_meta_score": wms, "mirror_win_rate": mirror_wr,
        }
    return {"stage": stage, "games_per_seat": gps, "per_candidate": per_candidate}


# --------------------------------------------------------------------------- #
# Metrics aggregation + ranking/labels
# --------------------------------------------------------------------------- #
def candidate_metrics(stage_rep: dict, opponents: list[dict], weights: dict,
                      mirror_key: str | None, ac_adj: float | None,
                      min_games: int) -> list[dict]:
    ext_keys = [o["key"] for o in opponents if o["key"] != mirror_key]
    rows = []
    for cid, c in stage_rep["per_candidate"].items():
        # aggregate wins/draws across external (weighted) archetypes.
        wins = draws = losses = completed = 0
        crashes = timeouts = 0
        for k in ext_keys:
            m = c["per_archetype"].get(k) or {}
            wins += int(m.get("wins") or 0)
            draws += int(m.get("draws") or 0)
            losses += int(m.get("losses") or 0)
            completed += int(m.get("completed") or 0)
            crashes += int(m.get("crashes") or 0)
            timeouts += int(m.get("timeouts") or 0)
        adj = round((wins + 0.5 * draws) / completed, 4) if completed else None
        w80 = list(wilson_interval(wins + 0.5 * draws, completed, Z_80))
        rows.append({
            "candidate": cid, "role": c["role"], "kind": c["kind"], "group": c["group"],
            "weighted_meta_score": c["weighted_meta_score"],
            "adjusted_win_rate": adj, "games_completed": completed,
            "wins": wins, "losses": losses, "draws": draws,
            "wilson80": w80, "mirror_win_rate": c.get("mirror_win_rate"),
            "vs_active_control": (c.get("vs_active_control") or {}).get("adjusted_win_rate"),
            "crashes": crashes, "timeouts": timeouts,
        })
    return rows


def label_rows(rows: list[dict], ac_adj: float | None, min_games: int,
               cfg_gate: dict) -> list[dict]:
    ac_adj = 0.5 if ac_adj is None else ac_adj
    for r in rows:
        role = r["role"]
        adj = r["adjusted_win_rate"]
        w80lo = (r["wilson80"] or [0.0, 1.0])[0]
        games = r["games_completed"]
        mirror = r.get("mirror_win_rate")
        beats_ac = adj is not None and adj > ac_adj + 1e-9
        # mirror-overfit: clearly strong vs self-mirror but not vs the real meta.
        mirror_overfit = (cfg_gate.get("mirror_overfit_guard") and mirror is not None
                          and adj is not None and mirror >= 0.60 and adj < 0.50)
        if r["crashes"] or r["timeouts"]:
            r["label"] = "rejected"
            r["interpretation"] = (f"{r['crashes']} crash(es)/{r['timeouts']} "
                                   "timeout(s) — not trustworthy.")
        elif role in ("active_control", "legacy_baseline", "reference_v2"):
            r["label"] = "anchor"
            r["interpretation"] = (f"Control/anchor (adj {adj}); the baseline "
                                   "candidates must beat, never a promotion target.")
        elif mirror_overfit:
            r["label"] = "mirror_overfit"
            r["interpretation"] = (f"Beats the self-mirror ({mirror}) but not the real "
                                   f"meta (adj {adj}) — overfit to the mirror.")
        elif games == 0 or adj is None:
            r["label"] = "inconclusive"
            r["interpretation"] = "No completed games with a parseable outcome."
        elif games >= min_games and w80lo > 0.50 and beats_ac:
            r["label"] = "promotable"
            r["interpretation"] = (f"Adj {adj} over {games} games, 80% lower bound "
                                   f"{w80lo} > 0.50, beats control ({ac_adj:.2f}).")
        elif games >= min_games and beats_ac and adj >= 0.50:
            r["label"] = "confirmation_promising"
            r["interpretation"] = (f"Adj {adj} beats control ({ac_adj:.2f}) but 80% "
                                   f"lower bound {w80lo} <= 0.50.")
        elif adj is not None and adj >= 0.55:
            r["label"] = "scout_promising"
            r["interpretation"] = (f"Scout signal (adj {adj} over {games} games); "
                                   "needs focused confirmation.")
        else:
            r["label"] = "inconclusive"
            r["interpretation"] = (f"Adj {adj} over {games} games not distinguishable "
                                   f"from control ({ac_adj:.2f}).")
        r["beats_active_control"] = bool(beats_ac)
    return rows


# --------------------------------------------------------------------------- #
# Matchup matrix CSV
# --------------------------------------------------------------------------- #
def write_matrix(stage_rep: dict, opponents: list[dict], path: Path) -> None:
    keys = [o["key"] for o in opponents]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["candidate", "role", "group", *keys, "vs_active_control",
                    "weighted_meta_score"])
        for cid, c in stage_rep["per_candidate"].items():
            row = [cid, c["role"], c["group"]]
            for k in keys:
                m = c["per_archetype"].get(k) or {}
                row.append(m.get("adjusted_win_rate"))
            row.append((c.get("vs_active_control") or {}).get("adjusted_win_rate"))
            row.append(c.get("weighted_meta_score"))
            w.writerow(row)


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #
def md_stage(title: str, rows: list[dict], opponents: list[dict],
             stage_rep: dict, extra: list[str]) -> str:
    L = [f"# {title}", "", f"> {DISCLAIMER}", ""]
    L += extra + [""]
    L.append("| candidate | role | group | meta score | adj WR | 80% CI | games | "
             "vs AC | mirror | label |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda x: (x["weighted_meta_score"] is None,
                                         -(x["weighted_meta_score"] or -1))):
        ci = r["wilson80"]
        ci_s = "-" if not ci else f"{ci[0]:.2f}–{ci[1]:.2f}"
        L.append(f"| {r['candidate']} | {r['role']} | {r['group']} | "
                 f"{r['weighted_meta_score']} | {r['adjusted_win_rate']} | {ci_s} | "
                 f"{r['games_completed']} | {r['vs_active_control']} | "
                 f"{r.get('mirror_win_rate')} | {r['label']} |")
    L.append("")
    L.append("## Interpretations")
    for r in rows:
        L.append(f"- **{r['candidate']}** ({r['label']}): {r['interpretation']}")
    L.append("")
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    cfg = _load_config()
    gate = cfg.get("promotion_gate", {})
    min_games = int(gate.get("min_games", 20))
    weights = cfg.get("evaluation_weights", {})
    mirror_key = (cfg.get("self_mirror") or {}).get("key")
    budgets = cfg.get("budgets", {})
    eng.GLOBAL_BUDGET_S = int(os.environ.get("META_EVAL_GLOBAL_BUDGET_S",
                                             budgets.get("global_budget_s", 1800)))
    eng.GAME_TIMEOUT_S = int(os.environ.get("META_EVAL_GAME_TIMEOUT_S",
                                            budgets.get("game_timeout_s", 60)))
    scout_gps = int(os.environ.get("PASS12_SCOUT_GPS",
                                   cfg["stages"]["scout"]["games_per_seat"]))
    focused_gps = int(os.environ.get("PASS12_FOCUSED_GPS",
                                     cfg["stages"]["focused"]["games_per_seat"]))

    ac_name, ac_score = _registry_active_control()
    pinned = (cfg.get("active_control") or {}).get("name")
    drift = pinned and pinned != ac_name

    if not eng._cabt_available():
        rep = {"pass": "12", "status": "blocked", "reason": "cabt_unavailable",
               "disclaimer": DISCLAIMER}
        (OUT / "pass12_scout_results.json").write_text(json.dumps(rep, indent=2),
                                                       encoding="utf-8")
        print("BLOCKED: cabt unavailable")
        return 0

    start = time.time()

    def budget_left():
        return eng.GLOBAL_BUDGET_S - (time.time() - start)

    surrogates = build_surrogates(cfg)
    opponents = [s for s in surrogates if s["status"] == "ready"
                 and s["role"] != "diagnostic_only"]
    mirror = [s for s in surrogates if s["status"] == "ready"
              and s["role"] == "diagnostic_only"]
    opp_for_eval = opponents + mirror  # mirror runs but is excluded from meta score

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        candidates, notes = resolve_candidates(tmp, ac_name)

        # ---- Stage 1: scout ----
        scout = run_stage("scout", scout_gps, candidates, opp_for_eval, weights,
                          ac_name, mirror_key, budget_left)
        ac_adj_scout = None
        for cid, c in scout["per_candidate"].items():
            if c["role"] == "active_control":
                # active control's own adjusted WR vs external meta
                ext = {k: v for k, v in weights.items() if k != mirror_key}
                ac_adj_scout = weighted_meta_score(c["per_archetype"], ext)
        scout_rows = candidate_metrics(scout, opp_for_eval, weights, mirror_key,
                                       ac_adj_scout, min_games)
        scout_rows = label_rows(scout_rows, ac_adj_scout, min_games, gate)

        scout_meta = {
            "pass": "12", "stage": "scout", "generated_at": time.time(),
            "disclaimer": DISCLAIMER, "active_control": ac_name,
            "active_control_public_score": ac_score, "registry_drift": bool(drift),
            "evaluation_weights": weights, "mirror_key": mirror_key,
            "opponents": [o["key"] for o in opponents],
            "candidate_notes": notes, "elapsed_s": round(time.time() - start, 1),
            "budget_exhausted": budget_left() <= 0,
            "per_candidate": scout["per_candidate"], "ranking": scout_rows,
        }
        (OUT / "pass12_scout_results.json").write_text(
            json.dumps(scout_meta, indent=2, default=str), encoding="utf-8")
        (OUT / "pass12_scout_results.md").write_text(
            md_stage("Pass 12 — scout evaluation", scout_rows, opponents, scout,
                     [f"- active control: **{ac_name}** (public {ac_score})",
                      f"- registry drift vs config pin: {bool(drift)}",
                      f"- opponents: {', '.join(o['key'] for o in opponents)}",
                      f"- scout games/seat: {scout_gps}",
                      f"- elapsed: {scout_meta['elapsed_s']}s"]),
            encoding="utf-8")
        write_matrix(scout, opponents, OUT / "pass12_matchup_matrix.csv")
        (OUT / "pass12_candidate_metrics.json").write_text(
            json.dumps({"stage": "scout", "active_control_adj": ac_adj_scout,
                        "rows": scout_rows}, indent=2, default=str), encoding="utf-8")

        # ---- select focused set ----
        cand_rows = [r for r in scout_rows if r["role"] == "candidate"]
        cand_rows.sort(key=lambda r: (r["weighted_meta_score"] is None,
                                      -(r["weighted_meta_score"] or -1)))
        top_n = int(cfg["stages"]["focused"].get("select_top_candidates", 4))
        chosen_ids = [r["candidate"] for r in cand_rows[:top_n]]
        # best transfer + best chaos (chaos likely none)
        for grp in ("transfer", "chaos"):
            g_rows = [r for r in cand_rows if r["group"] == grp]
            if g_rows and g_rows[0]["candidate"] not in chosen_ids:
                chosen_ids.append(g_rows[0]["candidate"])
        focus_cands = [c for c in candidates
                       if c["role"] == "active_control" or c["id"] in chosen_ids]

        # ---- Stage 2: focused ----
        focused = run_stage("focused", focused_gps, focus_cands, opp_for_eval,
                            weights, ac_name, mirror_key, budget_left)
        ac_adj_foc = None
        for cid, c in focused["per_candidate"].items():
            if c["role"] == "active_control":
                ext = {k: v for k, v in weights.items() if k != mirror_key}
                ac_adj_foc = weighted_meta_score(c["per_archetype"], ext)
        foc_rows = candidate_metrics(focused, opp_for_eval, weights, mirror_key,
                                     ac_adj_foc, min_games)
        foc_rows = label_rows(foc_rows, ac_adj_foc, min_games, gate)

        focused_meta = {
            "pass": "12", "stage": "focused", "generated_at": time.time(),
            "disclaimer": DISCLAIMER, "active_control": ac_name,
            "active_control_adj": ac_adj_foc, "evaluation_weights": weights,
            "mirror_key": mirror_key, "focused_set": chosen_ids,
            "focused_games_per_seat": focused_gps,
            "elapsed_s": round(time.time() - start, 1),
            "budget_exhausted": budget_left() <= 0,
            "per_candidate": focused["per_candidate"], "ranking": foc_rows,
        }
        (OUT / "pass12_focused_results.json").write_text(
            json.dumps(focused_meta, indent=2, default=str), encoding="utf-8")
        (OUT / "pass12_focused_results.md").write_text(
            md_stage("Pass 12 — focused evaluation", foc_rows, opponents, focused,
                     [f"- active control: **{ac_name}** (adj {ac_adj_foc})",
                      f"- focused set: {', '.join(chosen_ids) or 'none'}",
                      f"- focused games/seat: {focused_gps}",
                      f"- elapsed: {focused_meta['elapsed_s']}s"]),
            encoding="utf-8")
        write_matrix(focused, opponents, OUT / "pass12_focused_matchup_matrix.csv")

        # ---- ranking + promotion gate + dry-run queue ----
        ranking = sorted(
            [r for r in foc_rows if r["role"] == "candidate"],
            key=lambda r: (r["weighted_meta_score"] is None,
                           -(r["weighted_meta_score"] or -1)))
        promotable = [r for r in ranking if r["label"] == "promotable"]
        max_queue = int(gate.get("max_dry_run_queue", 1))
        queue = promotable[:max_queue]
        dry_run = {
            "pass": "12", "disclaimer": DISCLAIMER,
            "upload_performed": False,
            "max_dry_run_queue": max_queue,
            "queued": [{"candidate": r["candidate"],
                        "weighted_meta_score": r["weighted_meta_score"],
                        "adjusted_win_rate": r["adjusted_win_rate"],
                        "wilson80": r["wilson80"]} for r in queue],
            "queued_count": len(queue),
            "reason": ("No candidate met the promotion gate (>= "
                       f"{min_games} games, 80% lower bound > 0.50, beats the active "
                       "control, not mirror-overfit)." if not queue else
                       "Queued for MANUAL dry-run review only; NOT uploaded."),
            "note": "Surrogate eval is directional only; queueing never uploads.",
        }
        (OUT / "pass12_dry_run_queue.json").write_text(
            json.dumps(dry_run, indent=2, default=str), encoding="utf-8")

        rank_out = {
            "pass": "12", "disclaimer": DISCLAIMER, "active_control": ac_name,
            "active_control_adj": ac_adj_foc, "ranking": ranking,
            "upload_ready": False, "dry_run_queue": dry_run["queued"],
            "reason_not_upload_ready": (
                "Surrogate eval is DIRECTIONAL only and the dominant opponent family "
                "is provisional; no candidate is promotable on this evidence. No "
                "upload/submit is performed in any case."),
        }
        (OUT / "pass12_ranking.json").write_text(
            json.dumps(rank_out, indent=2, default=str), encoding="utf-8")
        (OUT / "pass12_ranking.md").write_text(
            md_stage("Pass 12 — candidate ranking (focused, directional)",
                     ranking, opponents, focused,
                     [f"- active control: **{ac_name}** (adj {ac_adj_foc})",
                      f"- upload ready: **False**; dry-run queued: {len(queue)} "
                      f"(max {max_queue}); upload performed: **False**"]),
            encoding="utf-8")

    print(f"scout candidates={len(scout['per_candidate'])} "
          f"focused_set={chosen_ids} queued={len(queue)} "
          f"elapsed={round(time.time()-start,1)}s")
    for p in ["pass12_scout_results.json", "pass12_matchup_matrix.csv",
              "pass12_candidate_metrics.json", "pass12_focused_results.json",
              "pass12_focused_matchup_matrix.csv", "pass12_ranking.json",
              "pass12_dry_run_queue.json"]:
        print(f"  -> data/experiments/{p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
