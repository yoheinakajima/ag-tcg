#!/usr/bin/env python3
"""Emit the Pass 5 chaos telemetry readiness outputs.

For each ``chaos.*`` archetype seam this writes a machine-readable contract
(``data/experiments/chaos_telemetry_contract.json``) and a human-readable
requirements doc (``data/experiments/chaos_candidate_requirements.md``).

Honesty rules (Pass 5):
- Required telemetry, confirmed card ids and blockers are *derived* from
  ``experiments/strategy_seams.yaml`` + ``data/cards/pass4_id_confirmation.json``
  and the telemetry that ``experiments/runner.py`` actually records. Nothing is
  invented.
- Every chaos seam's decisive signal lives on the *opponent's* hidden side
  (their hand size, deck count, bench, status). Our seat's observation never
  exposes that, so availability is reported as ``blocked`` with only weak
  own-side proxies, and the minimum metric stays ``uncertain`` where it cannot
  be measured. No fabricated conclusions.
"""

from __future__ import annotations

import json
from pathlib import Path

import _bootstrap  # noqa: F401
from ptcg_activegraph.experiments.config import load_yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SEAMS_PATH = REPO_ROOT / "experiments" / "strategy_seams.yaml"
ID_CONFIRM_PATH = REPO_ROOT / "data" / "cards" / "pass4_id_confirmation.json"
OUT_DIR = REPO_ROOT / "data" / "experiments"
CONTRACT_PATH = OUT_DIR / "chaos_telemetry_contract.json"
REQUIREMENTS_PATH = OUT_DIR / "chaos_candidate_requirements.md"

# Telemetry signals the Pass 5 local harness (experiments/runner.py) actually
# records, all derived strictly from the candidate's OWN observation.
AVAILABLE_OWN_TELEMETRY = {
    "min_deck_count",
    "deck_count_last",
    "low_deck_decisions",
    "search_decisions",
    "discard_decisions",
    "max_bench_seen",
    "max_hand_seen",
    "context_counts",
    "candidate_won",
    "steps",
}

# Per chaos seam: the telemetry it would need to *prove* the disruption worked,
# tagged by which side the signal lives on. "opponent" signals are hidden from
# our seat; "own" signals map onto AVAILABLE_OWN_TELEMETRY.
CHAOS_TELEMETRY_SPEC = {
    "chaos.hand_avalanche_froslass": {
        "goal": "Keep the opponent's hand large, then scale Mega Froslass ex "
        "damage off that hand size.",
        "required_telemetry": [
            {"signal": "opponent_hand_size", "side": "opponent"},
            {"signal": "own_attack_damage_dealt", "side": "own"},
            {"signal": "candidate_won", "side": "own"},
        ],
        "own_proxies": ["candidate_won", "steps"],
        "min_metric": "uncertain — opponent hand size is hidden from our seat, "
        "so the damage-vs-hand-size relationship cannot be measured directly.",
    },
    "chaos.bench_bloat_punisher": {
        "goal": "Crowd the opponent's bench with Accompanying Flute, then punish "
        "with bench-count-scaling attackers.",
        "required_telemetry": [
            {"signal": "opponent_bench_size", "side": "opponent"},
            {"signal": "own_attack_damage_dealt", "side": "own"},
            {"signal": "candidate_won", "side": "own"},
        ],
        "own_proxies": ["candidate_won", "steps"],
        "min_metric": "uncertain — opponent bench size is hidden from our seat; "
        "only our own win/loss is observable.",
    },
    "chaos.mill_resource_destruction": {
        "goal": "Disrupt the opponent's deck / hand / energy so a brittle bot "
        "loses pieces or decks out.",
        "required_telemetry": [
            {"signal": "opponent_deck_count", "side": "opponent"},
            {"signal": "opponent_hand_size", "side": "opponent"},
            {"signal": "candidate_won", "side": "own"},
            {"signal": "steps", "side": "own"},
        ],
        "own_proxies": ["candidate_won", "steps", "min_deck_count"],
        "min_metric": "uncertain — opponent deck count is hidden; opponent "
        "deckout can only be inferred weakly from a long game that we win, "
        "not measured directly.",
    },
    "chaos.status_confusion_lock": {
        "goal": "Stack Confusion / Burn / Sleep + forced switching so the bot "
        "mis-sequences and loses turns.",
        "required_telemetry": [
            {"signal": "opponent_status_flags", "side": "opponent"},
            {"signal": "opponent_lost_turns", "side": "opponent"},
            {"signal": "candidate_won", "side": "own"},
        ],
        "own_proxies": ["candidate_won", "steps"],
        "min_metric": "uncertain — opponent status conditions and lost turns are "
        "hidden from our seat.",
    },
    "chaos.vivillon_decidueye_four_card_lock": {
        "goal": "Use Vivillon / Judge to pin the opponent at exactly 4 cards, "
        "enabling Decidueye ex's reduced-cost attack.",
        "required_telemetry": [
            {"signal": "opponent_hand_size", "side": "opponent"},
            {"signal": "own_attack_enabled", "side": "own"},
            {"signal": "candidate_won", "side": "own"},
        ],
        "own_proxies": ["candidate_won", "steps", "context_counts"],
        "min_metric": "uncertain — the exact-4 opponent hand condition is hidden "
        "from our seat, so the lock cannot be confirmed from telemetry.",
    },
}


