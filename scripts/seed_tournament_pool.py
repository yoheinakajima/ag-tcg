#!/usr/bin/env python3
"""Pass 36 — seed the canonical candidate pool from EXISTING local tarballs.

No new candidates are created. Tarballs are immutable; we only read them to
compute provenance fingerprints and validation status. Special-pilot-only
entries are registered but inactive. Internal diagnostics only; NO upload.

Usage: python scripts/seed_tournament_pool.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import tarfile
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament import pool as poolmod  # noqa: E402
from ptcg_activegraph.tournament.config import load_config  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.graph.events import EventType  # noqa: E402

SUB = REPO / "data" / "submissions"

# Canonical seed plan: every entry points at an EXISTING tarball in the repo.
# (candidate_id, family_id, generation, parent, tarball_relpath, status, source_pass, note)
A, H, F, P = (poolmod.ACTIVE, poolmod.HELD_PROBE,
              poolmod.FAMILY_CHAMPION, poolmod.PORTFOLIO_ANCHOR)
SPECIAL, RET = poolmod.SPECIAL_PILOT_ONLY, poolmod.RETIRED

SEED = [
    # --- water live/control family ---
    ("league_water_anti_disruption_pivot_v1", "water", 1, "league_water_core_reference",
     "candidates_pass33/league_water_anti_disruption_pivot_v1.tar.gz", P, "pass33",
     "Water anti-disruption pivot; portfolio anchor for the live water line."),
    ("league_water_core_reference", "water", 0, None,
     "candidates_pass33/league_water_core_reference.tar.gz", F, "pass33",
     "Water family champion / control reference."),
    ("water_basic_density_v1", "water", 1, "league_water_core_reference",
     "candidates_pass33/water_basic_density_v1.tar.gz", H, "pass33",
     "Held dry-run probe (currently in submission queue). Stays held; not submitted."),
    ("core_pilot_water_v2_runtime", "water", -1, None,
     "candidates_pass33/core_pilot_water_v2_runtime.tar.gz", RET, "pass33",
     "Older water grandparent superseded by core_reference; retained, not deleted."),
    # --- dragapult family ---
    ("league_dragapult_v1_search_only", "dragapult", 1, "league_dragapult_spread",
     "candidates_pass33/league_dragapult_v1_search_only.tar.gz", P, "pass33",
     "Dragapult search-only portfolio reference."),
    ("league_dragapult_spread", "dragapult", 0, None,
     "candidates_pass33/league_dragapult_spread.tar.gz", A, "pass33",
     "Dragapult spread parent (spread attack UNSUPPORTED honesty caveat applies)."),
    # --- single-family portfolio references ---
    ("mono_lightning_miraidon_easy", "lightning", 0, None,
     "candidates_pass34/mono_lightning_miraidon_easy.tar.gz", P, "pass34",
     "Mono-lightning Miraidon portfolio reference."),
    ("diamond_toolbox_diancie", "diamond", 0, None,
     "candidates_pass34/diamond_toolbox_diancie.tar.gz", P, "pass34",
     "Diamond toolbox (Diancie) portfolio reference."),
    # --- mega family champions (pass33) + typed35 children (pass35) ---
    ("league_mega_venusaur_tank", "mega_venusaur", 0, None,
     "candidates_pass33/league_mega_venusaur_tank.tar.gz", F, "pass33",
     "Mega Venusaur tank family champion."),
    ("mega_venusaur_tank_typed35", "mega_venusaur", 1, "league_mega_venusaur_tank",
     "candidates_pass35/mega_venusaur_tank.tar.gz", A, "pass35",
     "Typed-lite child (Pass 35). NOT a proven win-rate gain; under evaluation."),
    ("league_mega_charizard_x_burst", "mega_charizard", 0, None,
     "candidates_pass33/league_mega_charizard_x_burst.tar.gz", F, "pass33",
     "Mega Charizard X burst family champion."),
    ("mega_charizard_x_burst_typed35", "mega_charizard", 1, "league_mega_charizard_x_burst",
     "candidates_pass35/mega_charizard_x_burst.tar.gz", A, "pass35",
     "Typed-lite child (Pass 35). NOT a proven win-rate gain; under evaluation."),
    ("league_mega_gardevoir_psychic_ramp", "mega_gardevoir", 0, None,
     "candidates_pass33/league_mega_gardevoir_psychic_ramp.tar.gz", F, "pass33",
     "Mega Gardevoir psychic-ramp family champion."),
    ("mega_gardevoir_psychic_ramp_typed35", "mega_gardevoir", 1, "league_mega_gardevoir_psychic_ramp",
     "candidates_pass35/mega_gardevoir_psychic_ramp.tar.gz", A, "pass35",
     "Typed-lite child (Pass 35). NOT a proven win-rate gain; under evaluation."),
    # --- special-pilot-only (registered, inactive, never scheduled) ---
    ("toxic_trap_poison_lock", "toxic", 0, None,
     "candidates_pass34/toxic_trap_poison_lock.tar.gz", SPECIAL, "pass34",
     "Special-pilot-only: requires a poison-lock pilot that does not exist yet."),
    ("deckout_carousel_durant_v2", "durant", 0, None,
     "candidates_pass34/deckout_carousel_durant_v2.tar.gz", SPECIAL, "pass34",
     "Special-pilot-only: requires a deckout-carousel pilot that does not exist yet."),
]


def _load_validator():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "validate_candidate_tarball", REPO / "scripts" / "validate_candidate_tarball.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def _fingerprints(tarball: Path) -> tuple[str | None, str | None]:
    main_fp = deck_fp = None
    try:
        with tarfile.open(tarball, "r:gz") as tar:
            for m in tar.getmembers():
                name = Path(m.name).name
                if name == "main.py" and main_fp is None:
                    main_fp = hashlib.sha256(tar.extractfile(m).read()).hexdigest()
                elif name == "deck.csv" and deck_fp is None:
                    deck_fp = hashlib.sha256(tar.extractfile(m).read()).hexdigest()
    except Exception:
        pass
    return main_fp, deck_fp


def main() -> int:
    cfg = load_config()
    validator = _load_validator()
    cands: list[poolmod.Candidate] = []
    for (cid, fam, gen, parent, rel, status, src, note) in SEED:
        tar = SUB / rel
        exists = tar.exists()
        main_fp = deck_fp = None
        vstatus = "missing"
        if exists:
            main_fp, deck_fp = _fingerprints(tar)
            try:
                vstatus = "valid" if validator.validate(str(tar)) == 0 else "invalid"
            except Exception as exc:  # noqa: BLE001
                vstatus = f"error:{type(exc).__name__}"
        eff_status = status if exists else poolmod.QUARANTINED
        cands.append(poolmod.Candidate(
            candidate_id=cid, family_id=fam, generation=gen,
            parent_candidate_id=parent, tarball_path=rel,
            deck_fingerprint=deck_fp, main_fingerprint=main_fp,
            status=eff_status, source_pass=src,
            validation_status=vstatus,
            entrypoint_status=("ok" if vstatus == "valid" else vstatus),
            smoke_status="unknown",
            tags=[fam, src, "pass36_seed"], no_upload=True,
            status_note=note if exists else f"tarball missing: {rel}",
        ))

    pool = poolmod.CandidatePool(cands, tournament_id=cfg.tournament_id)
    pool_path = pool.save()
    stats = pool.stats()

    # Markdown projection of the pool.
    proj_dir = REPO / "data" / "tournament" / "projections"
    proj_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# Tournament Candidate Pool (Pass 36 seed)", "",
             "_Internal diagnostics only — NOT a Kaggle leaderboard. Tarballs immutable; "
             "status marks only. NO upload._", "",
             f"- tournament: `{pool.tournament_id}`",
             f"- total registered: {len(cands)}  ·  schedulable/active: {pool.active_count()} "
             f"(soft cap {cfg.active_soft_cap}, hard cap {cfg.active_hard_cap})",
             f"- status counts: {stats}", "",
             "| candidate_id | family | gen | parent | status | validation | source |",
             "|---|---|---|---|---|---|---|"]
    for c in cands:
        lines.append(f"| {c.candidate_id} | {c.family_id} | {c.generation} | "
                     f"{c.parent_candidate_id or '—'} | {c.status} | "
                     f"{c.validation_status} | {c.source_pass} |")
    (proj_dir / "candidate_pool.md").write_text("\n".join(lines) + "\n")

    # Experiment artifacts.
    seed_rec = {
        "pass": "pass36", "tournament_id": pool.tournament_id,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "no_upload": True, "total": len(cands), "schedulable": pool.active_count(),
        "active_soft_cap": cfg.active_soft_cap, "active_hard_cap": cfg.active_hard_cap,
        "status_counts": stats,
        "special_pilot_only": [c.candidate_id for c in cands
                               if c.status == poolmod.SPECIAL_PILOT_ONLY],
        "held_probe": [c.candidate_id for c in cands if c.status == poolmod.HELD_PROBE],
        "pool_path": str(pool_path.relative_to(REPO)),
    }
    exp = REPO / "data" / "experiments"
    (exp / "pass36_candidate_pool_seed.json").write_text(json.dumps(seed_rec, indent=2))
    (exp / "pass36_candidate_pool_seed.md").write_text(
        f"# Pass 36 — Candidate Pool Seed\n\n_Generated {seed_rec['generated_at']} · "
        "internal only · NO upload_\n\n"
        f"- registered: {len(cands)}; schedulable: {pool.active_count()}\n"
        f"- status counts: {stats}\n"
        f"- held probe (stays held): {seed_rec['held_probe']}\n"
        f"- special-pilot-only (registered, never scheduled): "
        f"{seed_rec['special_pilot_only']}\n"
        f"- pool file: `{seed_rec['pool_path']}`\n")

    # Event-first: record the pool update on the ledger.
    ledger = TournamentLedger()
    ledger.emit(EventType.CandidatePoolUpdated, {
        "tournament_id": pool.tournament_id, "total": len(cands),
        "schedulable": pool.active_count(), "status_counts": stats,
        "pool_path": seed_rec["pool_path"], "source": "seed_tournament_pool",
    }, tags=["pool_seed"])

    print(f"seeded {len(cands)} candidates -> {pool_path.relative_to(REPO)}")
    print(f"schedulable={pool.active_count()} status_counts={stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
