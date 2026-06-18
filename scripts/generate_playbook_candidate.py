#!/usr/bin/env python3
"""Generate playbook candidate(s) for ActiveGraph Pass 9 (Track B).

Two modes:

  * single:  --playbook <yaml> --candidate-id <id>
  * group:   --group pass9_playbooks   (the base v2 playbook + 5 ablations)

Each candidate is a stdlib-only run directory under ``experiments/runs_pass9/``.
Ablations are derived from the base playbook by toggling rule sections, written
to ``playbooks/_generated/`` for provenance, then compiled. Emits the Pass-9
ActiveGraph events (PlaybookArchitectureStarted, ArchitectureDecisionRecorded).

No Kaggle upload, no GitHub push; root main.py/deck.csv are never touched.
"""

from __future__ import annotations

import argparse
import copy
from pathlib import Path

import yaml

import _bootstrap  # noqa: F401
from ptcg_activegraph.playbooks import load_playbook
from ptcg_activegraph.playbooks.compiler import (
    DEFAULT_BASELINE, DEFAULT_RUNS_ROOT, compile_playbook, compile_rules)

BASE_PLAYBOOK = "playbooks/v2_kyogre_abomasnow.yaml"
GENERATED_DIR = Path("playbooks/_generated")

# Ablation specs: each patches rule sections of the base playbook. ``None`` for
# deckout decline_threshold removes the deckout guard entirely.
ABLATIONS: list[dict] = [
    {
        "candidate_id": "playbook_v2_no_secret_box_play",
        "hypothesis": "If Secret Box is too risky, heavily deprioritizing it "
        "(dropping the evolution-decline guard, keeping the Mega-Signal orphan "
        "guard + discard + deckout) may improve consistency.",
        "patch": {
            "discard_safety": {"protect_setup": True},
            "search": {"avoid_orphan_evolution": False,
                       "avoid_orphan_mega_signal": True},
            "effect_resolution": {"decline_mega_signal_no_snover": False},
            "deckout_guard": {"decline_threshold": 8},
        },
    },
    {
        "candidate_id": "playbook_v2_kyogre_pressure",
        "hypothesis": "A Kyogre-first pilot may outperform evolution setup by "
        "simplifying decisions: protect setup on discard + deckout guard only, "
        "no search-line guards.",
        "patch": {
            "discard_safety": {"protect_setup": True},
            "search": {"avoid_orphan_evolution": False,
                       "avoid_orphan_mega_signal": False},
            "effect_resolution": {"decline_mega_signal_no_snover": False},
            "deckout_guard": {"decline_threshold": 8},
        },
    },
    {
        "candidate_id": "playbook_v2_abomasnow_setup",
        "hypothesis": "A Snover/Mega Abomasnow-focused pilot may improve ceiling "
        "if the line is protected: all search/decline guards on, but no deckout "
        "decline so it is willing to dig.",
        "patch": {
            "discard_safety": {"protect_setup": True},
            "search": {"avoid_orphan_evolution": True,
                       "avoid_orphan_mega_signal": True},
            "effect_resolution": {"decline_mega_signal_no_snover": True},
            "deckout_guard": {"decline_threshold": None},
        },
    },
    {
        "candidate_id": "playbook_v2_deckout_conservative",
        "hypothesis": "A stronger deckout guard (decline at <=12) may reduce "
        "long-game losses, at the cost of skipping some useful draw/search.",
        "patch": {
            "discard_safety": {"protect_setup": True},
            "search": {"avoid_orphan_evolution": True,
                       "avoid_orphan_mega_signal": False},
            "effect_resolution": {"decline_mega_signal_no_snover": False},
            "deckout_guard": {"decline_threshold": 12},
        },
    },
    {
        "candidate_id": "playbook_v2_effect_safety_max",
        "hypothesis": "Maximum safety around Ultra Ball / Secret Box / Mega "
        "Signal (all guards on, deckout decline at <=10) may reduce catastrophic "
        "line breaks even if it misses some upside.",
        "patch": {
            "discard_safety": {"protect_setup": True},
            "search": {"avoid_orphan_evolution": True,
                       "avoid_orphan_mega_signal": True},
            "effect_resolution": {"decline_mega_signal_no_snover": True},
            "deckout_guard": {"decline_threshold": 10},
        },
    },
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


def _write_derived(base_playbook: dict, candidate_id: str, patch: dict) -> Path:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    derived = _apply_patch(base_playbook, patch)
    derived["deck_id"] = candidate_id
    path = GENERATED_DIR / f"{candidate_id}.yaml"
    path.write_text(yaml.safe_dump(derived, sort_keys=False, allow_unicode=True),
                    encoding="utf-8")
    return path


def _emit_events(candidate_ids: list[str]) -> None:
    """Best-effort ActiveGraph event emission (never fails the build)."""
    try:
        from ptcg_activegraph.graph.events import EventType, new_event
        from ptcg_activegraph.graph.event_store import EventStore
        from ptcg_activegraph.experiments.config import LAB_EVENTS_PATH
        store = EventStore(LAB_EVENTS_PATH)
        store.append(new_event(
            EventType.PlaybookArchitectureStarted,
            payload={"pass": "pass9", "base_playbook": BASE_PLAYBOOK,
                     "candidates": candidate_ids},
            tags=["pass9", "playbook"]))
        store.append(new_event(
            EventType.ArchitectureDecisionRecorded,
            payload={"decision": "deck-specific declarative playbooks compiled "
                     "to stdlib-only candidates",
                     "rationale": "Pass 8: a generic policy cannot encode "
                     "line-coherence; effect-resolution targeting is "
                     "deck-specific and the fixture gate beats raw win rate."},
            tags=["pass9", "architecture"]))
    except Exception as exc:  # pragma: no cover - telemetry must not break build
        print(f"  (event emission skipped: {type(exc).__name__}: {exc})")


def _compile_one(playbook_path: str, candidate_id: str, runs_root: str,
                 baseline: str, hypothesis: str | None, ts: str | None) -> None:
    run_dir = compile_playbook(playbook_path, candidate_id, runs_root=runs_root,
                               baseline_dir=baseline, hypothesis=hypothesis,
                               ts=ts)
    rules = compile_rules(load_playbook(playbook_path))
    print(f"  {candidate_id:<36} rules={sorted(rules)} -> {run_dir}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--playbook", default=None, help="single playbook YAML")
    parser.add_argument("--candidate-id", default=None,
                        help="candidate id (single mode)")
    parser.add_argument("--group", default=None, choices=["pass9_playbooks"],
                        help="generate the base playbook + 5 ablations")
    parser.add_argument("--runs-root", default=DEFAULT_RUNS_ROOT)
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--base-playbook", default=BASE_PLAYBOOK)
    args = parser.parse_args()

    if args.group == "pass9_playbooks":
        import time
        ts0 = time.strftime("%Y%m%d_%H%M%S")
        candidate_ids = ["playbook_v2_kyogre_abomasnow_v1"] + [
            a["candidate_id"] for a in ABLATIONS]
        _emit_events(candidate_ids)
        print(f"group pass9_playbooks -> {args.runs_root}")
        # Base candidate (full safety).
        _compile_one(args.base_playbook, "playbook_v2_kyogre_abomasnow_v1",
                     args.runs_root, args.baseline,
                     "Declarative v2 playbook: reproduce the safety of "
                     "combo_full_safety_v3 with explicit strategic intent.",
                     f"{ts0}_00")
        base_pb = load_playbook(args.base_playbook)
        for i, ab in enumerate(ABLATIONS, start=1):
            derived = _write_derived(base_pb, ab["candidate_id"], ab["patch"])
            _compile_one(str(derived), ab["candidate_id"], args.runs_root,
                         args.baseline, ab["hypothesis"], f"{ts0}_{i:02d}")
        return 0

    if not args.playbook or not args.candidate_id:
        parser.error("single mode requires --playbook and --candidate-id "
                     "(or use --group pass9_playbooks)")
    _emit_events([args.candidate_id])
    _compile_one(args.playbook, args.candidate_id, args.runs_root,
                 args.baseline, None, None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
