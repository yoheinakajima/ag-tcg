#!/usr/bin/env python3
"""Pass 25 (Parts E+F) — build the Water live-control hardening candidates.

LOCAL ONLY. NO Kaggle upload, NO GitHub push, NO deck change to the proven base
(deck.csv is copied BYTE-IDENTICAL from core_pilot_water_v2_runtime), NO invented
card ids. Tarballs hold top-level main.py + deck.csv ONLY (stdlib-only main.py).

Three narrow, evidence-grounded candidates are compiled over the proven deck-safe
base. Each isolates exactly ONE delta from the control (the Pass-22 pivot, which
runs contexts (0,7,8) with the three Pass-22 hooks):

  * deckout_guard_v1        — pivot hooks + wire ctx38 so the existing, already-safe
                              draw-count clamp (keep >=1 card in deck; only bites at
                              low deck; never touches attacks) becomes live.
  * prize_liability_guard_v1— pivot hooks + the flag-gated ctx7 prize_liability_search
                              _pivot: when our board leans on the 2-prize Mega payoff
                              line and we have NO 1-prize attacker in play, fetch a
                              Kyogre so the Mega ex is never our lone attacker.
  * hybrid_guard_v1         — both of the above.

HONEST CAVEAT (Part C + fixture evidence): the proven base search scoring already
fetches the 1-prize attacker in nearly all prize-liability windows, and ctx38
barely appears in replays. These hooks are therefore near-no-op deltas; they are
built to be *measured* (decision-replay + league), not assumed beneficial.

Recovery trainers (Night Stretcher 1097 / Sacred Ash 1129) are VALIDATED real but
BLOCKED pre-build: the pilot has no runtime hook to play recovery Items, so a deck
change would only dilute the proven 60. See pass25_recovery_evaluation.json.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util as _ilu
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401
from ptcg_activegraph.pilot.compiler import (  # noqa: E402
    compile_candidate_source, load_playbook, make_tarball)

_p17_spec = _ilu.spec_from_file_location(
    "build_pass17_candidates",
    Path(__file__).resolve().parent / "build_pass17_candidates.py")
_p17 = _ilu.module_from_spec(_p17_spec)
_p17_spec.loader.exec_module(_p17)  # type: ignore[union-attr]

REPO = Path(__file__).resolve().parents[1]
V2_TARBALL = _p17.V2_TARBALL
OUT_ROOT = REPO / "data" / "submissions" / "candidates_pass25"
RUNS_ROOT = REPO / "experiments" / "runs_pass25"
CARD_DB = REPO / "data" / "cards" / "EN_Card_Data.csv"
RECOVERY_PATH = REPO / "data" / "experiments" / "pass25_recovery_evaluation.json"

PLAYBOOK = "playbooks/pass25_water_hardening.yaml"
CONTROL_ID = "league_water_anti_disruption_pivot_v1"  # Pass-22 pivot = control

# Per-candidate deltas. flags merge onto the playbook's base flags (the three
# Pass-22 hooks are already true in the playbook). runtime_contexts gate which
# compiler branches fire; (0,7,8) == control, +38 adds the draw-count clamp.
CANDIDATES = [
    {
        "id": "deckout_guard_v1",
        "flags": {},
        "runtime_contexts": (0, 7, 8, 38),
        "delta": "wire ctx38 draw-count deckout clamp (keep >=1 card in deck)",
        "hooks": [
            {"context": 0, "name": "emergency_backup_bench"},
            {"context": 7, "name": "anti_disruption_search_pivot"},
            {"context": 8, "name": "preserve_backup_basic_on_discard"},
            {"context": 38, "name": "deckout_drawcount_clamp"},
        ],
        "motivation": "mirror/grind deckout (80622626) — defensive draw-count clamp; "
                      "honest caveat: ctx38 is rare in replays and does NOT address "
                      "the observed forced-search deckout vector (ctx7 is forced).",
    },
    {
        "id": "prize_liability_guard_v1",
        "flags": {"prize_liability_search_pivot": True},
        "runtime_contexts": (0, 7, 8),
        "delta": "ctx7 prize_liability_search_pivot (keep a 1-prize backup attacker)",
        "hooks": [
            {"context": 0, "name": "emergency_backup_bench"},
            {"context": 7, "name": "anti_disruption_search_pivot"},
            {"context": 7, "name": "prize_liability_search_pivot"},
            {"context": 8, "name": "preserve_backup_basic_on_discard"},
        ],
        "motivation": "Fighting/Mega prize-liability (80623232, backup_attacker=False) "
                      "— avoid a lone 2-prize Mega ex; honest caveat: base already "
                      "fetches the 1-prize attacker in nearly all windows, so the "
                      "delta only appears on two-Mega-payoff boards.",
    },
    {
        "id": "hybrid_guard_v1",
        "flags": {"prize_liability_search_pivot": True},
        "runtime_contexts": (0, 7, 8, 38),
        "delta": "prize_liability_search_pivot + ctx38 draw-count clamp",
        "hooks": [
            {"context": 0, "name": "emergency_backup_bench"},
            {"context": 7, "name": "anti_disruption_search_pivot"},
            {"context": 7, "name": "prize_liability_search_pivot"},
            {"context": 8, "name": "preserve_backup_basic_on_discard"},
            {"context": 38, "name": "deckout_drawcount_clamp"},
        ],
        "motivation": "both seams combined; same near-no-op caveats as its parts.",
    },
]


def _load_base():
    v2_main = _p17._read_tar_member(V2_TARBALL, "main.py")
    base_main = _p17.extract_base_main(v2_main)
    deck_csv = _p17._read_tar_member(V2_TARBALL, "deck.csv")
    deck_ids = [l for l in deck_csv.splitlines() if l.strip()]
    if len(deck_ids) != 60:
        raise ValueError(f"base deck has {len(deck_ids)} cards, expected 60")
    return base_main, deck_csv, deck_ids


def build_candidate(spec: dict, base_main: str, deck_csv: str, deck_ids: list) -> dict:
    playbook = load_playbook(REPO / PLAYBOOK)
    cid = spec["id"]
    src = compile_candidate_source(
        base_main, playbook, cid,
        flags=spec["flags"] or None,
        runtime_contexts=spec["runtime_contexts"])

    out_dir = RUNS_ROOT / cid
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "main.py").write_text(src, encoding="utf-8")
    (out_dir / "deck.csv").write_text(deck_csv, encoding="utf-8")

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    tar_path = OUT_ROOT / (cid + ".tar.gz")
    make_tarball(out_dir, tar_path)

    merged_flags = dict(playbook.get("flags") or {})
    merged_flags.update(spec["flags"])
    return {
        "candidate_id": cid,
        "based_on": "core_pilot_water_v2_runtime",
        "control": CONTROL_ID,
        "playbook": PLAYBOOK,
        "delta_vs_control": spec["delta"],
        "runtime_contexts": list(spec["runtime_contexts"]),
        "flags": merged_flags,
        "hooks": spec["hooks"],
        "motivation": spec["motivation"],
        "run_dir": str(out_dir.relative_to(REPO)),
        "tarball": str(tar_path.relative_to(REPO)),
        "deck_size": len(deck_ids),
        "deck_byte_identical_to": str(V2_TARBALL.relative_to(REPO)),
        "main_bytes": len(src),
        "upload_performed": False,
        "github_push_performed": False,
    }


def evaluate_recovery() -> dict:
    """Validate the recovery card ids against the real card DB, then record the
    pre-build BLOCK decision (no runtime mechanism to play them; deck dilution)."""
    rows = {}
    if CARD_DB.exists():
        for r in csv.DictReader(open(CARD_DB, encoding="utf-8")):
            try:
                rows[int(r["Card ID"])] = r
            except (KeyError, ValueError, TypeError):
                continue
    ids = {1097: "Night Stretcher", 1129: "Sacred Ash"}
    validated = []
    for cid, name in ids.items():
        row = rows.get(cid)
        validated.append({
            "card_id": cid,
            "expected_name": name,
            "found": row is not None,
            "db_name": (row or {}).get("Card Name"),
            "category": (row or {}).get("Stage (Pokémon)/Type (Energy and Trainer)"),
            "real_id": row is not None and (row or {}).get("Card Name") == name,
        })
    all_real = all(v["real_id"] for v in validated)
    ev = {
        "pass": "25", "part": "E/F", "no_upload": True, "local_only": True,
        "ids_validated": validated,
        "all_ids_real": all_real,
        "decision": "blocked_pre_build" if all_real else "blocked_invalid_ids",
        "candidates_blocked": ["recovery_deck_v1", "recovery_hybrid_v1"],
        "block_reasons": [
            "The pilot exposes NO runtime hook that proactively PLAYS a recovery "
            "Item (Night Stretcher / Sacred Ash) from hand; broad Main stays "
            "delegated to the base policy and the compiler only refines narrow "
            "sub-actions at ctx 0/1/2/7/8/38, none of which plays these Items.",
            "A deck change would swap proven cards out of the byte-identical 60 for "
            "cards the policy can never use on purpose -> pure dilution + added "
            "variance, expected neutral-to-negative.",
            "recovery_hybrid_v1 depends on recovery_deck_v1, which is blocked.",
        ],
        "guardrails": {"deck_changed": False, "invented_ids": False},
        "note": "IDs validate as real Item cards; the candidates are intentionally "
                "NOT built. Building them would require a runtime play hook first.",
    }
    RECOVERY_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECOVERY_PATH.write_text(json.dumps(ev, indent=2), encoding="utf-8")
    return ev


def _strip_existing(path, predicate) -> int:
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
        if predicate(ev):
            removed += 1
        else:
            kept.append(line)
    p.write_text(("\n".join(kept) + ("\n" if kept else "")), encoding="utf-8")
    return removed


def emit_events(infos: list, recovery: dict) -> int:
    sys.path.insert(0, str(REPO / "src"))
    from ptcg_activegraph.graph.events import EventType, new_event
    from ptcg_activegraph.graph.event_store import EventStore
    from ptcg_activegraph.experiments.config import LAB_EVENTS_PATH

    def is_p25_build(ev: dict) -> bool:
        tags = ev.get("tags") or []
        return "pass25" in tags and "build" in tags

    removed = _strip_existing(LAB_EVENTS_PATH, is_p25_build)
    if removed:
        print(f"removed {removed} stale pass25 build events (idempotent re-run)")
    store = EventStore(LAB_EVENTS_PATH)
    n = 0

    store.append(new_event(
        EventType.StrategyFamilyRegistered, tags=["pass25", "build"],
        payload={
            "family": "water_live_control_hardening",
            "parent_reference": CONTROL_ID,
            "seams": ["prize_liability (80623232)", "deckout (80622626)"],
            "motivation": "harden the proven water core against two replay-grounded "
                          "loss seams with narrow, flag-gated levers",
            "no_upload": True,
        }))
    n += 1

    for info in infos:
        store.append(new_event(
            EventType.StrategyIterationCreated, tags=["pass25", "build"],
            payload={
                "candidate_id": info["candidate_id"],
                "family": "water_live_control_hardening",
                "control": CONTROL_ID,
                "delta_vs_control": info["delta_vs_control"],
                "runtime_contexts": info["runtime_contexts"],
                "hooks": [h["name"] for h in info["hooks"]],
                "deck": "byte-identical to core_pilot_water_v2 (no deck change)",
                "tarball": info["tarball"],
                "no_upload": True,
            }))
        n += 1
        for h in info["hooks"]:
            store.append(new_event(
                EventType.StrategyHypothesisLogged, tags=["pass25", "build", "hook"],
                payload={
                    "candidate_id": info["candidate_id"],
                    "context": h["context"], "hook": h["name"],
                    "flag_gated": True, "narrow": True, "no_upload": True,
                }))
            n += 1
        store.append(new_event(
            EventType.SubmissionPackaged, tags=["pass25", "build"],
            payload={
                "candidate_id": info["candidate_id"], "tarball": info["tarball"],
                "top_level_only": ["main.py", "deck.csv"],
                "queued_for_upload": False, "no_upload": True,
            }))
        n += 1

    store.append(new_event(
        EventType.StrategyBlocked, tags=["pass25", "build", "recovery"],
        payload={
            "candidates": recovery["candidates_blocked"],
            "ids_validated": recovery["ids_validated"],
            "all_ids_real": recovery["all_ids_real"],
            "decision": recovery["decision"],
            "reasons": recovery["block_reasons"],
            "no_upload": True,
        }))
    n += 1
    print(f"emitted {n} pass25 build events -> {LAB_EVENTS_PATH}")
    return n


def _write_manifest(infos: list, recovery: dict) -> None:
    manifest = {
        "pass": "25", "part": "E/F", "local_only": True,
        "upload_performed": False, "github_push_performed": False, "no_upload": True,
        "base_from": str(V2_TARBALL.relative_to(REPO)),
        "control": CONTROL_ID,
        "justified_by": [
            "data/experiments/pass25_loss_seam_analysis.json",
            "data/experiments/pass25_loss_windows.jsonl",
        ],
        "candidates": infos,
        "recovery_evaluation": str(RECOVERY_PATH.relative_to(REPO)),
        "recovery_decision": recovery["decision"],
        "honest_caveat": "prize_liability hook is near-no-op vs base (base already "
                         "fetches the 1-prize attacker); ctx38 is rare in replays. "
                         "Candidates are built to be measured, not assumed beneficial.",
        "guardrails": {
            "deck_changed": False, "invented_ids": False,
            "broad_main_override": False,
            "narrow_hooks_only": True,
            "tarball_top_level_only": ["main.py", "deck.csv"],
        },
    }
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    (RUNS_ROOT / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")

    lines = [
        "# Pass 25 — Water Live-Control Hardening candidates (Parts E+F)",
        "",
        "**LOCAL ONLY** — no Kaggle upload, no GitHub push, deck byte-identical to "
        f"`{Path(V2_TARBALL).name}` (60 cards), no invented ids, tarballs = top-level "
        "`main.py` + `deck.csv` only.",
        "",
        f"Control (live-active family reference): `{CONTROL_ID}` — contexts (0,7,8).",
        "",
        "## Candidates",
        "",
        "| candidate | delta vs control | runtime_contexts |",
        "|---|---|---|",
    ]
    for info in infos:
        lines.append(f"| `{info['candidate_id']}` | {info['delta_vs_control']} | "
                     f"{tuple(info['runtime_contexts'])} |")
    lines += [
        "",
        "## Honest caveat",
        "",
        "The proven base search scoring already fetches the 1-prize attacker in "
        "nearly all prize-liability windows, and ctx38 barely appears in replays. "
        "These hooks are therefore **near-no-op** deltas — built to be *measured* "
        "(decision-replay + internal league), not assumed beneficial.",
        "",
        "## Recovery candidates — VALIDATED then BLOCKED pre-build",
        "",
        f"Decision: `{recovery['decision']}` for "
        f"{', '.join(recovery['candidates_blocked'])}.",
        "",
    ]
    for v in recovery["ids_validated"]:
        lines.append(f"- `{v['card_id']}` {v['db_name']} — real Item card: "
                     f"{v['real_id']}")
    lines += [""]
    for r in recovery["block_reasons"]:
        lines.append(f"- {r}")
    lines += ["", f"See `{RECOVERY_PATH.relative_to(REPO)}`.", ""]
    (RUNS_ROOT / "manifest.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"manifest -> {(RUNS_ROOT / 'manifest.json').relative_to(REPO)} (+ .md)")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-events", action="store_true",
                    help="skip ActiveGraph event emission")
    args = ap.parse_args()

    base_main, deck_csv, deck_ids = _load_base()
    infos = [build_candidate(s, base_main, deck_csv, deck_ids) for s in CANDIDATES]
    for info in infos:
        print(f"built {info['candidate_id']}: contexts={tuple(info['runtime_contexts'])} "
              f"deck={info['deck_size']} -> {info['tarball']}")

    recovery = evaluate_recovery()
    print(f"recovery: {recovery['decision']} (all_ids_real={recovery['all_ids_real']}) "
          f"-> {RECOVERY_PATH.relative_to(REPO)}")

    _write_manifest(infos, recovery)
    if not args.no_events:
        emit_events(infos, recovery)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