def _id_status_index(confirm: dict) -> dict[int, dict]:
    """Map card id -> confirmation record (id/actual/status) across all groups."""
    idx: dict[int, dict] = {}
    for group in confirm.values():
        if not isinstance(group, list):
            continue
        for rec in group:
            try:
                idx[int(rec["id"])] = rec
            except (KeyError, TypeError, ValueError):
                continue
    return idx


def main() -> int:
    raw = load_yaml(SEAMS_PATH)
    seams = {s["id"]: s for s in raw.get("seams", []) if isinstance(s, dict)}
    confirm = json.loads(ID_CONFIRM_PATH.read_text(encoding="utf-8"))
    id_index = _id_status_index(confirm)

    contract = {
        "pass": 5,
        "note": "Local-only research artifact. Chaos seams stay blocked; this "
        "contract records exactly what telemetry each would need and why our "
        "seat cannot currently supply it. No card ids invented; no conclusions "
        "fabricated.",
        "available_own_telemetry": sorted(AVAILABLE_OWN_TELEMETRY),
        "seams": [],
    }

    for seam_id, spec in CHAOS_TELEMETRY_SPEC.items():
        seam = seams.get(seam_id, {})
        core_ids = list(seam.get("core_card_ids", []) or [])
        confirmed = []
        for cid in core_ids:
            rec = id_index.get(int(cid))
            confirmed.append(
                {
                    "id": int(cid),
                    "name": rec.get("actual") if rec else None,
                    "status": rec.get("status") if rec else "UNCONFIRMED",
                }
            )

        opponent_signals = [
            t["signal"] for t in spec["required_telemetry"] if t["side"] == "opponent"
        ]
        own_signals = [
            t["signal"] for t in spec["required_telemetry"] if t["side"] == "own"
        ]
        own_available = [s for s in own_signals if s in AVAILABLE_OWN_TELEMETRY]
        # A seam is telemetry-ready only if it needs no opponent-side signal and
        # all of its own-side signals are recorded by the harness.
        telemetry_ready = not opponent_signals and all(
            s in AVAILABLE_OWN_TELEMETRY for s in own_signals
        )
        availability = "available" if telemetry_ready else "blocked"

        blockers = []
        if opponent_signals:
            blockers.append(
                "opponent hidden-state telemetry not exposed to our seat: "
                + ", ".join(sorted(set(opponent_signals)))
            )
        missing_own = [s for s in own_signals if s not in AVAILABLE_OWN_TELEMETRY]
        if missing_own:
            blockers.append(
                "own-side signals not recorded by the harness: "
                + ", ".join(sorted(set(missing_own)))
            )
        if any(c["status"] != "MATCH" for c in confirmed):
            blockers.append(
                "some core card ids are not a clean MATCH against the official "
                "card table (see status field)"
            )
        if "chaos_decklist_confirmed" in (seam.get("requires") or []):
            blockers.append(
                "no full legal 60-card chaos decklist confirmed without inventing "
                "card ids (chaos_decklist_confirmed gate)"
            )

        contract["seams"].append(
            {
                "seam_id": seam_id,
                "enabled": bool(seam.get("enabled", False)),
                "default_priority": seam.get("default_priority"),
                "risk": seam.get("risk"),
                "policy_requirements": list(seam.get("requires") or []),
                "goal": spec["goal"],
                "required_telemetry": spec["required_telemetry"],
                "opponent_side_signals": opponent_signals,
                "own_side_signals": own_signals,
                "own_side_signals_available": own_available,
                "own_proxies_available": [
                    p for p in spec["own_proxies"] if p in AVAILABLE_OWN_TELEMETRY
                ],
                "telemetry_availability": availability,
                "confirmed_card_ids": confirmed,
                "blockers": blockers,
                "min_metric_to_unblock": spec["min_metric"],
            }
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CONTRACT_PATH.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")

    # --- human-readable requirements doc ---
    lines: list[str] = []
    lines.append("# Pass 5 — Chaos Telemetry Candidate Requirements")
    lines.append("")
    lines.append(
        "Local-only research artifact. For each chaos archetype seam this records "
        "the telemetry it would need to *prove* the disruption worked, whether our "
        "seat can supply it, the confirmed core card ids, the policy requirements, "
        "the blocker, and the minimum metric needed to unblock it."
    )
    lines.append("")
    lines.append(
        "**Key finding:** every chaos seam's decisive signal lives on the "
        "opponent's hidden side (their hand size, deck count, bench, or status). "
        "The Pass 5 harness records rich *own-side* telemetry (deck proximity, "
        "search/discard contexts, bench/hand high-water marks) but cannot observe "
        "the opponent's hidden state, so all five seams remain **blocked** and "
        "their unblock metric stays **uncertain**."
    )
    lines.append("")
    lines.append("Own-side telemetry now recorded by the harness:")
    lines.append("")
    for sig in sorted(AVAILABLE_OWN_TELEMETRY):
        lines.append(f"- `{sig}`")
    lines.append("")

    for entry in contract["seams"]:
        lines.append(f"## `{entry['seam_id']}`")
        lines.append("")
        lines.append(f"- **Goal:** {entry['goal']}")
        lines.append(
            f"- **Telemetry availability:** **{entry['telemetry_availability']}**"
        )
        lines.append(
            "- **Required telemetry:** "
            + ", ".join(
                f"`{t['signal']}` ({t['side']})" for t in entry["required_telemetry"]
            )
        )
        if entry["opponent_side_signals"]:
            lines.append(
                "- **Hidden (opponent-side) signals:** "
                + ", ".join(f"`{s}`" for s in entry["opponent_side_signals"])
            )
        if entry["own_proxies_available"]:
            lines.append(
                "- **Own-side proxies available:** "
                + ", ".join(f"`{s}`" for s in entry["own_proxies_available"])
            )
        lines.append(
            "- **Policy requirements:** "
            + (", ".join(entry["policy_requirements"]) or "none")
        )
        ids_str = ", ".join(
            f"{c['id']} {c['name'] or '?'} ({c['status']})"
            for c in entry["confirmed_card_ids"]
        )
        lines.append(f"- **Confirmed core card ids:** {ids_str or 'none'}")
        lines.append("- **Blockers:**")
        for b in entry["blockers"]:
            lines.append(f"  - {b}")
        lines.append(f"- **Minimum metric to unblock:** {entry['min_metric_to_unblock']}")
        lines.append("")

    REQUIREMENTS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote {CONTRACT_PATH.relative_to(REPO_ROOT)}")
    print(f"Wrote {REQUIREMENTS_PATH.relative_to(REPO_ROOT)}")
    print(f"Chaos seams documented: {len(contract['seams'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
