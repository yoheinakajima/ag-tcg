#!/usr/bin/env python3
"""Generate Pass-12 meta-driven candidates (LOCAL only; no upload, no GitHub
push, root main.py/deck.csv untouched, NEVER invent card ids).

Five candidate groups, each recorded honestly in the manifest:

  Group 0 — controls (referenced, not generated): the live active control, the
    v1 legacy baseline, the v2 reference deck, and a historical combo. These are
    anchors the candidates must beat; they are not "new" candidates.

  Group 1 — Water playbook candidates (5): guard-combo variations of the
    confirmed Kyogre/Abomasnow playbook. HONEST: the runtime compiler (RULE_MAP)
    only wires the five Pass-8 effect-safety guards, so these differ ONLY by
    combinations of those guards. Genuinely new tempo behaviour (attack/evolve
    by turn N) is DESIGN-ONLY and recorded in each playbook's report_notes.

  Group 2 — Water deck candidates (5): rebalanced 60-card decks built strictly
    from the confirmed 11-card pool (4-copy limit; basic Water Energy exempt).
    Deck composition is a genuine runtime lever (unlike the capped guard set).

  Group 3 — replay-deck transfer (3): the three replay-derived META decks piloted
    by the generic v1 brain. Tests whether a meta deck transfers under a competent
    generic pilot. HONEST: the pilot is generic, not tuned to the deck; the deck
    ids are observed in replays, never invented.

  Group 4 — chaos scout: BLOCKED. A disruption/chaos archetype would need both
    confirmed disruption+payoff card ids (we have none beyond the confirmed pool)
    AND a runtime chaos trigger wired into RULE_MAP (none exists). Building one
    would require inventing ids — refused. Recorded as blocked.

Outputs:
  data/submissions/candidates_pass12/*.tar.gz   (top-level main.py + deck.csv)
  data/submissions/pass12_candidates_manifest.json
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tarfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from ptcg_activegraph.playbooks import load_playbook  # noqa: E402
from ptcg_activegraph.playbooks.compiler import compile_playbook  # noqa: E402
from ptcg_activegraph.playbooks.schema import CONFIRMED_CARDS  # noqa: E402
import validate_candidate_tarball as vct  # noqa: E402

BASE_PLAYBOOK = REPO / "playbooks" / "v2_kyogre_abomasnow.yaml"
GENERATED_DIR = REPO / "playbooks" / "_generated_pass12"
RUNS_ROOT = REPO / "experiments" / "runs_pass12"
DECK_VARIANT_ROOT = REPO / "data" / "baselines" / "_pass12_deck_variants"
TARBALL_DIR = REPO / "data" / "submissions" / "candidates_pass12"
MANIFEST = REPO / "data" / "submissions" / "pass12_candidates_manifest.json"
V2_BASELINE = REPO / "data" / "baselines" / "v2_kaggle_479_1_deck_energy_trim_light"
V1_BRAIN = REPO / "data" / "baselines" / "v1_kaggle_349_8" / "main.py"
CAND_DIR = REPO / "data" / "submissions" / "candidates"
REGISTRY = REPO / "data" / "kaggle_uploads" / "live_score_registry.json"
REPLAY_DECKS = REPO / "data" / "meta_replays" / "decks"

CONFIRMED_IDS = set(CONFIRMED_CARDS.values())

# v2 control deck composition (confirmed ids only); sums to 60.
BASE_DECK_COUNTS: dict[int, int] = {
    3: 29, 721: 4, 722: 4, 723: 4, 1092: 1, 1121: 4,
    1145: 2, 1163: 2, 1219: 4, 1227: 4, 1262: 2,
}

# --- Group 1: Water playbook candidates (guard-combo + design-only notes) ----
PLAYBOOK_CANDIDATES = [
    {
        "id": "pb12_kyogre_tempo",
        "hypothesis": "Attacker-first: discard protection + a light deckout guard "
                      "so Kyogre pressure starts as early as possible.",
        "patch": {
            "discard_safety": {"protect_setup": True},
            "search": {"avoid_orphan_evolution": False, "avoid_orphan_mega_signal": False},
            "effect_resolution": {"decline_mega_signal_no_snover": False},
            "deckout_guard": {"decline_threshold": 8},
        },
        "design_only": "DESIGN-ONLY: an 'attack by turn N' deadline is not wired "
                       "into RULE_MAP; only the 5 guards above are runtime-active.",
    },
    {
        "id": "pb12_fast_evolution",
        "hypothesis": "Rush Snover -> Mega Abomasnow ex: all search/evolution "
                      "guards on, willing to dig (no deckout decline).",
        "patch": {
            "discard_safety": {"protect_setup": True},
            "search": {"avoid_orphan_evolution": True, "avoid_orphan_mega_signal": True},
            "effect_resolution": {"decline_mega_signal_no_snover": True},
            "deckout_guard": {"decline_threshold": None},
        },
        "design_only": "DESIGN-ONLY: an 'evolve by turn N' deadline / forced "
                       "evolution priority is not wired into RULE_MAP.",
    },
    {
        "id": "pb12_hybrid_tempo",
        "hypothesis": "Balance attack and evolution: protect setup + guard the "
                      "Mega Signal line, stay flexible on evolution search.",
        "patch": {
            "discard_safety": {"protect_setup": True},
            "search": {"avoid_orphan_evolution": False, "avoid_orphan_mega_signal": True},
            "effect_resolution": {"decline_mega_signal_no_snover": False},
            "deckout_guard": {"decline_threshold": 8},
        },
        "design_only": "DESIGN-ONLY: dynamic attack/evolve switching by board tempo "
                       "is not wired into RULE_MAP.",
    },
    {
        "id": "pb12_bench_safety",
        "hypothesis": "Healthy bench backup, avoid long-game losses: evolution-"
                      "orphan guard on + conservative deckout decline (<=12).",
        "patch": {
            "discard_safety": {"protect_setup": True},
            "search": {"avoid_orphan_evolution": True, "avoid_orphan_mega_signal": False},
            "effect_resolution": {"decline_mega_signal_no_snover": False},
            "deckout_guard": {"decline_threshold": 12},
        },
        "design_only": "DESIGN-ONLY: a 'maintain >=2 benched backups' rule is not "
                       "wired into RULE_MAP.",
    },
    {
        "id": "pb12_attack_deadline",
        "hypothesis": "Attack before over-thinning: minimal search guards + an "
                      "aggressive deckout decline (<=4) so it commits to attacking.",
        "patch": {
            "discard_safety": {"protect_setup": True},
            "search": {"avoid_orphan_evolution": False, "avoid_orphan_mega_signal": False},
            "effect_resolution": {"decline_mega_signal_no_snover": False},
            "deckout_guard": {"decline_threshold": 4},
        },
        "design_only": "DESIGN-ONLY: a hard 'must attack by turn N' deadline is not "
                       "wired into RULE_MAP; only the deckout threshold is.",
    },
]

# --- Group 2: Water deck candidates (confirmed pool only) --------------------
DECK_CANDIDATES = [
    {
        "id": "deck12_no_secret_box",
        "hypothesis": "Drop the risky Secret Box; add a Water Energy for steadier fuel.",
        "counts": {**BASE_DECK_COUNTS, 1092: 0, 3: 30},
        "playbook_patch": {"cards": {"secret_box": None},
                           "roles": {"risky_search_cards": None}},
    },
    {
        "id": "deck12_less_draw_more_attack",
        "hypothesis": "Trim draw supporters (Lillie/Petrel 4->2), add Water Energy "
                      "to power attacks sooner.",
        "counts": {**BASE_DECK_COUNTS, 1227: 2, 1219: 2, 3: 33},
    },
    {
        "id": "deck12_powerglass_heavy",
        "hypothesis": "More Powerglass acceleration (2->4) at the cost of two energy.",
        "counts": {**BASE_DECK_COUNTS, 1163: 4, 3: 27},
    },
    {
        "id": "deck12_mega_signal_heavy",
        "hypothesis": "More Mega Signal consistency (2->4) at the cost of two energy.",
        "counts": {**BASE_DECK_COUNTS, 1145: 4, 3: 27},
    },
    {
        "id": "deck12_lean_energy_more_tools",
        "hypothesis": "Lean the energy count, add a Powerglass and a Surfing Beach "
                      "for more board tools.",
        "counts": {**BASE_DECK_COUNTS, 1163: 3, 1262: 3, 3: 27},
    },
]

# --- Group 3: replay-deck transfer (generic pilot over a meta deck) ----------
# Deck files are named by replay id; the archetype->file mapping is single-sourced
# from experiments/meta_pool.yaml (resolved at runtime in _transfer_specs()).
TRANSFER_ARCHETYPES = [
    {"id": "transfer12_metal_ex_zacian_ramp", "key": "metal_ex_zacian_ramp",
     "hypothesis": "Does the confirmed metal/Zacian ramp deck transfer under a "
                   "generic pilot and beat our control?"},
    {"id": "transfer12_water_maxbelt", "key": "water_kyogre_abomasnow_maxbelt",
     "hypothesis": "Does the confirmed Water/Maximum Belt deck transfer under a "
                   "generic pilot and beat our control?"},
    {"id": "transfer12_unknown_ex_tempo", "key": "unknown_ex_tempo",
     "hypothesis": "Does the provisional unknown-ex tempo deck transfer under a "
                   "generic pilot? (provisional archetype — weak evidence)."},
]


def _transfer_specs() -> list[dict]:
    """Resolve each transfer archetype to its real replay deck via meta_pool."""
    pool = yaml.safe_load((REPO / "experiments" / "meta_pool.yaml")
                          .read_text(encoding="utf-8")) or {}
    by_key = {a["key"]: a for a in pool.get("archetypes", [])}
    specs = []
    for t in TRANSFER_ARCHETYPES:
        arch = by_key.get(t["key"]) or {}
        deck = arch.get("surrogate_deck")
        specs.append({**t, "deck": (REPO / deck) if deck else None})
    return specs

# --- Group 4: chaos scout (BLOCKED) -----------------------------------------
CHAOS_BLOCKED = [
    {"id": "chaos12_disruption_lock",
     "reason": "No confirmed disruption+payoff card ids exist beyond the confirmed "
               "11-card pool, and no runtime chaos trigger is wired into RULE_MAP. "
               "Building this would require inventing ids — refused."},
]


def _apply_patch(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for section, kv in patch.items():
        sec = out.setdefault(section, {})
        if not isinstance(sec, dict):
            sec = {}
            out[section] = sec
        for k, v in kv.items():
            if v is None:
                sec.pop(k, None)
            else:
                sec[k] = v
    return out


def _counts_to_deck(counts: dict[int, int]) -> list[int]:
    deck: list[int] = []
    for cid, n in counts.items():
        deck.extend([cid] * n)
    return deck


def _write_deck_variant_dir(spec: dict) -> Path:
    counts = spec["counts"]
    bad = [cid for cid in counts if cid not in CONFIRMED_IDS and counts[cid] > 0]
    if bad:
        raise ValueError(f"{spec['id']} uses unconfirmed ids {bad}")
    deck = _counts_to_deck(counts)
    if len(deck) != 60:
        raise ValueError(f"{spec['id']} deck has {len(deck)} cards, expected 60")
    over = {cid: n for cid, n in counts.items() if cid != 3 and n > 4}
    if over:
        raise ValueError(f"{spec['id']} exceeds 4-copy limit: {over}")
    vdir = DECK_VARIANT_ROOT / spec["id"]
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "deck.csv").write_text("\n".join(str(c) for c in deck) + "\n",
                                   encoding="utf-8")
    return vdir


def _package(run_dir: Path, candidate_id: str) -> Path:
    TARBALL_DIR.mkdir(parents=True, exist_ok=True)
    out = TARBALL_DIR / f"{candidate_id}.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        tar.add(run_dir / "main.py", arcname="main.py")
        tar.add(run_dir / "deck.csv", arcname="deck.csv")
    return out


def _active_control_name() -> str:
    if REGISTRY.exists():
        reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
        fn = (reg.get("active_control") or {}).get("filename") or ""
        if fn:
            return fn.replace(".tar.gz", "")
    return "combo_full_safety_v3_fixed"


def _controls() -> list[dict]:
    """Group 0: reference existing anchors (no generation)."""
    ac = _active_control_name()
    rows = [
        {"id": ac, "kind": "control", "role": "active_control", "status": "referenced",
         "validated": (CAND_DIR / f"{ac}.tar.gz").exists(),
         "artifact": str((CAND_DIR / f"{ac}.tar.gz").relative_to(REPO)),
         "note": "Live active control; the baseline candidates must beat."},
        {"id": "v1_kaggle_349_8", "kind": "control", "role": "legacy_baseline",
         "status": "referenced", "validated": V1_BRAIN.exists(),
         "artifact": str(V1_BRAIN.parent.relative_to(REPO)),
         "note": "v1 legacy baseline (lineage only)."},
        {"id": "deck_energy_trim_light", "kind": "control", "role": "reference_v2",
         "status": "referenced",
         "validated": (CAND_DIR / "deck_energy_trim_light.tar.gz").exists(),
         "artifact": str((CAND_DIR / "deck_energy_trim_light.tar.gz").relative_to(REPO)),
         "note": "v2 reference deck."},
        {"id": "combo_full_safety_v3", "kind": "control", "role": "historical_combo",
         "status": "referenced",
         "validated": (CAND_DIR / "combo_full_safety_v3.tar.gz").exists(),
         "artifact": str((CAND_DIR / "combo_full_safety_v3.tar.gz").relative_to(REPO)),
         "note": "Pre-fix combo, kept as a historical reference."},
    ]
    return rows


def main() -> int:
    base = load_playbook(BASE_PLAYBOOK)
    results: list[dict] = []
    ts_n = 0

    print("== group 0: controls (referenced) ==")
    for r in _controls():
        results.append(r)
        print(f"  {r['id']:<34} role={r['role']} present={r['validated']}")

    print("== group 1: water playbook candidates ==")
    for spec in PLAYBOOK_CANDIDATES:
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        pb = _apply_patch(base, spec["patch"])
        pb["deck_id"] = spec["id"]
        notes = list(pb.get("report_notes", []))
        notes.append(spec["design_only"])
        notes.append(f"tempo hypothesis: {spec['hypothesis']}")
        pb["report_notes"] = notes
        pb_path = GENERATED_DIR / f"{spec['id']}.yaml"
        pb_path.write_text(yaml.safe_dump(pb, sort_keys=False, allow_unicode=True),
                           encoding="utf-8")
        ts = f"20260618_pass12_{ts_n:02d}"
        ts_n += 1
        run_dir = compile_playbook(pb_path, spec["id"], runs_root=RUNS_ROOT,
                                   baseline_dir=V2_BASELINE, root_main=REPO / "main.py",
                                   hypothesis=spec["hypothesis"], ts=ts)
        tarball = _package(Path(run_dir), spec["id"])
        rc = vct.validate(str(tarball))
        results.append({"id": spec["id"], "kind": "playbook", "group": "water_playbook",
                        "tarball": str(tarball.relative_to(REPO)),
                        "validated": rc == 0, "status": "built",
                        "design_only_note": spec["design_only"],
                        "hypothesis": spec["hypothesis"]})
        print(f"  {spec['id']:<34} validated={rc == 0}")

    print("== group 2: water deck candidates (confirmed pool) ==")
    for spec in DECK_CANDIDATES:
        vdir = _write_deck_variant_dir(spec)
        if spec.get("playbook_patch"):
            GENERATED_DIR.mkdir(parents=True, exist_ok=True)
            pb = _apply_patch(base, spec["playbook_patch"])
            pb["deck_id"] = spec["id"]
            pb_path = GENERATED_DIR / f"{spec['id']}.yaml"
            pb_path.write_text(yaml.safe_dump(pb, sort_keys=False, allow_unicode=True),
                               encoding="utf-8")
        else:
            pb_path = BASE_PLAYBOOK
        ts = f"20260618_pass12_{ts_n:02d}"
        ts_n += 1
        run_dir = compile_playbook(pb_path, spec["id"], runs_root=RUNS_ROOT,
                                   baseline_dir=vdir, root_main=REPO / "main.py",
                                   hypothesis=spec["hypothesis"], ts=ts)
        tarball = _package(Path(run_dir), spec["id"])
        rc = vct.validate(str(tarball))
        results.append({"id": spec["id"], "kind": "deck", "group": "water_deck",
                        "tarball": str(tarball.relative_to(REPO)),
                        "validated": rc == 0, "status": "built",
                        "deck_counts": {str(k): v for k, v in spec["counts"].items() if v},
                        "hypothesis": spec["hypothesis"]})
        print(f"  {spec['id']:<34} validated={rc == 0}")

    print("== group 3: replay-deck transfer (generic pilot) ==")
    # Build a single generic pilot brain: the base playbook compiled with no
    # patch. The compiled main.py is deck-agnostic (it reads its sibling deck.csv
    # via _load_deck_ids and its embedded fallback only fires when no deck.csv is
    # reachable — which never happens in our shipped tarballs). The raw v1/v2
    # baseline brains are NOT used: they fail the validator's no-"select" step-0
    # shapes (they only return the deck when "select" is present and null).
    pilot_dir = compile_playbook(BASE_PLAYBOOK, "transfer12_pilot", runs_root=RUNS_ROOT,
                                 baseline_dir=V2_BASELINE, root_main=REPO / "main.py",
                                 hypothesis="Generic v2-family pilot for deck transfer.",
                                 ts=f"20260618_pass12_{ts_n:02d}")
    ts_n += 1
    pilot_main = Path(pilot_dir) / "main.py"
    for spec in _transfer_specs():
        deck_src = spec["deck"]
        if not deck_src or not deck_src.exists():
            results.append({"id": spec["id"], "kind": "transfer", "group": "transfer",
                            "status": "blocked", "validated": False,
                            "reason": f"replay deck missing for {spec['key']}"})
            print(f"  {spec['id']:<34} BLOCKED: deck missing")
            continue
        tdir = DECK_VARIANT_ROOT / spec["id"]
        tdir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pilot_main, tdir / "main.py")
        shutil.copy2(deck_src, tdir / "deck.csv")
        tarball = _package(tdir, spec["id"])
        rc = vct.validate(str(tarball))
        results.append({"id": spec["id"], "kind": "transfer", "group": "transfer",
                        "tarball": str(tarball.relative_to(REPO)),
                        "validated": rc == 0, "status": "built",
                        "pilot": "generic v2-family compiled brain (not tuned to "
                                 "this deck); deck read from sibling deck.csv",
                        "deck_source": str(deck_src.relative_to(REPO)),
                        "hypothesis": spec["hypothesis"]})
        print(f"  {spec['id']:<34} validated={rc == 0}")

    print("== group 4: chaos scout (BLOCKED) ==")
    for spec in CHAOS_BLOCKED:
        results.append({"id": spec["id"], "kind": "chaos", "group": "chaos",
                        "status": "blocked", "validated": False,
                        "reason": spec["reason"]})
        print(f"  {spec['id']:<34} BLOCKED")

    built = [r for r in results if r.get("status") == "built"]
    blocked = [r for r in results if r.get("status") == "blocked"]
    manifest = {
        "schema": "activegraph.pass12.candidates/v1",
        "note": ("LOCAL research only. No upload, no GitHub push, root "
                 "main.py/deck.csv untouched, no invented card ids. Playbook "
                 "candidates differ ONLY by the 5 wired guards; deeper tempo is "
                 "DESIGN-ONLY (see each playbook report_notes)."),
        "controls": [r for r in results if r.get("kind") == "control"],
        "built": built,
        "blocked": blocked,
        "all_built_validated": all(r["validated"] for r in built),
        "counts": {"controls": sum(1 for r in results if r.get("kind") == "control"),
                   "built": len(built), "blocked": len(blocked)},
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nmanifest -> {MANIFEST.relative_to(REPO)}")
    print(f"built={len(built)} blocked={len(blocked)} "
          f"all_built_validated={manifest['all_built_validated']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
