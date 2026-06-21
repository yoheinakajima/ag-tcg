#!/usr/bin/env python3
"""PASS 46C — frame-persisting diagnostic builder (READ-ONLY / LOCAL ONLY).

Consumes the persisted Pass-46C decision-frame traces (written by
``run_pass46c_trace_games.py``) and produces honest diagnostic artifacts:
  * Part D — extractor compatibility validation (the Pass-46B extractor decodes the
    persisted trace format with NO extension).
  * Part E — turn-planning behavior metrics v0 (observable counts only; unsupported
    damage/lethal/missed-KO/Boss-gust/spread claims stay explicit).
  * Part F — internal-vs-public-reference behavioral comparison (local self-play).
  * Part G — strategy decision + 10-section report.

NEVER mutates production Object Storage, runs a tick, writes any tournament ledger /
events.jsonl, emits a lifecycle/generation/promotion/submission event, or touches
root ``main.py`` / ``deck.csv``. Read-only over local trace files + local artifacts.

Run: ``python3 scripts/build_pass46c_diagnostic.py``  (idempotent).
"""
from __future__ import annotations

import hashlib
import json
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.analysis import turn_planning as tp  # noqa: E402

EXP = REPO / "data" / "experiments"
REPORTS = REPO / "data" / "reports"
TRACES = EXP / "pass46c_traces"
MANIFEST = EXP / "pass46c_trace_manifest.json"
PREFLIGHT = EXP / "pass46c_safety_preflight.json"

CAVEATS = [
    "READ-ONLY / LOCAL diagnostic: production Object Storage was not mutated.",
    "No production tick executed; the deployed daemon is unchanged and still soaking.",
    "No candidate generation, promotion, retirement, quarantine, queue, or upload occurred.",
    "No tournament ledger / events.jsonl write occurred; traces live in a diagnostic-only dir.",
    "Public references are BENCHMARK-ONLY opponents, never candidates/parents/sources.",
    "Game outcomes here are LOCAL self-play diagnostics, NOT Kaggle leaderboard scores.",
    "Turn metrics are observable counts only; damage / lethal / missed-KO / Boss-gust / "
    "spread remain explicitly unsupported (not inferable from the trace).",
]
REFERENCE_ROLES = {"public_reference"}


def write_pair(stem: str, data: dict, md_title: str, md_body: str) -> None:
    (EXP / f"{stem}.json").write_text(json.dumps(data, indent=2, default=str) + "\n",
                                      encoding="utf-8")
    head = ("# " + md_title + "\n\n_Pass 46C — read-only / local frame-persisting "
            "diagnostic. Local self-play only; NOT a Kaggle strength claim. "
            "No generation / promotion / upload / tick._\n\n")
    caveat = "## Caveats\n" + "".join(f"- {c}\n" for c in CAVEATS) + "\n"
    (EXP / f"{stem}.md").write_text(head + caveat + md_body + "\n", encoding="utf-8")


def _load_traces() -> list[dict]:
    return [tp.read_trace(p) for p in sorted(TRACES.glob("*.json.gz"))]


