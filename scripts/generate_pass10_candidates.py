#!/usr/bin/env python3
"""Generate Pass-10 candidates: tempo playbooks + buildable deck variants.

What this builds (LOCAL only; no Kaggle upload, no GitHub push, root
main.py/deck.csv untouched):

  * 5 tempo PLAYBOOK candidates (kyogre_tempo, fast_evolution, hybrid_tempo,
    bench_safety, attack_deadline). Each is compiled, packaged, and validated.
  * 2 DECK candidates buildable from the confirmed 11-card pool
    (deck_no_secret_box, deck_less_draw_more_attack). Compiled, packaged,
    validated.
  * A manifest that records BLOCKED deck candidates (maxbelt, cyrano_waitress,
    metal) whose card ids are NOT confirmed — never invented, never built.

HONESTY NOTE (critical): the runtime rule compiler (``RULE_MAP``) only wires the
five Pass-8 effect-safety guards. The tempo playbooks therefore differ only by
*combinations of those five guards*. Any genuinely new tempo behaviour
(evolve-by-turn / attack-by-turn deadlines, bench-backup minimums) is recorded
as DESIGN-ONLY in each playbook's report_notes and is NOT present in the packaged
runtime until a new guard is wired into the generator. We do not ship a tarball
whose behaviour we cannot actually produce.
"""

from __future__ import annotations

import copy
import json
import sys
import tarfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.playbooks import load_playbook  # noqa: E402
from ptcg_activegraph.playbooks.compiler import compile_playbook  # noqa: E402
from ptcg_activegraph.playbooks.schema import CONFIRMED_CARDS  # noqa: E402

sys.path.insert(0, str(REPO / "scripts"))
import validate_candidate_tarball as vct  # noqa: E402

BASE_PLAYBOOK = REPO / "playbooks" / "v2_kyogre_abomasnow.yaml"
GENERATED_DIR = REPO / "playbooks" / "_generated"
RUNS_ROOT = REPO / "experiments" / "runs_pass10"
DECK_VARIANT_ROOT = REPO / "data" / "baselines" / "_pass10_deck_variants"
TARBALL_DIR = REPO / "data" / "submissions" / "candidates_pass10"
MANIFEST = REPO / "data" / "submissions" / "pass10_candidates_manifest.json"
V2_BASELINE = REPO / "data" / "baselines" / "v2_kaggle_479_1_deck_energy_trim_light"

# v2 control deck composition (confirmed ids only).
BASE_DECK_COUNTS: dict[int, int] = {
    3: 29, 721: 4, 722: 4, 723: 4, 1092: 1, 1121: 4,
    1145: 2, 1163: 2, 1219: 4, 1227: 4, 1262: 2,
}

# --- tempo playbooks: guard-combo patches + honest design-only notes ---------
TEMPO_CANDIDATES = [
    {
        "id": "playbook_kyogre_tempo",
        "hypothesis": "Attacker-first: keep only discard protection + a light "
                      "deckout guard so Kyogre pressure starts as early as possible.",
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
        "id": "playbook_fast_evolution",
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
        "id": "playbook_hybrid_tempo",
        "hypothesis": "Balance attack and evolution: protect setup + guard the "
                      "Mega Signal line, but stay flexible on evolution search.",
        "patch": {
            "discard_safety": {"protect_setup": True},
            "search": {"avoid_orphan_evolution": False, "avoid_orphan_mega_signal": True},
            "effect_resolution": {"decline_mega_signal_no_snover": False},
            "deckout_guard": {"decline_threshold": 8},
        },
        "design_only": "DESIGN-ONLY: dynamic attack/evolve switching by board "
                       "tempo is not wired into RULE_MAP.",
    },
    {
        "id": "playbook_bench_safety",
        "hypothesis": "Keep a healthy bench backup and avoid long-game losses: "
                      "evolution-orphan guard on + conservative deckout decline (<=12).",
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
        "id": "playbook_attack_deadline",
        "hypothesis": "Attack before over-thinning: minimal search guards but an "
                      "aggressive deckout decline (<=4) so it commits to attacking.",
        "patch": {
            "discard_safety": {"protect_setup": True},
            "search": {"avoid_orphan_evolution": False, "avoid_orphan_mega_signal": False},
            "effect_resolution": {"decline_mega_signal_no_snover": False},
            "deckout_guard": {"decline_threshold": 4},
        },
        "design_only": "DESIGN-ONLY: a hard 'must attack by turn N' deadline is "
                       "not wired into RULE_MAP; only the deckout threshold is.",
    },
]

# --- deck candidates ---------------------------------------------------------
DECK_CANDIDATES = [
    {
        "id": "deck_no_secret_box",
        "hypothesis": "Drop the risky Secret Box entirely; add a Water Energy for "
                      "steadier attack fuel.",
        "counts": {**BASE_DECK_COUNTS, 1092: 0, 3: 30},
        # Removing the card means the playbook must stop referencing its id.
        "playbook_patch": {
            "cards": {"secret_box": None},
            "roles": {"risky_search_cards": None},
        },
    },
    {
        "id": "deck_less_draw_more_attack",
        "hypothesis": "Trim draw supporters (Lillie/Petrel 4->2) and add Water "
                      "Energy to power attacks sooner.",
        "counts": {**BASE_DECK_COUNTS, 1227: 2, 1219: 2, 3: 33},
    },
]

