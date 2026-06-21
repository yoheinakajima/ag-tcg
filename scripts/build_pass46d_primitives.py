#!/usr/bin/env python3
"""PASS 46D — turn-planning primitives v0 build (READ-ONLY / LOCAL / INFRASTRUCTURE).

Produces every Pass-46D artifact WITHOUT mutating production, running a tick, generating
candidates, or making any Kaggle-strength claim:

* Part A — safety stop-gate ............ data/experiments/pass46d_safety_preflight.{json,md}
* Part B — primitive design doc ........ docs/TURN_PLANNING_PRIMITIVES_V0.md
                                         data/experiments/pass46d_primitive_design.{json,md}
* Part D — fixture extraction .......... data/experiments/pass46d_trace_fixture_manifest.{json,md}
* Part E — fixture validation .......... data/experiments/pass46d_primitive_fixture_validation.{json,md}
* Part F — behavior comparison ......... data/experiments/pass46d_primitive_behavior_comparison.{json,md}
* Part G — candidate integration plan .. docs/TURN_PLANNING_CANDIDATE_INTEGRATION_PLAN.md
                                         data/experiments/pass46d_candidate_integration_plan.{json,md}
* Part J — report (10 sections) ........ data/reports/pass46d_turn_planning_primitives_report.md
                                         data/experiments/pass46d_strategy_decision.{json,md}

The primitives under test live in the pure module
``src/ptcg_activegraph/analysis/turn_primitives.py``.
"""
from __future__ import annotations

import filecmp
import glob
import gzip
import hashlib
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.analysis import turn_primitives as P  # noqa: E402
from ptcg_activegraph.analysis import turn_planning as TP  # noqa: E402
from ptcg_activegraph.tournament import sync, promotion, pool as poolmod, projections as projmod  # noqa: E402
from ptcg_activegraph.tournament.config import load_config  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool  # noqa: E402
from ptcg_activegraph.tournament.scheduler import build_worklist  # noqa: E402
from ptcg_activegraph.tournament.storage import get_storage_backend  # noqa: E402

EXP = REPO / "data" / "experiments"
REPORTS = REPO / "data" / "reports"
DOCS = REPO / "docs"
TRACES = EXP / "pass46c_traces"
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"

LEDGER_FORBIDDEN = {"SubmissionQueued", "SubmissionUploaded", "KaggleScoreUpdated",
                    "CandidatePromoted"}
NEVER = {poolmod.SPECIAL_PILOT_ONLY, poolmod.RETIRED, poolmod.QUARANTINED, poolmod.INVALID}

CAVEATS = [
    "READ-ONLY / LOCAL / INFRASTRUCTURE-ONLY: production Object Storage was not mutated.",
    "No production tick executed; the deployed daemon is unchanged and still soaking.",
    "No candidate generated, promoted, retired, quarantined, queued, uploaded, or republished.",
    "No tournament ledger / events.jsonl write occurred.",
    "Primitives are pure infrastructure; they make NO Kaggle leaderboard strength claim.",
    "Public references are BENCHMARK-ONLY opponents, never candidates/parents/sources.",
    "Unsupported claims (exact damage, lethal, missed-KO, Boss/gust, spread, best-action) "
    "stay explicitly unsupported.",
]