# ============================================================= Part D
def part_d(traces: list[dict]) -> dict:
    per_game = []
    extension_needed = False
    for t in traces:
        fmt = tp.detect_format(t)
        frames = tp.iter_decision_frames(t)
        by_seat = {0: 0, 1: 0}
        for f in frames:
            if f.acting_player in by_seat:
                by_seat[f.acting_player] += 1
        recomputed = hashlib.sha256(
            json.dumps(t.get("steps", []), sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        sha_ok = recomputed == t.get("steps_sha256")
        decodable = fmt == tp.FMT_KAGGLE_REPLAY and (len(frames) > 0 or not t.get("ok"))
        if t.get("ok") and fmt != tp.FMT_KAGGLE_REPLAY:
            extension_needed = True
        per_game.append({
            "game_id": t.get("id"), "ok": t.get("ok"),
            "detected_format": fmt,
            "expected_format": tp.FMT_KAGGLE_REPLAY,
            "format_ok": fmt == tp.FMT_KAGGLE_REPLAY,
            "n_frames": len(frames),
            "frames_seat0": by_seat[0], "frames_seat1": by_seat[1],
            "steps_sha256_roundtrip_ok": sha_ok,
            "decodable_by_pass46b_extractor": decodable,
        })
    ok_games = [g for g in per_game if g["ok"]]
    all_decodable = all(g["decodable_by_pass46b_extractor"] for g in ok_games)
    all_sha_ok = all(g["steps_sha256_roundtrip_ok"] for g in per_game)
    all_have_frames = all(g["n_frames"] > 0 for g in ok_games)
    data = {
        "pass": "46c", "part": "D", "read_only": True,
        "extractor_module": "ptcg_activegraph.analysis.turn_planning",
        "extractor_extension_needed": extension_needed,
        "n_traces": len(traces), "n_ok": len(ok_games),
        "all_ok_traces_decodable": all_decodable,
        "all_steps_sha256_roundtrip_ok": all_sha_ok,
        "all_ok_traces_have_frames": all_have_frames,
        "per_game": per_game,
    }
    md = ("The Pass-46B extractor decodes the persisted Pass-46C trace format "
          f"(`{tp.FMT_KAGGLE_REPLAY}`) with **no extension** "
          f"(`extractor_extension_needed = {extension_needed}`).\n\n"
          "| game | fmt ok | frames | seat0 | seat1 | sha ok | decodable |\n"
          "|---|---|---|---|---|---|---|\n")
    for g in per_game:
        md += (f"| {g['game_id'].split('_vs_')[0][:34]} | {g['format_ok']} | "
               f"{g['n_frames']} | {g['frames_seat0']} | {g['frames_seat1']} | "
               f"{g['steps_sha256_roundtrip_ok']} | "
               f"{g['decodable_by_pass46b_extractor']} |\n")
    write_pair("pass46c_trace_extractor_validation", data,
               "Pass 46C — Part D: extractor compatibility", md)
    return data


# ============================================================= Part E
_AGG_SUM = ["turns_ending_without_attack", "main_end_with_alternatives",
            "search_action_count", "discard_action_count", "retreat_switch_count",
            "ability_use_count", "dead_low_action_turns", "n_frames"]


def _summaries_by_candidate(traces: list[dict]) -> dict:
    """Map candidate_id -> list of per-(game,seat) TurnPlanSummary dicts + role."""
    out: dict[str, dict] = {}
    for t in traces:
        if not t.get("ok"):
            continue
        frames = tp.iter_decision_frames(t)
        seat_to_cand = {0: (t["candidate_a"], t["role_a"]),
                        1: (t["candidate_b"], t["role_b"])}
        for seat, (cid, role) in seat_to_cand.items():
            s = tp.summarize_turn_plan(frames, acting_player=seat, game_id=t["id"])
            rec = s.to_dict()
            rec["_game_id"] = t["id"]
            rec["_seat"] = seat
            entry = out.setdefault(cid, {"role": role, "games": []})
            entry["games"].append(rec)
    return out


def _aggregate(games: list[dict]) -> dict:
    agg: dict = {"n_game_seats": len(games)}
    for k in _AGG_SUM:
        agg[k + "_total"] = sum(int(g.get(k) or 0) for g in games)
    fats = [g["first_attack_turn"] for g in games
            if isinstance(g.get("first_attack_turn"), int)]
    agg["first_attack_turn_min"] = min(fats) if fats else None
    agg["first_attack_turn_mean"] = round(statistics.mean(fats), 2) if fats else None
    agg["game_seats_with_any_attack"] = len(fats)
    benches = [g["setup_bench_count"] for g in games
               if isinstance(g.get("setup_bench_count"), int)]
    agg["setup_bench_count_mean"] = round(statistics.mean(benches), 2) if benches else None
    fkos = [g["first_ko_turn"] for g in games if isinstance(g.get("first_ko_turn"), int)]
    agg["first_ko_or_prize_turn_min"] = min(fkos) if fkos else None
    return agg


def part_e(traces: list[dict]) -> dict:
    by_cand = _summaries_by_candidate(traces)
    candidates = {}
    for cid, entry in by_cand.items():
        candidates[cid] = {
            "role": entry["role"],
            "aggregate": _aggregate(entry["games"]),
            "per_game_seat": entry["games"],
        }
    data = {
        "pass": "46c", "part": "E", "read_only": True,
        "metric_basis": "observable decision-frame counts / family classifications / "
                        "observable count deltas only",
        "unsupported_claims": tp.unsupported_flags(),
        "candidates": candidates,
    }
    md = ("Turn-planning behavior metrics v0 (observable only; unsupported claims "
          "preserved). One row per candidate aggregated across its game-seats.\n\n"
          "| candidate | role | seats | frames | 1st atk (min) | end-no-atk | "
          "search | ability | retreat | dead/low |\n"
          "|---|---|---|---|---|---|---|---|---|---|\n")
    for cid, c in sorted(candidates.items()):
        a = c["aggregate"]
        md += (f"| {cid[:30]} | {c['role']} | {a['n_game_seats']} | "
               f"{a['n_frames_total']} | {a['first_attack_turn_min']} | "
               f"{a['turns_ending_without_attack_total']} | "
               f"{a['search_action_count_total']} | {a['ability_use_count_total']} | "
               f"{a['retreat_switch_count_total']} | "
               f"{a['dead_low_action_turns_total']} |\n")
    write_pair("pass46c_behavior_metrics", data,
               "Pass 46C — Part E: turn-planning behavior metrics v0", md)
    return data


# ============================================================= Part F
def _group_aggregate(by_cand: dict, predicate) -> dict:
    games: list[dict] = []
    members: list[str] = []
    for cid, entry in by_cand.items():
        if predicate(entry["role"]):
            games.extend(entry["games"])
            members.append(cid)
    agg = _aggregate(games)
    agg["members"] = sorted(members)
    return agg


def _per_frame_rates(agg: dict) -> dict:
    n = agg.get("n_frames_total") or 0
    if not n:
        return {}
    return {
        "end_no_attack_per_frame": round(agg["turns_ending_without_attack_total"] / n, 4),
        "search_per_frame": round(agg["search_action_count_total"] / n, 4),
        "ability_per_frame": round(agg["ability_use_count_total"] / n, 4),
        "retreat_per_frame": round(agg["retreat_switch_count_total"] / n, 4),
        "dead_low_per_frame": round(agg["dead_low_action_turns_total"] / n, 4),
        "end_with_alternatives_per_frame":
            round(agg["main_end_with_alternatives_total"] / n, 4),
    }


def part_f(traces: list[dict]) -> dict:
    by_cand = _summaries_by_candidate(traces)
    internal = _group_aggregate(by_cand, lambda r: r not in REFERENCE_ROLES)
    reference = _group_aggregate(by_cand, lambda r: r in REFERENCE_ROLES)
    data = {
        "pass": "46c", "part": "F", "read_only": True,
        "comparison": "internal decks (candidates + parents) vs public references — "
                      "LOCAL self-play diagnostic, NOT a Kaggle strength claim",
        "internal": {"aggregate": internal, "rates": _per_frame_rates(internal)},
        "public_reference": {"aggregate": reference,
                             "rates": _per_frame_rates(reference)},
        "observable_deltas": {
            "first_attack_turn_min_internal": internal.get("first_attack_turn_min"),
            "first_attack_turn_min_reference": reference.get("first_attack_turn_min"),
            "first_attack_turn_mean_internal": internal.get("first_attack_turn_mean"),
            "first_attack_turn_mean_reference": reference.get("first_attack_turn_mean"),
        },
        "interpretation_caveat":
            "Differences here are observable behavioral tendencies in local self-play, "
            "not evidence of Kaggle-leaderboard strength. Small n; directional only.",
        "unsupported_claims": tp.unsupported_flags(),
    }
    ri, rr = data["internal"]["rates"], data["public_reference"]["rates"]
    md = ("Internal decks vs public references — observable behavioral tendencies in "
          "local self-play. Directional only (small n); NOT a strength claim.\n\n"
          "| metric (per-frame) | internal | public_reference |\n|---|---|---|\n")
    for k in sorted(set(ri) | set(rr)):
        md += f"| {k} | {ri.get(k)} | {rr.get(k)} |\n"
    md += (f"\nFirst-attack turn (min / mean): internal "
           f"{internal.get('first_attack_turn_min')} / "
           f"{internal.get('first_attack_turn_mean')}; reference "
           f"{reference.get('first_attack_turn_min')} / "
           f"{reference.get('first_attack_turn_mean')}.\n")
    write_pair("pass46c_reference_comparison", data,
               "Pass 46C — Part F: internal-vs-reference comparison", md)
    return data


# ============================================================= Part G
def part_g(preflight: dict, manifest: dict, d: dict, e: dict, f: dict) -> dict:
    ready = bool(
        preflight.get("all_ok")
        and manifest.get("complete")
        and manifest.get("no_upload") and not manifest.get("production_mutated")
        and not manifest.get("events_written")
        and d.get("all_ok_traces_decodable")
        and d.get("all_steps_sha256_roundtrip_ok")
        and d.get("all_ok_traces_have_frames")
        and not d.get("extractor_extension_needed")
        and bool(e.get("candidates"))
        and bool(f.get("internal")))
    decision = ("reference_trace_diagnostic_ready_soak_continue" if ready
                else "reference_trace_diagnostic_incomplete_hold")
    data = {
        "pass": "46c", "part": "G", "read_only": True, "production_mutated": False,
        "tick_executed": False, "events_written": False, "no_upload": True,
        "decision": decision, "ready": ready,
        "gates": {
            "safety_all_ok": bool(preflight.get("all_ok")),
            "panel_complete": bool(manifest.get("complete")),
            "n_traces_ok": manifest.get("n_ok"),
            "traces_decodable": bool(d.get("all_ok_traces_decodable")),
            "steps_hash_roundtrip_ok": bool(d.get("all_steps_sha256_roundtrip_ok")),
            "frames_present": bool(d.get("all_ok_traces_have_frames")),
            "extractor_extension_needed": bool(d.get("extractor_extension_needed")),
            "metrics_computed": bool(e.get("candidates")),
            "comparison_computed": bool(f.get("internal")),
        },
        "next_pass_actions": [
            "Keep the production Scheduled Deployment soaking (no change this pass).",
            "Re-run this LOCAL trace lane on demand to refresh decision-frame traces.",
            "Future pass: widen the panel and add per-archetype frame comparisons.",
        ],
    }
    md = (f"**Decision: `{decision}`** (ready = {ready}).\n\n## Gates\n"
          + "".join(f"- `{k}`: {v}\n" for k, v in data["gates"].items())
          + "\n## Next-pass actions\n"
          + "".join(f"- {a}\n" for a in data["next_pass_actions"]))
    write_pair("pass46c_strategy_decision", data,
               "Pass 46C — Part G: strategy decision", md)
    return data


# ============================================================= report (10 sections)
def write_report(preflight: dict, manifest: dict, d: dict, e: dict,
                 f: dict, g: dict) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    L: list[str] = []
    L.append("# Pass 46C — Frame-Persisting Diagnostic Lane v0\n")
    L.append("_READ-ONLY / LOCAL diagnostic produced while the production Scheduled "
             "Deployment soaks. No prod mutation, no tick, no lifecycle/generation/"
             "promotion/upload, no forbidden events. Local self-play diagnostics are "
             "NOT Kaggle leaderboard scores._\n")

    L.append("## 1. Summary & Decision")
    L.append(f"- Decision: **`{g['decision']}`** (ready = {g['ready']}).")
    L.append(f"- Built a bounded, reusable LOCAL trace runner and played "
             f"**{manifest.get('n_ok')}/{manifest.get('n_games_planned')}** cabt games, "
             f"persisting full decision-frame traces decodable by the Pass-46B extractor.")
    L.append("- This lane is diagnostic-only; the deployed daemon is unchanged.\n")

    L.append("## 2. Scope & Safety")
    L.append(f"- Part-A stop-gate `all_ok = {preflight.get('all_ok')}`; references "
             f"absent from prod pool ({preflight.get('refs_in_pool')}) and worklist "
             f"({preflight.get('refs_in_worklist')}).")
    L.append(f"- Root immutable: `main.py` sha `{preflight.get('root_main_sha256')}`, "
             f"`deck.csv` sha `{preflight.get('root_deck_sha256')}`.")
    L.append(f"- No forbidden events in prod ledger: "
             f"{preflight.get('forbidden_events_in_prod_ledger')}; "
             f"auto_submit falsy; deployment still points to the production tick.\n")

    L.append("## 3. Trace Runner Design")
    L.append("- `scripts/run_pass46c_trace_games.py` orchestrates; "
             "`scripts/_pass46c_trace_worker.py` plays ONE game per subprocess.")
    L.append(f"- Each game runs in a hard-timeout subprocess "
             f"(`game_timeout_s = {manifest.get('game_timeout_s')}`, "
             f"`game_retries = {manifest.get('game_retries')}`) because native "
             "open_spiel C hangs cannot be interrupted in-process.")
    L.append("- The runner is **resumable + budgeted**: it skips already-OK traces, "
             "stops at a per-invocation wall-clock budget, and rebuilds the manifest "
             "from persisted traces — so it tolerates being killed mid-run.\n")

    L.append("## 4. Match Panel")
    L.append("| group | a (seat0) | b | kind | ok | steps | a_outcome |\n"
             "|---|---|---|---|---|---|---|")
    for r in manifest.get("traces", []):
        L.append(f"| {r['group']} | {r['candidate_a']} | {r['candidate_b']} | "
                 f"{r['matchup_kind']} | {r['ok']} | {r['n_steps']} | {r['a_outcome']} |")
    L.append(f"\n- Resolved parents: "
             f"{manifest.get('panel_parents_resolved')}.\n")

    L.append("## 5. Trace Persistence & Manifest")
    L.append(f"- Traces persisted (gzip) under `{manifest.get('trace_dir')}`; "
             f"`no_upload = {manifest.get('no_upload')}`, "
             f"`events_written = {manifest.get('events_written')}`, "
             f"`object_storage_mutated = {manifest.get('object_storage_mutated')}`.")
    L.append("- Each trace stores the full `env.steps` decision frames plus a "
             "`steps_sha256` integrity hash and matchup metadata.\n")

    L.append("## 6. Extractor Compatibility (Part D)")
    L.append(f"- The Pass-46B extractor decodes every OK trace as "
             f"`{tp.FMT_KAGGLE_REPLAY}` with **no extension** "
             f"(`extractor_extension_needed = {d.get('extractor_extension_needed')}`).")
    L.append(f"- `all_ok_traces_decodable = {d.get('all_ok_traces_decodable')}`, "
             f"`all_steps_sha256_roundtrip_ok = {d.get('all_steps_sha256_roundtrip_ok')}`, "
             f"`all_ok_traces_have_frames = {d.get('all_ok_traces_have_frames')}`.\n")

    L.append("## 7. Behavior Metrics v0 (Part E)")
    L.append("| candidate | role | seats | frames | 1st atk (min) | end-no-atk | "
             "search | ability | retreat |\n|---|---|---|---|---|---|---|---|---|")
    for cid, c in sorted(e.get("candidates", {}).items()):
        a = c["aggregate"]
        L.append(f"| {cid} | {c['role']} | {a['n_game_seats']} | {a['n_frames_total']} "
                 f"| {a['first_attack_turn_min']} | "
                 f"{a['turns_ending_without_attack_total']} | "
                 f"{a['search_action_count_total']} | {a['ability_use_count_total']} | "
                 f"{a['retreat_switch_count_total']} |")
    L.append("")

    L.append("## 8. Reference Comparison (Part F)")
    ri, rr = f["internal"]["rates"], f["public_reference"]["rates"]
    L.append("| metric (per-frame) | internal | public_reference |\n|---|---|---|")
    for k in sorted(set(ri) | set(rr)):
        L.append(f"| {k} | {ri.get(k)} | {rr.get(k)} |")
    L.append(f"\n- First-attack turn (mean): internal "
             f"{f['internal']['aggregate'].get('first_attack_turn_mean')} vs reference "
             f"{f['public_reference']['aggregate'].get('first_attack_turn_mean')} "
             "(directional only; small n).\n")

    L.append("## 9. Honesty & Unsupported Claims")
    L.append("- The following remain explicitly **unsupported / not inferable from the "
             "trace** and are NOT claimed anywhere: "
             + ", ".join(sorted(tp.unsupported_flags().keys())) + ".")
    L.append("- KO/prize timing is approximated from observable opponent "
             "prize-remaining deltas only; exact KO and damage are not decoded.")
    L.append("- Internal/benchmark outcomes are LOCAL self-play, NOT Kaggle scores.\n")

    L.append("## 10. Limitations & Next Steps")
    L.append("- Small bounded panel (12 games); differences are directional, not "
             "statistically powered.")
    L.append("- Frame metrics are behavioral tendencies, not strength; no promotion or "
             "submission is implied or taken.")
    L.append("- Next: keep prod soaking; re-run this lane on demand; widen the panel and "
             "add per-archetype frame comparisons in a future pass.\n")

    (REPORTS / "pass46c_frame_persisting_diagnostic_report.md").write_text(
        "\n".join(L), encoding="utf-8")


def main() -> int:
    if not MANIFEST.exists() or not PREFLIGHT.exists():
        raise SystemExit("missing prerequisites: run scripts/run_pass46c_trace_games.py first")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    traces = _load_traces()
    d = part_d(traces)
    e = part_e(traces)
    f = part_f(traces)
    g = part_g(preflight, manifest, d, e, f)
    write_report(preflight, manifest, d, e, f, g)
    print(json.dumps({"decision": g["decision"], "ready": g["ready"],
                      "n_traces": len(traces),
                      "extractor_extension_needed": d["extractor_extension_needed"],
                      "all_decodable": d["all_ok_traces_decodable"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
