#!/usr/bin/env python3
"""Pass 34 (Part M) — emit ActiveGraph events for the new-deck intake + lane split.

Data-driven from the Pass-34 artifacts. Emits exactly the Part-M event set:
- StrategyFamilyRegistered    : one per NEW deck family (Miraidon, Diamond, Toxic, Durant).
- StrategyHypothesisLogged    : one per deck idea (intake).
- StrategyIterationCreated    : one per BUILT candidate (Part E manifest).
- StrategyIterationEvaluated  : one per internal-tournament participant (Part H).
- LocalEvaluationFinished     : the internal tournament AND the meta sanity (Part H/K).
- StrategyDecisionRecorded    : the gated dry-run decision (Part L).
- SubmissionQueued            : only if the dry-run queue holds one candidate (Part L).
- ReportSiteGenerated         : the Part-N reports/site.

Every event carries no_upload=true and a "pass34" tag plus family_id (and
candidate_id / parent_id / source_artifacts / validation / tournament / decision
label where applicable). The only side effect is appending to the local lab event
store — nothing is uploaded to Kaggle or pushed to GitHub. Idempotent: re-running
strips previously-emitted "pass34" events first.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.graph.events import EventType, new_event  # noqa: E402
from ptcg_activegraph.graph.event_store import EventStore  # noqa: E402
from ptcg_activegraph.experiments.config import LAB_EVENTS_PATH  # noqa: E402

EXP = REPO / "data" / "experiments"
TAG = "pass34"

# deck_id -> family_id (the four NEW families ingested this pass)
FAMILY = {
    "mono_lightning_miraidon_easy": "miraidon",
    "diamond_toolbox_diancie": "diamond",
    "toxic_trap_poison_lock": "toxic",
    "deckout_carousel_durant_v2": "durant",
}
# ranking family token -> our family_id (benchmarks keep their own)
RANK_FAMILY = {
    "miraidon_new": "miraidon", "diamond_new": "diamond",
    "water": "water", "dragapult": "dragapult", "charizard": "charizard",
    "venusaur": "venusaur", "gardevoir": "gardevoir",
}


def _load(name: str) -> dict:
    try:
        return json.loads((EXP / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _strip(path, tag=TAG) -> int:
    p = Path(path)
    if not p.exists():
        return 0
    kept, removed = [], 0
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except Exception:  # noqa: BLE001
            kept.append(line)
            continue
        tags = ev.get("tags") or [] if isinstance(ev, dict) else []
        if tag in tags:
            removed += 1
        else:
            kept.append(line)
    p.write_text(("\n".join(kept) + ("\n" if kept else "")), encoding="utf-8")
    return removed


def main() -> int:
    intake = _load("pass34_deck_intake.json")
    manifest = _load("pass34_candidate_manifest.json")
    validation = {r["candidate_id"]: r
                  for r in _load("pass34_candidate_validation.json").get("results", [])}
    smoke = {r["candidate_id"]: r
             for r in _load("pass34_live_smoke.json").get("results", [])}
    rankings = _load("pass34_new_deck_rankings.json")
    meta = _load("pass34_meta_sanity.json")
    decision = _load("pass34_strategy_decision.json")

    removed = _strip(LAB_EVENTS_PATH)
    if removed:
        print(f"removed {removed} stale {TAG} events (idempotent re-run)")
    store = EventStore(LAB_EVENTS_PATH)
    n = 0

    intake_decks = intake.get("decks", [])
    INTAKE_SRC = "data/experiments/pass34_deck_intake.json"
    MAN_SRC = "data/experiments/pass34_candidate_manifest.json"

    # 1) StrategyFamilyRegistered — one per NEW family.
    seen_fam: set[str] = set()
    for d in intake_decks:
        fam = FAMILY.get(d["deck_id"], d["deck_id"])
        if fam in seen_fam:
            continue
        seen_fam.add(fam)
        store.append(new_event(
            EventType.StrategyFamilyRegistered,
            tags=[TAG, "family", fam],
            payload={"family_id": fam, "display_name": d.get("display_name"),
                     "design_class": d.get("design_class"), "lane": d.get("lane"),
                     "special_pilot_required": d.get("special_pilot_required"),
                     "energy_color": d.get("energy_color"),
                     "source_artifacts": [INTAKE_SRC],
                     "is_clone": False, "is_kaggle_leaderboard": False,
                     "no_upload": True}))
        n += 1

    # 2) StrategyHypothesisLogged — one per deck idea.
    for d in intake_decks:
        fam = FAMILY.get(d["deck_id"], d["deck_id"])
        store.append(new_event(
            EventType.StrategyHypothesisLogged,
            tags=[TAG, "hypothesis", fam, d["deck_id"]],
            payload={"family_id": fam, "candidate_id": d["deck_id"],
                     "display_name": d.get("display_name"),
                     "design_class": d.get("design_class"), "lane": d.get("lane"),
                     "special_pilot_required": d.get("special_pilot_required"),
                     "energy_color": d.get("energy_color"),
                     "energy_resolution": d.get("energy_resolution"),
                     "cards_validated": d.get("cards_validated"),
                     "missing_ids": d.get("missing_ids"),
                     "evolution_corrections": d.get("evolution_corrections"),
                     "source_artifacts": [INTAKE_SRC],
                     "invented_card_ids": False, "is_kaggle_leaderboard": False,
                     "no_upload": True}))
        n += 1

    # 3) StrategyIterationCreated — one per BUILT candidate.
    built_ids = []
    for r in manifest.get("results", []):
        if not r.get("built"):
            continue
        cid = r["candidate_id"]
        built_ids.append(cid)
        v = validation.get(cid, {})
        s = smoke.get(cid, {})
        store.append(new_event(
            EventType.StrategyIterationCreated,
            tags=[TAG, "candidate", FAMILY.get(cid, cid), cid],
            payload={"family_id": FAMILY.get(cid, cid), "candidate_id": cid,
                     "parent_id": r.get("generic_pilot_source"),
                     "lane": r.get("lane"),
                     "special_pilot_required": r.get("special_pilot_required"),
                     "blocked_from_league": r.get("blocked_from_league"),
                     "blocked_reason": r.get("blocked_reason"),
                     "deck_size": r.get("deck_size"),
                     "tarball": r.get("tarball"),
                     "validation_status": {
                         "tarball_valid": v.get("tarball_valid"),
                         "entrypoint_valid": v.get("entrypoint_valid"),
                         "smoke_clean": s.get("clean"),
                         "deck_is_legal_evidence": s.get("deck_is_legal_evidence")},
                     "source_artifacts": [MAN_SRC,
                                          "data/experiments/pass34_candidate_validation.json",
                                          "data/experiments/pass34_live_smoke.json"],
                     "invented_card_ids": False, "is_clone": False,
                     "is_kaggle_leaderboard": False, "no_upload": True}))
        n += 1

    # 4) StrategyIterationEvaluated — one per internal-tournament participant.
    standings = rankings.get("standings", [])
    meta_pd = meta.get("per_deck", {})
    RANK_SRC = "data/experiments/pass34_new_deck_rankings.json"
    for i, r in enumerate(standings, 1):
        cid = r["id"]
        fam = RANK_FAMILY.get(r.get("family"), r.get("family"))
        md = meta_pd.get(cid, {})
        collapses = sorted(
            sf for sf, rr in (md.get("per_archetype") or {}).items()
            if (rr.get("win_rate") or 0.0) < 0.10)
        store.append(new_event(
            EventType.StrategyIterationEvaluated,
            tags=[TAG, "tournament", fam, cid],
            payload={"family_id": fam, "candidate_id": cid, "rank": i,
                     "is_new_pass34_deck": cid in FAMILY,
                     "tournament_status": {
                         "adj_win_rate": r.get("adj_win_rate"),
                         "wilson": r.get("wilson"),
                         "compatibility_label": r.get("compatibility_label"),
                         "invalids": r.get("invalids"),
                         "timeouts": r.get("timeouts"),
                         "crashes": r.get("crashes")},
                     "meta_sanity": {
                         "weighted_meta_score": md.get("weighted_meta_score"),
                         "collapses": collapses},
                     "source_artifacts": [RANK_SRC,
                                          "data/experiments/pass34_meta_sanity.json"],
                     "surrogate_only": True, "is_kaggle_leaderboard": False,
                     "no_upload": True}))
        n += 1

    # 5) LocalEvaluationFinished — internal tournament + meta sanity.
    store.append(new_event(
        EventType.LocalEvaluationFinished,
        tags=[TAG, "tournament"],
        payload={"evaluation": "internal_new_deck_tournament",
                 "participants": len(standings),
                 "is_kaggle_leaderboard": False,
                 "caveat": ("internal our-vs-our tournament with one generic pilot; "
                            "NOT Kaggle, NOT a promotion signal"),
                 "source_artifacts": [RANK_SRC], "no_upload": True}))
    n += 1
    sanity = meta.get("sanity", {})
    store.append(new_event(
        EventType.LocalEvaluationFinished,
        tags=[TAG, "meta_sanity"],
        payload={"evaluation": "replay_derived_meta_sanity",
                 "subjects": len(meta_pd), "sanity_passed": sanity.get("sanity_passed"),
                 "is_kaggle_leaderboard": False, "surrogate_only": True,
                 "caveat": ("replay-derived surrogate opponents piloted by a generic "
                            "brain; directional only, NOT Kaggle"),
                 "source_artifacts": ["data/experiments/pass34_meta_sanity.json"],
                 "no_upload": True}))
    n += 1

    # 6) StrategyDecisionRecorded — the gated dry-run decision.
    labels = decision.get("decision_labels", {})
    store.append(new_event(
        EventType.StrategyDecisionRecorded,
        tags=[TAG, "decision"],
        payload={"pass": 34, "decision_label": decision.get("decision"),
                 "held_probe": decision.get("held_probe"),
                 "held_probe_reaffirmed": decision.get("held_probe_reaffirmed"),
                 "queued_candidate_count": decision.get("queued_candidate_count"),
                 "any_new_candidate_displaces_held":
                     decision.get("any_new_candidate_displaces_held"),
                 "decision_labels": labels,
                 "special_pilot_tasks": decision.get("special_pilot_tasks"),
                 "human_approval_required": True, "auto_submit_enabled": False,
                 "promote": False, "upload": False, "submit": False,
                 "github_push": False, "is_kaggle_leaderboard": False,
                 "source_artifacts": [
                     "data/experiments/pass34_strategy_decision.json"],
                 "no_upload": True}))
    n += 1

    # 7) SubmissionQueued — only if the dry-run queue holds one candidate.
    if decision.get("queued_candidate_count"):
        held = decision.get("held_probe")
        store.append(new_event(
            EventType.SubmissionQueued,
            tags=[TAG, "dry_run_queue", held],
            payload={"family_id": FAMILY.get(held, "water"), "candidate_id": held,
                     "disposition": "held_future_calibration_probe",
                     "queue_max": 1, "held": True, "auto_submit_enabled": False,
                     "require_manual_approval_for_submit": True,
                     "upload_performed": False, "is_kaggle_leaderboard": False,
                     "decision_label": decision.get("decision"),
                     "source_artifacts": ["data/submission_queue.json"],
                     "no_upload": True}))
        n += 1

    # 8) ReportSiteGenerated.
    store.append(new_event(
        EventType.ReportSiteGenerated,
        tags=[TAG, "report"],
        payload={"pass": 34,
                 "reports": [
                     "data/reports/pass34_new_deck_intake_tournament_report.md",
                     "data/reports/activegraph_strategy_report.md",
                     "data/site/index.html",
                     "docs/PTCG_STRATEGY_CANVAS.md",
                     "docs/SPECIAL_PILOT_LANES.md"],
                 "decision_label": decision.get("decision"), "no_upload": True}))
    n += 1

    print(f"emitted {n} {TAG} events -> {LAB_EVENTS_PATH}")
    print(f"families={len(seen_fam)} ideas={len(intake_decks)} "
          f"built={len(built_ids)} participants={len(standings)} "
          f"queued={decision.get('queued_candidate_count')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