# --- blocked deck candidates (unconfirmed card ids; NEVER built) -------------
BLOCKED_DECK_CANDIDATES = [
    {"id": "deck_maximum_belt", "reason": "Maximum Belt id not in confirmed set"},
    {"id": "deck_cyrano_waitress",
     "reason": "Cyrano / Waitress ids not in confirmed set"},
    {"id": "deck_metal_zacian", "reason": "metal / Zacian ex ids not in confirmed set"},
]

CONFIRMED_IDS = set(CONFIRMED_CARDS.values())


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


def _write_tempo_playbook(base: dict, spec: dict) -> Path:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    pb = _apply_patch(base, spec["patch"])
    pb["deck_id"] = spec["id"]
    notes = list(pb.get("report_notes", []))
    notes.append(spec["design_only"])
    notes.append(f"tempo hypothesis: {spec['hypothesis']}")
    pb["report_notes"] = notes
    path = GENERATED_DIR / f"{spec['id']}.yaml"
    path.write_text(yaml.safe_dump(pb, sort_keys=False, allow_unicode=True),
                    encoding="utf-8")
    return path


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


def main() -> int:
    base = load_playbook(BASE_PLAYBOOK)
    results: list[dict] = []
    ts_n = 0

    print("== tempo playbook candidates ==")
    for spec in TEMPO_CANDIDATES:
        pb_path = _write_tempo_playbook(base, spec)
        ts = f"20260618_pass10_{ts_n:02d}"
        ts_n += 1
        run_dir = compile_playbook(pb_path, spec["id"], runs_root=RUNS_ROOT,
                                   baseline_dir=V2_BASELINE,
                                   root_main=REPO / "main.py",
                                   hypothesis=spec["hypothesis"], ts=ts)
        tarball = _package(Path(run_dir), spec["id"])
        rc = vct.validate(str(tarball))
        results.append({"id": spec["id"], "kind": "playbook",
                        "run_dir": str(Path(run_dir).relative_to(REPO)),
                        "tarball": str(tarball.relative_to(REPO)),
                        "validated": rc == 0, "status": "built",
                        "design_only_note": spec["design_only"]})
        print(f"  {spec['id']:<28} validated={rc == 0}")

    print("== deck candidates (buildable) ==")
    for spec in DECK_CANDIDATES:
        vdir = _write_deck_variant_dir(spec)
        # A deck that removes a card needs a playbook that stops referencing it.
        if spec.get("playbook_patch"):
            GENERATED_DIR.mkdir(parents=True, exist_ok=True)
            pb = _apply_patch(base, spec["playbook_patch"])
            pb["deck_id"] = spec["id"]
            pb_path = GENERATED_DIR / f"{spec['id']}.yaml"
            pb_path.write_text(yaml.safe_dump(pb, sort_keys=False, allow_unicode=True),
                               encoding="utf-8")
        else:
            pb_path = BASE_PLAYBOOK
        ts = f"20260618_pass10_{ts_n:02d}"
        ts_n += 1
        run_dir = compile_playbook(pb_path, spec["id"], runs_root=RUNS_ROOT,
                                   baseline_dir=vdir,
                                   root_main=REPO / "main.py",
                                   hypothesis=spec["hypothesis"], ts=ts)
        tarball = _package(Path(run_dir), spec["id"])
        rc = vct.validate(str(tarball))
        results.append({"id": spec["id"], "kind": "deck",
                        "run_dir": str(Path(run_dir).relative_to(REPO)),
                        "tarball": str(tarball.relative_to(REPO)),
                        "validated": rc == 0, "status": "built",
                        "deck_counts": {str(k): v for k, v in spec["counts"].items() if v}})
        print(f"  {spec['id']:<28} validated={rc == 0}")

    print("== blocked deck candidates (NOT built) ==")
    for spec in BLOCKED_DECK_CANDIDATES:
        results.append({"id": spec["id"], "kind": "deck",
                        "status": "blocked", "validated": False,
                        "reason": spec["reason"]})
        print(f"  {spec['id']:<28} BLOCKED: {spec['reason']}")

    manifest = {
        "schema": "activegraph.pass10.candidates/v1",
        "note": "LOCAL research only. No upload. Tempo behaviours beyond the 5 "
                "wired guards are DESIGN-ONLY (see each playbook report_notes).",
        "built": [r for r in results if r["status"] == "built"],
        "blocked": [r for r in results if r["status"] == "blocked"],
        "all_built_validated": all(r["validated"] for r in results
                                   if r["status"] == "built"),
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nmanifest -> {MANIFEST.relative_to(REPO)}")
    print(f"all built validated: {manifest['all_built_validated']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