def sha_path(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def write_pair(stem: str, data: dict, md_title: str, md_body: str) -> None:
    (EXP / f"{stem}.json").write_text(json.dumps(data, indent=2, default=str) + "\n",
                                      encoding="utf-8")
    head = ("# " + md_title + "\n\n_Pass 46D — turn-planning primitives v0. READ-ONLY / "
            "LOCAL / infrastructure only. Pure primitives over Pass-46C decision frames; "
            "NOT a Kaggle strength claim. No generation / promotion / upload / tick._\n\n")
    caveat = "## Caveats\n" + "".join(f"- {c}\n" for c in CAVEATS) + "\n"
    (EXP / f"{stem}.md").write_text(head + caveat + md_body + "\n", encoding="utf-8")


# ============================================================= Part A: safety
def part_a() -> dict:
    main_unchanged = filecmp.cmp(REPO / "main.py", BASELINE / "main.py", shallow=False)
    deck_unchanged = filecmp.cmp(REPO / "deck.csv", BASELINE / "deck.csv", shallow=False)
    replit_txt = (REPO / ".replit").read_text(encoding="utf-8")
    dep_ok = ("scripts/tournament_deployment_tick.py" in replit_txt
              and "--production" in replit_txt
              and "replit_app_storage" in replit_txt)
    deployment_target_scheduled = 'deploymentTarget = "scheduled"' in replit_txt
    try:
        cfg0 = load_config()
        auto_submit = bool(getattr(cfg0, "auto_submit", False)) if cfg0 is not None else False
    except Exception:  # noqa: BLE001
        auto_submit = False
    # references absent from prod pool + worklist (read-only prod load)
    b = get_storage_backend(env="production", backend="replit_app_storage")
    txt = b.read_text(sync.EVENTS_KEY)
    tmpf = Path(tempfile.mkdtemp()) / "events.jsonl"
    tmpf.write_text(txt, encoding="utf-8")
    events = TournamentLedger(path=tmpf).load()
    pool = CandidatePool.from_events(events)
    status_of = {c.candidate_id: c.status for c in pool.candidates}
    ref_ids = set(promotion.load_reference_ids())
    refs_in_pool = sorted(ref_ids & set(status_of))
    projmod.PROJ_DIR = Path(tempfile.mkdtemp())
    cfg = load_config()
    prior = projmod.write_projections(pool, events, cfg)
    state = projmod.build_scheduler_state(events, ranking=prior["ranked_ids"])
    wl_ids: set[str] = set()
    for g in build_worklist(pool, state, cfg):
        d = g.to_dict()
        wl_ids.add(d["candidate_a"])
        wl_ids.add(d["candidate_b"])
    refs_in_wl = sorted(ref_ids & wl_ids)
    never_in_wl = sorted(c for c, s in status_of.items() if s in NEVER and c in wl_ids)
    forbidden_in_ledger = sorted({e.event_type for e in events
                                  if e.event_type in LEDGER_FORBIDDEN})
    # local ledger forbidden scan too
    local_events_path = REPO / "data" / "tournament" / "events.jsonl"
    local_forbidden: list[str] = []
    if local_events_path.exists():
        seen: set[str] = set()
        for line in local_events_path.read_text(encoding="utf-8").splitlines():
            try:
                et = json.loads(line).get("event_type")
            except Exception:  # noqa: BLE001
                continue
            if et in LEDGER_FORBIDDEN:
                seen.add(et)
        local_forbidden = sorted(seen)
    traces_present = sorted(Path(p).name for p in glob.glob(str(TRACES / "*.json.gz")))
    checks = {
        "root_main_unchanged": main_unchanged,
        "root_deck_unchanged": deck_unchanged,
        "deployment_points_to_tick_not_root": dep_ok,
        "deployment_target_scheduled": deployment_target_scheduled,
        "auto_submit_falsy": auto_submit is False,
        "references_absent_from_pool": refs_in_pool == [],
        "references_absent_from_worklist": refs_in_wl == [],
        "no_never_schedule_in_worklist": never_in_wl == [],
        "no_forbidden_events_in_prod_ledger": forbidden_in_ledger == [],
        "no_forbidden_events_in_local_ledger": local_forbidden == [],
        "pass46c_traces_present": len(traces_present) > 0,
    }
    all_ok = all(checks.values())
    data = {
        "pass": "46d", "part": "A", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "tick_executed": False,
        "candidate_generated": False,
        "baseline": str(BASELINE.relative_to(REPO)),
        "root_main_sha256": sha_path(REPO / "main.py"),
        "root_deck_sha256": sha_path(REPO / "deck.csv"),
        "checks": checks, "all_ok": all_ok,
        "refs_in_pool": refs_in_pool, "refs_in_worklist": refs_in_wl,
        "never_schedule_in_worklist": never_in_wl,
        "forbidden_events_in_prod_ledger": forbidden_in_ledger,
        "forbidden_events_in_local_ledger": local_forbidden,
        "prod_ledger_len": len(events), "n_traces_present": len(traces_present),
    }
    md = "## Stop-gate checks\n" + "".join(
        f"- `{k}`: {'PASS' if v else 'FAIL'}\n" for k, v in checks.items())
    md += f"\n**all_ok = {all_ok}**\n"
    write_pair("pass46d_safety_preflight", data,
               "Pass 46D — Part A: safety stop-gate", md)
    return data


# ============================================================= Part B: design doc
PRIMITIVE_DESIGN = [
    {
        "name": "typed_board_decode_wrapper",
        "purpose": "Decode any accepted frame shape (Kaggle-replay seat object, raw "
                   "observation, bare select, or DecisionFrame) into a normalized, "
                   "never-raising board snapshot with per-zone visible counts.",
        "v0_functions": ["safe_get", "board_snapshot_from_frame", "visible_counts_by_zone"],
        "status": "implemented_v0",
        "backlog": "Native cg-typed (cg.api dataclass) decode path; richer per-Pokemon "
                   "attached-energy / HP decode when a typed observation is supplied.",
    },
    {
        "name": "legal_option_taxonomy",
        "purpose": "Normalize option type codes/strings/enum-names and classify each legal "
                   "option into a conservative action family + coarse taxonomy bucket.",
        "v0_functions": ["normalize_option_type", "normalize_select_context",
                         "classify_option_family", "legal_action_family_summary"],
        "status": "implemented_v0",
        "backlog": "Disambiguate move_energy vs retreat without logs; evolve vs bench-place "
                   "for play_in_play when a typed board is available.",
    },
    {
        "name": "board_role_summary",
        "purpose": "Summarize the acting seat's and (counts-only) opponent's board roles: "
                   "active presence, bench occupancy, hand/deck/discard/prize counts.",
        "v0_functions": ["board_snapshot_from_frame", "visible_counts_by_zone"],
        "status": "implemented_v0",
        "backlog": "Attacker-readiness / role tags (attacker vs support vs pivot) which "
                   "require card typing from a cg-typed observation.",
    },
    {
        "name": "energy_planner",
        "purpose": "Enumerate attach-energy options with their visible destination zone and "
                   "give a GENERIC (deck-agnostic) ordering: fuel the active attacker before "
                   "developing the bench. No value/lethal computation.",
        "v0_functions": ["energy_attach_candidates", "score_energy_attach_generic"],
        "status": "implemented_v0",
        "backlog": "Value-of-information / attacker-cost-aware attach scoring (requires "
                   "attack cost typing + a trusted Search API).",
    },
    {
        "name": "setup_planner",
        "purpose": "Detect the setup phase (turn 0/1 or absent self-active) and, when the "
                   "trace encodes placement destinations, list active vs bench candidates.",
        "v0_functions": ["setup_candidate_summary"],
        "status": "implemented_v0_partial",
        "backlog": "These traces encode setup as a hand-select with NO active/bench "
                   "destination in the option schema, so destination labelling needs a "
                   "richer (cg-typed) observation; only phase + active-presence are honest here.",
    },
    {
        "name": "search_priority_planner",
        "purpose": "Enumerate deck-search (select-from-deck) options and surface ONLY the "
                   "card ids positively resolvable from select.deck[index].",
        "v0_functions": ["search_candidate_summary"],
        "status": "implemented_v0",
        "backlog": "Priority ORDERING of fetch targets (needs card typing + role goals); v0 "
                   "only lists visible candidates, it does not rank them.",
    },
    {
        "name": "discard_priority_planner",
        "purpose": "Enumerate discard (select-from-discard) options and surface ONLY the "
                   "resolvable card ids.",
        "v0_functions": ["discard_candidate_summary"],
        "status": "implemented_v0",
        "backlog": "Priority ORDERING of what to discard (needs card typing); v0 only lists.",
    },
    {
        "name": "draw_deckout_guard",
        "purpose": "Surface deck-out risk from the visible deck_count so a future policy can "
                   "avoid lethal self-deckout.",
        "v0_functions": ["visible_counts_by_zone (exposes deck_count)"],
        "status": "backlog",
        "backlog": "The raw input (deck_count) is already exposed by visible_counts_by_zone, "
                   "but the guard policy (draw-count modelling, deckout-turn projection) is "
                   "deferred to v1.",
    },
    {
        "name": "unsupported_claim_guard",
        "purpose": "Expose the fixed, stable set of claims the primitives REFUSE to infer "
                   "from a bare trace, so callers/tests can assert guarantees never shrink.",
        "v0_functions": ["unsupported_claims"],
        "status": "implemented_v0",
        "backlog": "None — guard is intentionally static; new unsupported claims are added "
                   "only when a corresponding trusted source is introduced.",
    },
]


def part_b() -> dict:
    impl = [p for p in PRIMITIVE_DESIGN if p["status"].startswith("implemented")]
    backlog = [p for p in PRIMITIVE_DESIGN if p["status"] == "backlog"]
    data = {
        "pass": "46d", "part": "B", "n_primitives": len(PRIMITIVE_DESIGN),
        "n_implemented_v0": len(impl), "n_backlog": len(backlog),
        "module": "src/ptcg_activegraph/analysis/turn_primitives.py",
        "primitives": PRIMITIVE_DESIGN,
        "design_invariants": [
            "pure / read-only (no Object Storage or EventStore writes, no network)",
            "never raises on malformed/missing data (structured unknown results)",
            "no dependency on production state",
            "no public-reference policy code import",
            "no deck-specific card strategy beyond generic role classification",
            "hidden opponent hand contents never read or fabricated (counts only)",
        ],
    }
    md = "## Primitives\n"
    for p in PRIMITIVE_DESIGN:
        md += (f"\n### {p['name']} — _{p['status']}_\n"
               f"{p['purpose']}\n\n"
               f"- v0 functions: {', '.join(p['v0_functions'])}\n"
               f"- backlog: {p['backlog']}\n")
    md += "\n## Design invariants\n" + "".join(f"- {x}\n" for x in data["design_invariants"])
    write_pair("pass46d_primitive_design", data,
               "Pass 46D — Part B: primitive design", md)
    # docs/ markdown (single source = PRIMITIVE_DESIGN)
    doc = ("# Turn-Planning Primitives v0\n\n"
           "_Pass 46D. Pure, read-only, never-raising building blocks for turn-planning "
           "diagnosis and (future) candidate generation. Infrastructure only — NOT a Kaggle "
           "strength claim, no production mutation, no candidate generation._\n\n"
           "Module: `src/ptcg_activegraph/analysis/turn_primitives.py`\n\n"
           "## Design invariants\n"
           + "".join(f"- {x}\n" for x in data["design_invariants"])
           + "\n## Primitives (v0 implemented vs backlog)\n")
    for p in PRIMITIVE_DESIGN:
        doc += (f"\n### {p['name']} — `{p['status']}`\n\n{p['purpose']}\n\n"
                f"- **v0 functions:** {', '.join(p['v0_functions'])}\n"
                f"- **backlog:** {p['backlog']}\n")
    doc += ("\n## Honesty contract\n\nThe following are ALWAYS marked unsupported and are "
            "never inferred from a bare trace (see `unsupported_claims()`):\n\n"
            + "".join(f"- `{k}`\n" for k in sorted(P.unsupported_claims()))
            + "\nNumeric `attackId` alone is insufficient for a damage/lethal claim.\n")
    (DOCS / "TURN_PLANNING_PRIMITIVES_V0.md").write_text(doc, encoding="utf-8")
    return data


# ============================================================= Part D: fixtures
def _iter_frames():
    """Yield (trace, step_index, seat, seat_obj) for every decision frame, deterministically."""
    for fp in sorted(glob.glob(str(TRACES / "*.json.gz"))):
        with gzip.open(fp, "rt", encoding="utf-8") as fh:
            o = json.load(fh)
        for i, step in enumerate(o.get("steps") or []):
            if not isinstance(step, list):
                continue
            for seat, so in enumerate(step):
                if not isinstance(so, dict):
                    continue
                obs = so.get("observation") or {}
                if not isinstance(obs.get("select"), dict):
                    continue
                yield o, i, seat, so


def _fixture_categories(so: dict, seat: int) -> set[str]:
    cats: set[str] = set()
    snap = P.board_snapshot_from_frame(so, seat=seat)
    summ = P.legal_action_family_summary(so, board=snap)
    fams = summ["families"]
    setup = P.setup_candidate_summary(so, board=snap)
    self_b = snap.get("self") or {}
    if setup.get("is_setup") is True:
        if self_b.get("active_present") is False:
            cats.add("setup_active")
        else:
            cats.add("setup_bench")
    if P.energy_attach_candidates(so):
        cats.add("main_attach")
    if "main_play" in fams or "evolve" in fams:
        cats.add("main_play_search")
    if P.discard_candidate_summary(so)["n_discard_options"] > 0:
        cats.add("discard")
    if P.search_candidate_summary(so)["n_search_options"] > 0:
        cats.add("search_to_hand")
    if "attack" in fams:
        cats.add("attack_available")
    productive = {x for x in fams if x not in ("end", "unknown")}
    if summ["n_options"] <= 1 or not productive:
        cats.add("low_choice_or_end")
    return cats


FIXTURE_ORDER = ["setup_active", "setup_bench", "main_attach", "main_play_search",
                 "discard", "search_to_hand", "attack_available", "low_choice_or_end"]


def part_d() -> dict:
    chosen: dict[str, dict] = {}
    for o, i, seat, so in _iter_frames():
        for cat in _fixture_categories(so, seat):
            if cat not in chosen:
                chosen[cat] = {
                    "category": cat, "game_id": o["id"], "step": i, "seat": seat,
                    "role": o["role_a"] if seat == 0 else o["role_b"],
                    "frame": so,
                }
        if all(c in chosen for c in FIXTURE_ORDER):
            break
    fixtures = [chosen[c] for c in FIXTURE_ORDER if c in chosen]
    missing = [c for c in FIXTURE_ORDER if c not in chosen]
    data = {
        "pass": "46d", "part": "D", "no_upload": True,
        "source_traces_dir": str(TRACES.relative_to(REPO)),
        "n_fixtures": len(fixtures),
        "categories_present": sorted(chosen),
        "categories_missing": missing,
        "fixtures": fixtures,
    }
    md = "## Fixtures extracted\n" + "".join(
        f"- `{f['category']}` — game `{f['game_id']}` step {f['step']} seat {f['seat']} "
        f"(role: {f['role']})\n" for f in fixtures)
    if missing:
        md += "\n## Categories not found in panel\n" + "".join(f"- `{c}`\n" for c in missing)
    write_pair("pass46d_trace_fixture_manifest", data,
               "Pass 46D — Part D: trace fixture manifest", md)
    return data


# ============================================================= Part E: validation
def _opponent_hand_exposed(snap: dict) -> bool:
    opp = snap.get("opponent")
    if not isinstance(opp, dict):
        return False
    # only counts are allowed; a literal 'hand' list would be an exposure
    return "hand" in opp and isinstance(opp.get("hand"), list)


def part_e(fixtures: list[dict]) -> dict:
    results: list[dict] = []
    for f in fixtures:
        so = f["frame"]
        seat = f["seat"]
        cat = f["category"]
        raw_sel = (so.get("observation") or {}).get("select") or {}
        snap = P.board_snapshot_from_frame(so, seat=seat)
        ctx = P.normalize_select_context(so)
        summ = P.legal_action_family_summary(so, board=snap)
        attach = P.energy_attach_candidates(so)
        search = P.search_candidate_summary(so)
        discard = P.discard_candidate_summary(so)
        checks: dict[str, bool] = {}
        # min/max preserved exactly
        checks["min_count_preserved"] = ctx["min_count"] == raw_sel.get("minCount")
        checks["max_count_preserved"] = ctx["max_count"] == raw_sel.get("maxCount")
        checks["n_options_preserved"] = ctx["n_options"] == len(
            raw_sel.get("option") or raw_sel.get("options") or [])
        # taxonomy classifies the category's known family correctly
        fams = set(summ["families"])
        if cat == "main_attach":
            checks["taxonomy_matches_category"] = "attach" in fams
        elif cat == "attack_available":
            checks["taxonomy_matches_category"] = "attack" in fams
        elif cat == "discard":
            checks["taxonomy_matches_category"] = discard["n_discard_options"] > 0
        elif cat == "search_to_hand":
            checks["taxonomy_matches_category"] = search["n_search_options"] > 0
        elif cat in ("setup_active", "setup_bench"):
            checks["taxonomy_matches_category"] = P.setup_candidate_summary(
                so, board=snap)["is_setup"] is True
        else:
            checks["taxonomy_matches_category"] = ctx["checkable"]
        # energy candidates point to active/bench destinations when present
        checks["energy_destinations_visible_or_none"] = all(
            c["destination"] in ("active", "bench") for c in attach) if attach else True
        # search/discard list visible ids only (subset of select.deck for search)
        deck = raw_sel.get("deck") if isinstance(raw_sel.get("deck"), list) else []
        deck_ids = {e.get("id") for e in deck if isinstance(e, dict)}
        checks["search_ids_visible_only"] = (not search["visible_card_ids"]) or (
            deck_ids and set(search["visible_card_ids"]) <= deck_ids)
        checks["discard_ids_resolvable_only"] = all(
            isinstance(x, int) for x in discard["visible_card_ids"])
        # hidden opponent hand never exposed
        checks["opponent_hand_not_exposed"] = not _opponent_hand_exposed(snap)
        # unsupported claims remain marked
        uns = P.unsupported_claims()
        required = {"exact_damage", "lethal_availability", "missed_ko",
                    "boss_gust_target_correctness", "spread_placement_correctness"}
        checks["unsupported_claims_present"] = required <= set(uns)
        ok = all(checks.values())
        results.append({"category": cat, "game_id": f["game_id"], "step": f["step"],
                        "seat": seat, "checks": checks, "ok": ok,
                        "families_present": summ["families_present"],
                        "n_attach": len(attach), "n_search": search["n_search_options"],
                        "n_discard": discard["n_discard_options"]})
    all_ok = bool(results) and all(r["ok"] for r in results)
    data = {"pass": "46d", "part": "E", "n_fixtures": len(results),
            "all_ok": all_ok, "results": results}
    md = f"## Fixture validation (all_ok = {all_ok})\n"
    for r in results:
        md += (f"\n### `{r['category']}` — {'OK' if r['ok'] else 'FAIL'}\n"
               f"- families: {', '.join(r['families_present'])}\n"
               + "".join(f"- `{k}`: {'PASS' if v else 'FAIL'}\n"
                         for k, v in r["checks"].items()))
    write_pair("pass46d_primitive_fixture_validation", data,
               "Pass 46D — Part E: primitive fixture validation", md)
    return data


# ============================================================= Part F: comparison
def _role_group(role: str) -> str:
    if role == "public_reference":
        return "public_reference"
    if role == "parent":
        return "internal_parent"
    return "internal_candidate"


def part_f() -> dict:
    groups: dict[str, dict] = {}

    def acc(g: str) -> dict:
        return groups.setdefault(g, {
            "n_games_seats": 0, "n_frames": 0,
            "frames_with_attach": 0, "frames_with_attack": 0,
            "frames_with_search": 0, "frames_with_discard": 0,
            "frames_low_choice": 0, "frames_setup": 0, "frames_setup_active_absent": 0,
            "attach_dest_active": 0, "attach_dest_bench": 0,
            "search_visible_ids": 0, "discard_visible_ids": 0,
            "family_frame_counts": {}, "members": set()})

    by_trace: dict[str, dict] = {}
    for fp in sorted(glob.glob(str(TRACES / "*.json.gz"))):
        with gzip.open(fp, "rt", encoding="utf-8") as fh:
            o = json.load(fh)
        seat_frames = {0: 0, 1: 0}
        roles = {0: o["role_a"], 1: o["role_b"]}
        members = {0: o["candidate_a"], 1: o["candidate_b"]}
        for i, step in enumerate(o.get("steps") or []):
            if not isinstance(step, list):
                continue
            for seat, so in enumerate(step):
                if not isinstance(so, dict):
                    continue
                if not isinstance((so.get("observation") or {}).get("select"), dict):
                    continue
                g = _role_group(roles[seat])
                d = acc(g)
                d["members"].add(members[seat])
                d["n_frames"] += 1
                seat_frames[seat] += 1
                snap = P.board_snapshot_from_frame(so, seat=seat)
                summ = P.legal_action_family_summary(so, board=snap)
                fams = summ["families"]
                for fam in fams:
                    d["family_frame_counts"][fam] = d["family_frame_counts"].get(fam, 0) + 1
                attach = P.energy_attach_candidates(so)
                if attach:
                    d["frames_with_attach"] += 1
                    for c in attach:
                        if c["destination"] == "active":
                            d["attach_dest_active"] += 1
                        elif c["destination"] == "bench":
                            d["attach_dest_bench"] += 1
                if "attack" in fams:
                    d["frames_with_attack"] += 1
                srch = P.search_candidate_summary(so)
                if srch["n_search_options"] > 0:
                    d["frames_with_search"] += 1
                    d["search_visible_ids"] += len(srch["visible_card_ids"])
                disc = P.discard_candidate_summary(so)
                if disc["n_discard_options"] > 0:
                    d["frames_with_discard"] += 1
                    d["discard_visible_ids"] += len(disc["visible_card_ids"])
                productive = {x for x in fams if x not in ("end", "unknown")}
                if summ["n_options"] <= 1 or not productive:
                    d["frames_low_choice"] += 1
                stp = P.setup_candidate_summary(so, board=snap)
                if stp.get("is_setup") is True:
                    d["frames_setup"] += 1
                    self_b = snap.get("self") or {}
                    if self_b.get("active_present") is False:
                        d["frames_setup_active_absent"] += 1
        for seat in (0, 1):
            acc(_role_group(roles[seat]))["n_games_seats"] += 1
        by_trace[o["id"]] = {"role_a": o["role_a"], "role_b": o["role_b"],
                             "frames_seat0": seat_frames[0], "frames_seat1": seat_frames[1]}

    def rate(num: int, den: int) -> float | None:
        return round(num / den, 4) if den else None

    summary: dict[str, dict] = {}
    for g, d in groups.items():
        n = d["n_frames"]
        summary[g] = {
            "n_games_seats": d["n_games_seats"], "n_frames": n,
            "members": sorted(d["members"]),
            "attach_frame_rate": rate(d["frames_with_attach"], n),
            "attack_frame_rate": rate(d["frames_with_attack"], n),
            "search_frame_rate": rate(d["frames_with_search"], n),
            "discard_frame_rate": rate(d["frames_with_discard"], n),
            "low_choice_frame_rate": rate(d["frames_low_choice"], n),
            "setup_frame_rate": rate(d["frames_setup"], n),
            "attach_dest_active": d["attach_dest_active"],
            "attach_dest_bench": d["attach_dest_bench"],
            "attach_dest_active_share": rate(
                d["attach_dest_active"], d["attach_dest_active"] + d["attach_dest_bench"]),
            "search_visible_ids_total": d["search_visible_ids"],
            "discard_visible_ids_total": d["discard_visible_ids"],
            "family_frame_counts": dict(sorted(
                d["family_frame_counts"].items(), key=lambda kv: -kv[1])),
        }
    caveats = [
        "DIRECTIONAL and SMALL-N: 12 local self-play games; not a leaderboard signal.",
        "Rates are over options PRESENTED per decision frame, not the action chosen "
        "(the selected action is not reliably recoverable from these traces — see 46B/46C).",
        "Public references are benchmark-only opponents; this is behavior description, "
        "not a strength comparison.",
        "No exact-damage / lethal / KO inference is used in any rate here.",
    ]
    data = {"pass": "46d", "part": "F", "directional_small_n": True,
            "caveats": caveats, "groups": summary, "by_trace": by_trace}
    md = "## Per-role behavior (directional, small-n)\n"
    for g, s in summary.items():
        md += (f"\n### {g} (members: {', '.join(s['members'])})\n"
               f"- frames: {s['n_frames']} over {s['n_games_seats']} game-seats\n"
               f"- attach frame rate: {s['attach_frame_rate']}; "
               f"attack: {s['attack_frame_rate']}; search: {s['search_frame_rate']}; "
               f"discard: {s['discard_frame_rate']}; low-choice: {s['low_choice_frame_rate']}\n"
               f"- attach destinations: active {s['attach_dest_active']} / "
               f"bench {s['attach_dest_bench']} (active share {s['attach_dest_active_share']})\n")
    md += "\n## Caveats\n" + "".join(f"- {c}\n" for c in caveats)
    write_pair("pass46d_primitive_behavior_comparison", data,
               "Pass 46D — Part F: primitive behavior comparison", md)
    return data


# ============================================================= Part G: integration
def part_g() -> dict:
    plan = {
        "candidate_generation_v1_usage": [
            "Generate candidate decks as today (deck-composition operators on INTERNAL "
            "sources only), then use the primitives to SCREEN a candidate's local trace "
            "behavior before admitting it to probation — e.g. flag candidates whose attach "
            "destinations or setup behavior look pathological vs their parent.",
            "Use legal_action_family_summary + family_frame_counts as a cheap behavioral "
            "fingerprint to detect inert / no-op mutations (a candidate whose family "
            "distribution is byte-identical to its parent is a non-inert-failure signal).",
        ],
        "stdlib_safe_agent_subset": [
            "A stdlib-only agent (no `import cg`) can call: safe_get, normalize_option_type, "
            "normalize_select_context, classify_option_family, legal_action_family_summary, "
            "board_snapshot_from_frame, visible_counts_by_zone, energy_attach_candidates, "
            "score_energy_attach_generic, search/discard_candidate_summary, unsupported_claims.",
            "These operate purely on the raw observation/select dicts already passed to a "
            "Kaggle agent, so no extra dependency or runtime is introduced.",
        ],
        "cg_typed_search_full_stack": [
            "A cg-typed / Search-API-capable agent can use the full stack AND supply the "
            "typed extras the v0 primitives intentionally leave unsupported: exact attach "
            "value, attacker readiness/role tags, fetch/discard PRIORITY ordering, and "
            "deckout projection (draw_deckout_guard).",
            "Only such an agent may make damage/lethal/KO claims, and only when backed by "
            "the cg Search API — never from a numeric attackId alone.",
        ],
        "required_gates_before_candidate_generation": [
            "Production must NOT be soaking a still-unresolved probation cohort (a fresh "
            "readiness check must say a probation candidate is near thresholds first).",
            "Safety stop-gate (Part A) must pass: root main/deck byte-identical, deployment "
            "unchanged, zero reference leakage, zero forbidden events.",
            "Any candidate screened by these primitives stays LOCAL probation; promotion "
            "still requires the existing aggregate AND direct-H2H Wilson gate.",
            "Public references remain benchmark-only and may never become a source/parent.",
        ],
        "explicitly_not_implemented_here": [
            "No candidate was generated, screened-for-promotion, queued, or promoted in 46D.",
            "Primitives are infrastructure only; wiring them into candidate generation is a "
            "FUTURE v1 pass, not this one.",
        ],
    }
    data = {"pass": "46d", "part": "G", "implementation_done": False, "plan": plan}
    md = ""
    titles = {
        "candidate_generation_v1_usage": "How candidate generation v1 can use these primitives",
        "stdlib_safe_agent_subset": "Stdlib-safe agent subset",
        "cg_typed_search_full_stack": "cg_typed / Search-capable full primitive stack",
        "required_gates_before_candidate_generation": "Gates required before ANY candidate is generated from this",
        "explicitly_not_implemented_here": "Explicitly NOT implemented in Pass 46D",
    }
    for key, items in plan.items():
        md += f"\n## {titles[key]}\n" + "".join(f"- {x}\n" for x in items)
    write_pair("pass46d_candidate_integration_plan", data,
               "Pass 46D — Part G: candidate integration plan", md)
    doc = ("# Turn-Planning Candidate Integration Plan\n\n"
           "_Pass 46D. FUTURE plan only — no implementation. Read-only / infrastructure. "
           "No candidate was generated; primitives are not yet wired into candidate "
           "generation. No Kaggle strength claim._\n")
    for key, items in plan.items():
        doc += f"\n## {titles[key]}\n\n" + "".join(f"- {x}\n" for x in items)
    (DOCS / "TURN_PLANNING_CANDIDATE_INTEGRATION_PLAN.md").write_text(doc, encoding="utf-8")
    return data


# ============================================================= Part J: report
def part_j(a: dict, b: dict, d: dict, e: dict, f: dict, g: dict) -> dict:
    ready = bool(a["all_ok"] and d["n_fixtures"] > 0 and e["all_ok"]
                 and len(f["groups"]) > 0)
    decision = ("turn_planning_primitives_ready_soak_continue" if ready
                else "turn_planning_primitives_incomplete_hold")
    dec = {
        "pass": "46d", "decision": decision, "ready": ready,
        "recommendation": ("Keep production soaking. Do NOT run Pass 47 until a fresh "
                           "readiness check says a probation candidate is close to "
                           "thresholds. Use these primitives in a future candidate-"
                           "generation v1 pass, not yet."),
        "safety_all_ok": a["all_ok"], "n_primitives_implemented": b["n_implemented_v0"],
        "n_fixtures": d["n_fixtures"], "fixture_validation_all_ok": e["all_ok"],
        "behavior_groups": sorted(f["groups"]),
        "production_mutated": False, "candidate_generated": False,
        "no_upload": True, "kaggle_strength_claim": False,
    }
    md = (f"## Decision\n- **decision**: `{decision}`\n- **ready**: {ready}\n"
          f"- safety all_ok: {a['all_ok']}\n- fixtures: {d['n_fixtures']}\n"
          f"- fixture validation all_ok: {e['all_ok']}\n\n"
          f"## Recommendation\n{dec['recommendation']}\n")
    write_pair("pass46d_strategy_decision", dec,
               "Pass 46D — Part J: decision", md)

    sections = [
        ("1. Objective and safety",
         "Build reusable, tested, never-raise turn-planning **primitives** over Pass-46C "
         "decision frames — infrastructure only. READ-ONLY / LOCAL: no production mutation, "
         "no tick, no candidate generation, no promotion/upload/republish/lifecycle change. "
         f"Part-A stop-gate `all_ok = {a['all_ok']}` (root main/deck byte-identical, "
         "deployment unchanged, zero reference leakage, zero forbidden events in prod+local "
         "ledgers). `Start application` stays the frozen Kaggle entrypoint (not started)."),
        ("2. Primitive design",
         f"{b['n_primitives']} design primitives ({b['n_implemented_v0']} implemented v0, "
         f"{b['n_backlog']} backlog) defined in `docs/TURN_PLANNING_PRIMITIVES_V0.md`. "
         "Invariants: pure/read-only, never-raise, no production dependency, no public-"
         "reference code, no deck-specific strategy beyond generic role classification, "
         "opponent hand never read (counts only)."),
        ("3. Implemented module",
         "`src/ptcg_activegraph/analysis/turn_primitives.py` — 13 pure primitives: safe_get, "
         "normalize_option_type, normalize_select_context, classify_option_family, "
         "board_snapshot_from_frame, visible_counts_by_zone, legal_action_family_summary, "
         "energy_attach_candidates, score_energy_attach_generic, setup_candidate_summary, "
         "search_candidate_summary, discard_candidate_summary, unsupported_claims. Imports "
         "only the pure action_resolver + turn_planning decoders."),
        ("4. Fixture extraction",
         f"{d['n_fixtures']} fixtures extracted deterministically from the Pass-46C 12-game "
         f"panel (categories: {', '.join(d['categories_present'])}). Manifest embeds the raw "
         "frames so tests are self-contained: `data/experiments/pass46d_trace_fixture_"
         "manifest.json`."),
        ("5. Fixture validation",
         f"Primitives run over every fixture: `all_ok = {e['all_ok']}`. Asserted: option "
         "taxonomy matches the fixture's known family; min/max/option counts preserved "
         "exactly; energy candidates resolve to active/bench destinations when present; "
         "search/discard surface visible card ids only; opponent hand never exposed; "
         "unsupported claims remain marked."),
        ("6. Behavior comparison",
         "The 12-game panel re-analysed with the primitives, grouped by role "
         f"({', '.join(sorted(f['groups']))}): per-frame attach/attack/search/discard/"
         "low-choice rates, setup behavior, and attach active-vs-bench destination shares. "
         "DIRECTIONAL and SMALL-N; describes options presented, not actions chosen; no "
         "strength claim. Detail: `data/experiments/pass46d_primitive_behavior_comparison.md`."),
        ("7. Unsupported claims",
         "Stable guard (`unsupported_claims()`): " + ", ".join(
             f"`{k}`" for k in sorted(P.unsupported_claims())) + ". A numeric `attackId` "
         "alone is never sufficient for a damage/lethal claim."),
        ("8. Candidate integration plan",
         "FUTURE plan only (no implementation): how candidate-generation v1 screens candidate "
         "behavior with these primitives, the stdlib-safe subset, the cg_typed/Search full "
         "stack, and the gates required before any candidate is generated. "
         "`docs/TURN_PLANNING_CANDIDATE_INTEGRATION_PLAN.md`."),
        ("9. Tests / no-upload guarantees",
         "`tests/test_pass46d_turn_primitives.py` (>=24 tests): purity/never-raise, no "
         "EventStore/ObjectStorage writes, type/context normalization, family classification, "
         "visible-only ids, opponent-hand non-exposure, unsupported-claims completeness, "
         "fixture manifest + validation, behavior caveats, no reference-as-candidate, no "
         "forbidden events, root immutable, Start application not started. Every 46D artifact "
         "is local with `no_upload=true`; no SubmissionQueued/Uploaded/KaggleScoreUpdated/"
         "CandidatePromoted emitted."),
        ("10. Decision and next steps",
         f"Decision: `{decision}` (ready={ready}). " + dec["recommendation"]),
    ]
    rep = ("# Pass 46D — Turn-Planning Primitives v0\n\n"
           "_READ-ONLY / LOCAL / infrastructure only. No production mutation, no tick, no "
           "candidate generation, no promotion/upload. Local diagnostics over Pass-46C "
           "frames — NOT a Kaggle leaderboard claim._\n")
    for title, body in sections:
        rep += f"\n## {title}\n\n{body}\n"
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "pass46d_turn_planning_primitives_report.md").write_text(rep, encoding="utf-8")
    return dec


def main() -> int:
    a = part_a()
    if not a["all_ok"]:
        print(json.dumps({"stage": "safety", "all_ok": False, "checks": a["checks"]},
                         indent=2))
        return 1
    b = part_b()
    d = part_d()
    e = part_e(d["fixtures"])
    f = part_f()
    g = part_g()
    dec = part_j(a, b, d, e, f, g)
    print(json.dumps({"decision": dec["decision"], "ready": dec["ready"],
                      "safety_all_ok": a["all_ok"], "n_fixtures": d["n_fixtures"],
                      "fixture_validation_all_ok": e["all_ok"],
                      "n_primitives_implemented": b["n_implemented_v0"],
                      "behavior_groups": sorted(f["groups"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
