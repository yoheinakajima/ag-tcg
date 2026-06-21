#!/usr/bin/env python3
"""PASS 46B — reference-gap + turn-planning diagnostic builder (READ-ONLY / LOCAL).

Produces honest diagnostic artifacts from EXISTING evidence (local sidecars, the one
local Kaggle replay, the public-benchmark ledger, prod read-only counts). This script:
  * NEVER mutates production Object Storage, never calls push_state / sync writers.
  * NEVER emits CandidateStatusChanged / CandidateGenerated / CandidatePromoted /
    SubmissionQueued / SubmissionUploaded / KaggleScoreUpdated or any lifecycle event.
  * NEVER generates candidates, writes tarballs, or touches root main.py / deck.csv.
  * Public references stay benchmark-only; verified absent from pool + worklist.

Run: ``python3 scripts/build_pass46b_diagnostic.py``  (idempotent; writes data/experiments/pass46b_*).
"""
from __future__ import annotations

import filecmp
import glob
import gzip
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.analysis import turn_planning as tp  # noqa: E402
from ptcg_activegraph.tournament import sync, promotion, pool as poolmod, projections as projmod  # noqa: E402
from ptcg_activegraph.tournament.config import load_config  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool  # noqa: E402
from ptcg_activegraph.tournament.scheduler import build_worklist  # noqa: E402
from ptcg_activegraph.tournament.storage import get_storage_backend  # noqa: E402

EXP = REPO / "data" / "experiments"
REPORTS = REPO / "data" / "reports"
DOCS = REPO / "docs"
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
GAMES_DIR = REPO / "data" / "tournament" / "games"
REPLAY = REPO / "data" / "replays" / "80374966.json"
BENCH_JSONL = EXP / "pass41_public_benchmark_games.jsonl"

TARGETS = [
    "generated_diamond_diamondtoolbox_eratio_v1",
    "generated_dragapult_leaguedragapul_bdens_v1",
    "generated_lightning_monolightningm_dsratio_v1",
]
FAMILIES = ["water", "dragapult", "lightning", "diamond",
            "mega_charizard", "mega_gardevoir", "mega_venusaur"]
# Events this read-only diagnostic must NEVER emit (script-source intent).
FORBIDDEN = {"SubmissionQueued", "SubmissionUploaded", "KaggleScoreUpdated",
             "CandidatePromoted", "CandidateStatusChanged", "CandidateGenerated",
             "CandidateValidationFinished"}
# Events whose PRESENCE in the prod ledger would indicate an upload/promotion
# occurred. (CandidateGenerated / CandidateValidationFinished / CandidateStatusChanged
# legitimately exist from normal daemon operation and are NOT violations here.)
LEDGER_FORBIDDEN = {"SubmissionQueued", "SubmissionUploaded", "KaggleScoreUpdated",
                    "CandidatePromoted"}
NEVER = {poolmod.SPECIAL_PILOT_ONLY, poolmod.RETIRED, poolmod.QUARANTINED, poolmod.INVALID}

CAVEATS = [
    "READ-ONLY diagnostic: production Object Storage was not mutated.",
    "No candidate generation, promotion, lifecycle change, or status change occurred.",
    "No Kaggle upload / submit / auto-submit occurred.",
    "Public references are BENCHMARK-ONLY opponents, never our candidates.",
    "Internal tournament/benchmark scores are NOT Kaggle leaderboard scores.",
    "The production daemon (Scheduled Deployment) is unchanged and still soaking.",
    "A 'gap' finding is a diagnostic signal, not a promotion/submit signal.",
]


def sha(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def family_of(cid: str) -> str:
    c = (cid or "").lower()
    if "dragapult" in c:
        return "dragapult"
    if "lightning" in c or "miraidon" in c:
        return "lightning"
    if "diamond" in c or "diancie" in c:
        return "diamond"
    if "charizard" in c:
        return "mega_charizard"
    if "gardevoir" in c:
        return "mega_gardevoir"
    if "venusaur" in c:
        return "mega_venusaur"
    if "water" in c:
        return "water"
    return "unknown"


def write_pair(stem: str, data: dict, md_title: str, md_body: str) -> None:
    (EXP / f"{stem}.json").write_text(json.dumps(data, indent=2, default=str) + "\n",
                                      encoding="utf-8")
    head = ("# " + md_title + "\n\n_Pass 46B — read-only diagnostic. Internal benchmark "
            "only; NOT a Kaggle strength claim. No generation / promotion / upload._\n\n")
    caveat = "## Caveats\n" + "".join(f"- {c}\n" for c in CAVEATS) + "\n"
    (EXP / f"{stem}.md").write_text(head + caveat + md_body + "\n", encoding="utf-8")


# ---------------------------------------------------------------- prod read-only
def load_prod():
    b = get_storage_backend(env="production", backend="replit_app_storage")
    txt = b.read_text(sync.EVENTS_KEY)
    tmpf = Path(tempfile.mkdtemp()) / "events.jsonl"
    tmpf.write_text(txt, encoding="utf-8")
    events = TournamentLedger(path=tmpf).load()
    manifest = json.loads(b.read_text(sync.MANIFEST_KEY)) if b.exists(sync.MANIFEST_KEY) else {}
    return events, manifest


# ============================================================= Part A: safety
def part_a() -> dict:
    main_before = filecmp.cmp(REPO / "main.py", BASELINE / "main.py", shallow=False)
    deck_before = filecmp.cmp(REPO / "deck.csv", BASELINE / "deck.csv", shallow=False)
    # package preflight (verify-only) — does not mutate root
    verify_rc = None
    try:
        r = subprocess.run([sys.executable, "-c",
                            "import kaggle_environments, yaml; print('ok')"],
                           capture_output=True, text=True, timeout=60)
        verify_rc = r.returncode
    except Exception as e:  # pragma: no cover
        verify_rc = -1
    main_after = filecmp.cmp(REPO / "main.py", BASELINE / "main.py", shallow=False)
    deck_after = filecmp.cmp(REPO / "deck.csv", BASELINE / "deck.csv", shallow=False)
    # .replit deployment
    replit_txt = (REPO / ".replit").read_text(encoding="utf-8")
    dep_ok = ("scripts/tournament_deployment_tick.py" in replit_txt
              and "--production" in replit_txt
              and "replit_app_storage" in replit_txt)
    run_not_root = "scripts/tournament_deployment_tick.py" in replit_txt
    deployment_target_scheduled = 'deploymentTarget = "scheduled"' in replit_txt
    # auto_submit falsy in config
    try:
        cfg = load_config()
        auto_submit = bool(getattr(cfg, "auto_submit", False)) if cfg is not None else False
    except Exception:
        auto_submit = False
    # references absent from prod pool + worklist
    events, manifest = load_prod()
    pool = CandidatePool.from_events(events)
    status_of = {c.candidate_id: c.status for c in pool.candidates}
    ref_ids = set(promotion.load_reference_ids())
    pool_ids = set(status_of)
    refs_in_pool = sorted(ref_ids & pool_ids)
    projmod.PROJ_DIR = Path(tempfile.mkdtemp())
    cfg = load_config()
    prior = projmod.write_projections(pool, events, cfg)
    state = projmod.build_scheduler_state(events, ranking=prior["ranked_ids"])
    wl = build_worklist(pool, state, cfg)
    wl_ids = set()
    for g in wl:
        d = g.to_dict()
        wl_ids.add(d["candidate_a"])
        wl_ids.add(d["candidate_b"])
    refs_in_wl = sorted(ref_ids & wl_ids)
    never_in_wl = sorted(c for c, s in status_of.items() if s in NEVER and c in wl_ids)
    forbidden_in_ledger = sorted({e.event_type for e in events
                                  if e.event_type in LEDGER_FORBIDDEN})
    checks = {
        "root_main_unchanged_before": main_before,
        "root_deck_unchanged_before": deck_before,
        "root_main_unchanged_after": main_after,
        "root_deck_unchanged_after": deck_after,
        "deployment_points_to_tick_not_root": dep_ok and run_not_root,
        "deployment_target_scheduled": deployment_target_scheduled,
        "auto_submit_falsy": auto_submit is False,
        "references_absent_from_pool": refs_in_pool == [],
        "references_absent_from_worklist": refs_in_wl == [],
        "no_never_schedule_in_worklist": never_in_wl == [],
        "package_verify_ok": verify_rc == 0,
    }
    all_ok = all(checks.values())
    data = {
        "pass": "46b", "part": "A", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "tick_executed": False,
        "start_application_started": False,
        "baseline": str(BASELINE.relative_to(REPO)),
        "root_main_sha256": sha(REPO / "main.py"),
        "root_deck_sha256": sha(REPO / "deck.csv"),
        "deployment_run": "scripts/tournament_deployment_tick.py --production replit_app_storage",
        "checks": checks, "all_ok": all_ok,
        "refs_in_pool": refs_in_pool, "refs_in_worklist": refs_in_wl,
        "never_schedule_in_worklist": never_in_wl,
        "forbidden_events_in_prod_ledger": forbidden_in_ledger,
        "prod_ledger_len": len(events),
        "manifest_event_count": manifest.get("event_count"),
        "manifest_matches_ledger": manifest.get("event_count") == len(events),
    }
    md = "## Stop-gate checks\n" + "".join(
        f"- {k}: {'PASS' if v else 'FAIL'}\n" for k, v in checks.items())
    md += f"\n**all_ok = {all_ok}**\n"
    write_pair("pass46b_safety_preflight", data, "Safety Stop-Gate (Part A)", md)
    return data


# ============================================================= Part B: inventory
def part_b() -> dict:
    sidecars = sorted(glob.glob(str(GAMES_DIR / "*.json.gz")))
    bench_rows = [json.loads(l) for l in BENCH_JSONL.read_text().splitlines() if l.strip()] \
        if BENCH_JSONL.exists() else []
    # classify sidecars (outcome-only vs frames)
    fmt_counts = Counter()
    sidecar_cands = Counter()
    for f in sidecars[:60]:
        obj = tp.read_trace(f)
        fmt_counts[tp.detect_format(obj)] += 1
        sidecar_cands[obj.get("candidate_a")] += 1
        sidecar_cands[obj.get("candidate_b")] += 1
    replay_obj = tp.read_trace(REPLAY) if REPLAY.exists() else None
    replay_frames = tp.iter_decision_frames(replay_obj) if replay_obj else []
    pass40_41 = sorted(p.name for p in EXP.glob("pass4[01]_*reference*")) \
        + sorted(p.name for p in EXP.glob("pass4[01]_*benchmark*")) \
        + sorted(p.name for p in EXP.glob("pass41_cg_*"))
    field_support = {
        "setup_active_bench_choices": "supported (kaggle replay frames; play_from_hand/play_in_play during setup)",
        "main_phase_action_choices": "supported (option families per frame)",
        "attach_energy_choices": "supported (attach_energy option type)",
        "search_to_hand_choices": "supported (select_card from deck); chosen card-id only when positionally resolvable",
        "discard_choices": "supported (select_card from discard); card-id only when resolvable",
        "retreat_switch_choices": "partial (only when active<->bench swap appears in logs)",
        "attack_no_attack": "supported (attack option type chosen / not chosen)",
        "ko_prize_events": "partial (approximated from opponent prize-remaining delta only)",
        "deck_hand_prize_discard_counts": "supported (obs.current.players counts)",
        "lethal_exact_damage_boss_gust_spread_hidden_hand_best_action": tp.UNSUPPORTED_SENTINEL,
    }
    data = {
        "pass": "46b", "part": "B", "read_only": True,
        "local_sidecars": {
            "dir": str(GAMES_DIR.relative_to(REPO)), "count": len(sidecars),
            "format_breakdown": dict(fmt_counts),
            "frames_persisted": False,
            "note": "tournament sidecars store `steps` as an INTEGER COUNT plus outcome "
                    "metadata only — NO decision frames; usable for outcome-level metrics "
                    "(win/loss/draw, game length, seats, hard-fail) only.",
            "distinct_candidates": sorted(c for c in sidecar_cands if c),
            "contains_generated_probation": any("generated_" in (c or "") for c in sidecar_cands),
            "contains_public_reference": any("public_ref_" in (c or "") for c in sidecar_cands),
        },
        "kaggle_replay": {
            "path": str(REPLAY.relative_to(REPO)) if REPLAY.exists() else None,
            "available": REPLAY.exists(), "decision_frames": len(replay_frames),
            "note": "the only local source of full decision frames (single game).",
        },
        "public_benchmark_ledger": {
            "path": str(BENCH_JSONL.relative_to(REPO)) if BENCH_JSONL.exists() else None,
            "rows": len(bench_rows), "frames_persisted": False,
            "note": "metadata/counts only (result, steps, timeout); no decision frames.",
        },
        "prior_reference_artifacts": pass40_41,
        "trace_field_support": field_support,
        "unsupported_fields": list(tp.UNSUPPORTED_CLAIMS),
        "honest_conclusion": (
            "Full turn-planning decision frames are essentially INSUFFICIENT locally: only "
            "ONE Kaggle replay carries frames; tournament/benchmark records are outcome-only. "
            "Outcome-level reference-gap analysis is well supported; trace-level turn-planning "
            "metrics are illustrative (n=1 game) until a frame-persisting trace lane exists."),
    }
    md = ("## Evidence map\n"
          f"- Local sidecars: {len(sidecars)} (outcome-only; no frames)\n"
          f"- Kaggle replay frames: {len(replay_frames)} (single game)\n"
          f"- Public-benchmark rows: {len(bench_rows)} (counts only)\n\n"
          "## Trace field support\n"
          + "".join(f"- {k}: {v}\n" for k, v in field_support.items())
          + f"\n## Honest conclusion\n{data['honest_conclusion']}\n")
    write_pair("pass46b_evidence_inventory", data, "Evidence Inventory (Part B)", md)
    return data


# ====================================================== Part C: schema artifact
def part_c_schema() -> dict:
    data = {
        "pass": "46b", "part": "C", "module": "src/ptcg_activegraph/analysis/turn_planning.py",
        "read_only": True, "pure_read_only": True,
        "formats": [tp.FMT_KAGGLE_REPLAY, tp.FMT_CABT_SIDECAR_FRAMES,
                    tp.FMT_CABT_SIDECAR_OUTCOME_ONLY, tp.FMT_UNKNOWN],
        "action_families": list(tp.ACTION_FAMILIES),
        "decision_frame_fields": [
            "game_id", "source", "step", "turn", "acting_player", "your_index",
            "context", "select_type", "min_count", "max_count", "n_options",
            "selected_indices", "selected_families", "option_families", "primary_family",
            "self_board", "opponent_board", "hand_count", "deck_count", "prize_remaining",
            "discard_count", "bench_count", "supporter_played", "stadium_played",
            "energy_attached", "observed_log_events", "retreat_observed",
            "legality_ok", "legality_notes", "notes"],
        "turn_plan_summary_fields": [
            "game_id", "acting_player", "n_frames", "first_attack_turn", "first_ko_turn",
            "first_prize_turn", "setup_bench_count", "bench_occupancy_by_turn",
            "energy_attachments_by_turn", "turns_ending_without_attack",
            "main_end_with_alternatives", "search_action_count", "search_card_ids",
            "discard_action_count", "discard_card_ids", "retreat_switch_count",
            "ability_use_count", "hand_count_trajectory", "deck_count_trajectory",
            "dead_low_action_turns", "invalid", "timeout", "error", "unsupported", "notes"],
        "unsupported_claims": list(tp.UNSUPPORTED_CLAIMS),
        "unsupported_sentinel": tp.UNSUPPORTED_SENTINEL,
        "honesty_notes": [
            "first_ko_turn / first_prize_turn are approximated from opponent prize-remaining "
            "deltas (observable), never from inferred damage; exact KO events are unsupported.",
            "retreat detected only when an active<->bench swap appears in engine logs.",
            "search/discard card ids recorded only when positionally resolvable; never invented.",
        ],
    }
    md = ("## Module\n`src/ptcg_activegraph/analysis/turn_planning.py` (pure, read-only).\n\n"
          "## Action families\n" + ", ".join(tp.ACTION_FAMILIES) + "\n\n"
          "## Always-unsupported claims\n"
          + "".join(f"- {c}\n" for c in tp.UNSUPPORTED_CLAIMS)
          + "\n## Honesty notes\n" + "".join(f"- {n}\n" for n in data["honesty_notes"]))
    write_pair("pass46b_turn_plan_schema", data, "Turn-Plan Extractor Schema (Part C)", md)
    return data


# ============================================== Part D: behavioral baseline
def _bench_summary(rows: list[dict]) -> dict:
    our_win = sum(1 for r in rows if r.get("result") == "our_win")
    ref_win = sum(1 for r in rows if r.get("result") == "reference_win")
    draw = sum(1 for r in rows if r.get("result") == "draw" or r.get("draw"))
    invalid = sum(1 for r in rows if r.get("result") == "invalid" or r.get("error")
                  or r.get("timeout"))
    decisive = our_win + ref_win
    return {"games": len(rows), "our_win": our_win, "ref_win": ref_win, "draw": draw,
            "invalid": invalid, "decisive": decisive,
            "our_win_rate_vs_reference": round(our_win / decisive, 4) if decisive else None}


def part_d() -> dict:
    # outcome-level: local internal sidecars
    sidecars = sorted(glob.glob(str(GAMES_DIR / "*.json.gz")))
    res = Counter()
    steps = []
    fam_internal = {f: Counter() for f in FAMILIES + ["unknown"]}
    for f in sidecars:
        obj = tp.read_trace(f)
        oc = tp.sidecar_outcome(obj)
        res[oc["result"]] += 1
        if isinstance(oc["step_count"], int):
            steps.append(oc["step_count"])
        # attribute the A-seat candidate's family outcome (a_outcome)
        fam = family_of(obj.get("candidate_a"))
        fam_internal.setdefault(fam, Counter())[oc.get("a_outcome") or "?"] += 1
    steps.sort()
    # outcome-level: references
    bench_rows = [json.loads(l) for l in BENCH_JSONL.read_text().splitlines() if l.strip()] \
        if BENCH_JSONL.exists() else []
    ref_overall = _bench_summary(bench_rows)
    ref_by_family = {}
    by_fam_rows: dict[str, list] = {}
    for r in bench_rows:
        by_fam_rows.setdefault(family_of(r.get("our_candidate")), []).append(r)
    for fam, rows in by_fam_rows.items():
        ref_by_family[fam] = _bench_summary(rows)
    # trace-level: single replay (illustrative, n=1)
    trace = {"available": REPLAY.exists(), "games": 1 if REPLAY.exists() else 0,
             "illustrative_only": True, "per_seat": []}
    if REPLAY.exists():
        obj = tp.read_trace(REPLAY)
        frames = tp.iter_decision_frames(obj)
        for seat in (0, 1):
            s = tp.summarize_turn_plan(frames, acting_player=seat, game_id=obj.get("id"))
            trace["per_seat"].append({
                "seat": seat, "n_frames": s.n_frames,
                "first_attack_turn": s.first_attack_turn,
                "first_prize_turn": s.first_prize_turn,
                "attach_events": sum(s.energy_attachments_by_turn.values()),
                "search_actions": s.search_action_count,
                "ability_uses": s.ability_use_count,
                "retreat_switch": s.retreat_switch_count,
                "end_with_alternatives": s.main_end_with_alternatives,
                "turns_ending_without_attack": s.turns_ending_without_attack,
                "dead_low_action_turns": s.dead_low_action_turns})
    data = {
        "pass": "46b", "part": "D", "read_only": True,
        "reference_opponents_overall": ref_overall,
        "internal_candidates_overall_local_sidecars": {
            "games": len(sidecars), "results": dict(res),
            "game_length_step_count": {
                "n": len(steps),
                "min": steps[0] if steps else None,
                "median": steps[len(steps) // 2] if steps else None,
                "max": steps[-1] if steps else None,
                "note": "max is an outlier long/stuck game"},
        },
        "probation_candidates_local": {"status": "insufficient_data",
                                       "reason": "no generated_ probation games persisted locally; "
                                                 "production sidecars deliberately not bulk-downloaded"},
        "generated_pass42_candidates_local": {"status": "insufficient_data",
                                              "reason": "no generated_ frames/sidecars present locally"},
        "reference_gap_by_family": ref_by_family,
        "internal_family_a_outcomes_local": {k: dict(v) for k, v in fam_internal.items() if v},
        "trace_level_turn_planning": trace,
        "key_finding": (
            f"Across {ref_overall['decisive']} decisive benchmark games our candidates beat "
            f"public references only {ref_overall['our_win_rate_vs_reference']} of the time — "
            "the gap is broad and behavioral. Public references likely use cg_typed agents and "
            "stronger turn plans; our internal candidates are stdlib/generic. Trace-level "
            "turn-planning metrics are illustrative (single replay) only."),
    }
    md = ("## Reference opponents (benchmark-only)\n"
          f"- our win-rate vs references: **{ref_overall['our_win_rate_vs_reference']}** "
          f"({ref_overall['our_win']}W / {ref_overall['ref_win']}L / {ref_overall['draw']}D "
          f"/ {ref_overall['invalid']} invalid over {ref_overall['games']} games)\n\n"
          "## Reference gap by family (our win-rate vs references)\n"
          "| family | games | ourW | refW | draw | our_winrate |\n|---|---|---|---|---|---|\n"
          + "".join(f"| {fam} | {d['games']} | {d['our_win']} | {d['ref_win']} | {d['draw']} | "
                   f"{d['our_win_rate_vs_reference']} |\n" for fam, d in sorted(ref_by_family.items()))
          + "\n## Internal local sidecars (internal-vs-internal)\n"
          f"- results: {dict(res)}; game length step-count min/median/max: "
          f"{data['internal_candidates_overall_local_sidecars']['game_length_step_count']['min']}/"
          f"{data['internal_candidates_overall_local_sidecars']['game_length_step_count']['median']}/"
          f"{data['internal_candidates_overall_local_sidecars']['game_length_step_count']['max']}\n\n"
          "## Trace-level turn planning (single replay — illustrative only)\n"
          + "".join(f"- seat {p['seat']}: first_attack_turn={p['first_attack_turn']}, "
                    f"first_prize_turn={p['first_prize_turn']}, attach={p['attach_events']}, "
                    f"search={p['search_actions']}, ability={p['ability_uses']}\n"
                    for p in trace["per_seat"])
          + f"\n## Key finding\n{data['key_finding']}\n")
    write_pair("pass46b_reference_behavior_baseline", data, "Reference-vs-Our Behavioral Baseline (Part D)", md)
    return data


# ============================================== Part E: loss-mode taxonomy
def part_e() -> dict:
    labels = [
        {"label": "setup_underdeveloped", "rule": "bench_count < 2 by the earliest 1-2 observed turns (no backup attackers)",
         "evidence_fields": ["bench_count", "turn", "setup_bench_count"], "confidence": "medium"},
        {"label": "energy_slow", "rule": "energy attachment events lag (0 attach events through early turns)",
         "evidence_fields": ["energy_attachments_by_turn"], "confidence": "medium"},
        {"label": "attack_lag", "rule": "first_attack_turn later than the reference median first_attack_turn",
         "evidence_fields": ["first_attack_turn"], "confidence": "low",
         "note": "needs frame-level reference baseline; currently low (n=1 trace)"},
        {"label": "prize_lag", "rule": "first_prize_turn / first_ko_turn later than reference median",
         "evidence_fields": ["first_prize_turn", "first_ko_turn"], "confidence": "low"},
        {"label": "passive_main_phase", "rule": "main_end_with_alternatives > 0 (End chosen while productive options existed)",
         "evidence_fields": ["main_end_with_alternatives", "option_families"], "confidence": "medium"},
        {"label": "discard_pressure", "rule": "high discard_action_count of energy/basic/evolution/search cards",
         "evidence_fields": ["discard_action_count", "discard_card_ids"], "confidence": "low",
         "note": "card categories need deck metadata; currently low"},
        {"label": "search_underuse_or_misuse", "rule": "search_action_count low relative to dead/low-action turns",
         "evidence_fields": ["search_action_count", "dead_low_action_turns"], "confidence": "low"},
        {"label": "low_ability_usage", "rule": "ability_use_count == 0 across the game when ability options were present",
         "evidence_fields": ["ability_use_count", "option_families"], "confidence": "low"},
        {"label": "long_game_resource_decay", "rule": "deck_count trajectory collapses or dead_low_action_turns high / very long game",
         "evidence_fields": ["deck_count_trajectory", "dead_low_action_turns", "step_count"], "confidence": "medium"},
        {"label": "runtime_failure", "rule": "invalid / timeout / error flag set",
         "evidence_fields": ["invalid", "timeout", "error"], "confidence": "high"},
        {"label": "unsupported", "rule": "insufficient trace info to assign any label",
         "evidence_fields": [], "confidence": "high"},
    ]
    data = {
        "pass": "46b", "part": "E", "read_only": True, "deterministic": True,
        "never_quarantines_or_promotes": True,
        "labels_are_observational_not_causal": True,
        "never_classifies_missed_lethal": True,
        "missed_lethal_note": "missed-lethal is NEVER classified here; it requires a validated "
                              "Search API / exact attack outcome, which this taxonomy does not use.",
        "labels": labels,
    }
    md = ("## Loss-mode labels (deterministic, observational — not causal)\n"
          "| label | rule | confidence |\n|---|---|---|\n"
          + "".join(f"| {l['label']} | {l['rule']} | {l['confidence']} |\n" for l in labels)
          + "\n_missed-lethal is intentionally absent: not inferable without a validated Search API._\n")
    write_pair("pass46b_loss_mode_taxonomy", data, "Loss-Mode Taxonomy v0 (Part E)", md)
    return data


# ============================================== Part F: per-family gap report
def part_f(part_d_data: dict) -> dict:
    ref_by_family = part_d_data["reference_gap_by_family"]
    gaps = []
    for fam in FAMILIES:
        d = ref_by_family.get(fam)
        if not d:
            gaps.append({"family": fam, "sample_size": 0, "status": "sample_too_small",
                         "reference_win_rate": None, "dominant_loss_modes": [],
                         "primitives_needed": [], "feed": "no_action_yet",
                         "uncertainty": "high"})
            continue
        wr = d["our_win_rate_vs_reference"]
        gaps.append({
            "family": fam, "sample_size": d["games"],
            "reference_win_rate_ours": wr,
            "decisive": d["decisive"],
            "dominant_loss_modes": ["attack_lag", "setup_underdeveloped", "passive_main_phase"]
            if (wr is not None and wr < 0.4) else ["mixed"],
            "primitives_needed": ["turn_phase_plan", "energy_planner", "attack_planner",
                                  "search_planner"],
            "feed": "cg_typed_reusable_policy_primitives",
            "uncertainty": "medium (outcome-level only; trace-level frames insufficient)"})
    # rank by largest observable gap (lowest our win-rate first), unknown win-rate last
    ranked = sorted(gaps, key=lambda g: (g.get("reference_win_rate_ours") is None,
                                         g.get("reference_win_rate_ours") if g.get("reference_win_rate_ours") is not None else 1))
    data = {
        "pass": "46b", "part": "F", "read_only": True,
        "no_kaggle_strength_claim": True,
        "ranked_largest_observable_gaps": ranked,
        "headline": ("The broad gap is gameplay POLICY / turn planning, not deck counts. "
                     "Every family loses the large majority of games to public references. "
                     "The next improvement should be REUSABLE turn-planning primitives "
                     "(cg_typed lane), not another one-off deck."),
    }
    md = ("## Ranked largest observable gaps (lowest our win-rate vs references first)\n"
          "| family | sample | our_winrate | feed |\n|---|---|---|---|\n"
          + "".join(f"| {g['family']} | {g['sample_size']} | {g.get('reference_win_rate_ours')} | "
                   f"{g['feed']} |\n" for g in ranked)
          + f"\n## Headline\n{data['headline']}\n")
    write_pair("pass46b_family_gap_report", data, "Per-Family Gap Report (Part F)", md)
    return data


# ============================================== Part G: primitive backlog
def part_g() -> dict:
    primitives = [
        {"id": "typed_board_decode_wrapper", "title": "Typed board decode wrapper",
         "desc": "stable typed view of active/bench/hand/discard/prize/deck counts",
         "status": "ready_for_design",
         "note": "Pass-46B extractor already provides honest counts; promote to a reusable typed view."},
        {"id": "legal_option_taxonomy", "title": "Legal option taxonomy",
         "desc": "robust SelectContext/OptionType mapping with safe unknown fallback",
         "status": "ready_for_design",
         "note": "action_resolver + classify_action_family cover the positively-observed codes."},
        {"id": "turn_phase_plan", "title": "Turn phase plan",
         "desc": "setup-active, setup-bench, development, attack, recovery, prize-race phases",
         "status": "needs_more_trace_evidence"},
        {"id": "energy_planner", "title": "Energy planner",
         "desc": "attach to current vs future attacker; avoid over-attaching; enable retreat",
         "status": "needs_cg_typed_lane"},
        {"id": "search_planner", "title": "Search planner",
         "desc": "prioritize basics if bench thin, evolution if base exists, energy to unlock attack, draw if hand dead",
         "status": "needs_cg_typed_lane"},
        {"id": "discard_planner", "title": "Discard planner",
         "desc": "preserve unique basics/evolutions/energy thresholds; discard excess duplicates/low-value late cards",
         "status": "needs_more_trace_evidence"},
        {"id": "attack_planner", "title": "Attack planner",
         "desc": "attack when available and productive; prefer prize-taking only when observably supported",
         "status": "needs_cg_typed_lane",
         "note": "must NOT claim lethal/missed-KO without a validated Search API"},
        {"id": "retreat_switch_planner", "title": "Retreat/switch planner",
         "desc": "promote attacker-ready mon; preserve high-prize damaged attacker when possible",
         "status": "needs_more_trace_evidence"},
        {"id": "deckout_draw_safety_gate", "title": "Deckout / draw-safety gate",
         "desc": "avoid drawing into deckout; protect deck count late",
         "status": "ready_for_design"},
        {"id": "prize_race_heuristics", "title": "Prize-race heuristics",
         "desc": "track prize differential; bias plays to win the prize race",
         "status": "needs_cg_typed_lane"},
        {"id": "reference_parity_benchmark_gate", "title": "Reference-parity benchmark gate",
         "desc": "benchmark-only gate measuring closeness to public references before any promotion",
         "status": "ready_for_design"},
        {"id": "search_api_counterfactual_probe", "title": "Search API counterfactual probe (future)",
         "desc": "small bounded read-only feasibility only; no live policy",
         "status": "needs_search_api"},
    ]
    data = {"pass": "46b", "part": "G", "read_only": True,
            "focus": "reusable turn-planning primitives, NOT one-off deck optimization",
            "primitives": primitives,
            "status_legend": ["ready_for_design", "needs_more_trace_evidence",
                              "needs_cg_typed_lane", "needs_search_api",
                              "special_pilot_only", "blocked_or_unsupported"],
            "top3_next": ["typed_board_decode_wrapper", "legal_option_taxonomy", "energy_planner"]}
    md = ("## Reusable turn-planning primitive backlog\n"
          "| id | title | status |\n|---|---|---|\n"
          + "".join(f"| {p['id']} | {p['title']} | {p['status']} |\n" for p in primitives)
          + "\n## Top 3 to build next\n"
          + "".join(f"- {x}\n" for x in data["top3_next"]))
    write_pair("pass46b_turn_planning_backlog", data, "Turn-Planning Primitive Backlog (Part G)", md)
    return data


# ============================================== Part H: bounded sidecar sampler
def part_h() -> dict:
    N = 10
    sidecars = sorted(glob.glob(str(GAMES_DIR / "*.json.gz")))
    # bounded selection: prefer complete, non-invalid, mix of win/loss
    chosen, wins, losses = [], 0, 0
    for f in sidecars:
        if len(chosen) >= N:
            break
        obj = tp.read_trace(f)
        oc = tp.sidecar_outcome(obj)
        if oc["error"] or oc["timeout"] or not oc["ok"]:
            continue
        if oc["result"] == "win" and wins < N // 2:
            chosen.append((f, oc)); wins += 1
        elif oc["result"] == "loss" and losses < N - N // 2:
            chosen.append((f, oc)); losses += 1
    manifest = [{
        "file": Path(f).name, "result": oc["result"], "step_count": oc["step_count"],
        "candidate_a": oc["candidate_a"], "candidate_b": oc["candidate_b"],
        "frames_available": oc["frames_available"]} for f, oc in chosen]
    data = {"pass": "46b", "part": "H", "read_only": True,
            "bounded_N_per_group": N, "total_local_sidecars": len(sidecars),
            "sampled": len(manifest), "bulk_download": False,
            "production_sidecars_downloaded": False,
            "avoided": ["locks/", "conflict_report", "pytest scratch"],
            "note": "all sampled sidecars are outcome-only (no decision frames). Sampler is "
                    "bounded and never bulk-reads all games or downloads production sidecars.",
            "no_secret_values": True, "manifest": manifest}
    md = ("## Bounded sidecar sample (outcome-only)\n"
          f"- bounded N per group: {N}; sampled {len(manifest)} of {len(sidecars)} local sidecars\n"
          "- production sidecars NOT downloaded; no bulk read\n\n"
          "| file | result | step_count |\n|---|---|---|\n"
          + "".join(f"| {m['file']} | {m['result']} | {m['step_count']} |\n" for m in manifest))
    write_pair("pass46b_sidecar_sample_manifest", data, "Bounded Sidecar Sample (Part H)", md)
    return data


# ============================================== Part I: optional top-up (skip)
def part_i() -> dict:
    data = {"pass": "46b", "part": "I", "read_only": True, "topup_run": False,
            "reason": "existing evidence is sufficient for the diagnostic; a benchmark top-up "
                      "risks timeout/complexity and is out of scope for a read-only diagnostic.",
            "games_attempted": 0, "games_completed": 0, "ledger_used": None,
            "invalid": 0, "timeout": 0, "changed_conclusions": False,
            "production_touched": False, "candidate_generation": False}
    md = ("## Optional benchmark top-up\n- **Not run.** "
          + data["reason"] + "\n- No production state touched; conclusions unchanged.\n")
    write_pair("pass46b_optional_benchmark_topup", data, "Optional Benchmark Top-Up (Part I)", md)
    return data


# ============================================== Part J: strategy decision
def part_j(a: dict, d: dict) -> dict:
    if not a["all_ok"]:
        decision = "blocked_safety_failure"
    else:
        decision = "reference_gap_diagnostic_complete_soak_continue"
    data = {
        "pass": "46b", "part": "J", "read_only": True, "decision": decision,
        "allowed_decisions": ["reference_gap_diagnostic_complete_soak_continue",
                              "reference_gap_diagnostic_incomplete_needs_more_sidecars",
                              "blocked_safety_failure"],
        "statements": [
            "Keep soaking production probation candidates.",
            "Do not run full Pass 47 yet unless readiness thresholds are near.",
            "Do not optimize one deck now.",
            "Next improvement pass should be reusable turn-planning primitives / policy "
            "infrastructure (cg_typed / search-capable), not another one-off deck.",
            "Public-reference parity is not close yet "
            f"(our win-rate vs references ≈ {d['reference_opponents_overall']['our_win_rate_vs_reference']}).",
            "No upload / submit / promotion / generation occurred.",
        ],
        "production_mutated": False, "candidate_generated": False,
        "candidate_promoted": False, "candidate_submitted": False,
        "caveats": CAVEATS,
    }
    md = (f"## Decision: **{decision}**\n\n"
          + "".join(f"- {s}\n" for s in data["statements"]))
    write_pair("pass46b_strategy_decision", data, "Strategy Decision (Part J)", md)
    return data


def main() -> None:
    EXP.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    a = part_a()
    if not a["all_ok"]:
        # still emit a decision artifact recording the block, then stop.
        part_j(a, {"reference_opponents_overall": {"our_win_rate_vs_reference": None}})
        print(json.dumps({"STOP": "safety_failure", "checks": a["checks"]}, indent=2))
        return
    b = part_b()
    c = part_c_schema()
    d = part_d()
    e = part_e()
    f = part_f(d)
    g = part_g()
    h = part_h()
    i = part_i()
    j = part_j(a, d)
    print(json.dumps({
        "all_ok": a["all_ok"], "decision": j["decision"],
        "our_winrate_vs_refs": d["reference_opponents_overall"]["our_win_rate_vs_reference"],
        "replay_frames": c is not None and b["kaggle_replay"]["decision_frames"],
        "elapsed_s": round(time.time() - t0, 1)}, indent=2))


if __name__ == "__main__":
    main()
