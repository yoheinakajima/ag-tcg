#!/usr/bin/env python3
"""Emit the Pass 5 chaos telemetry readiness outputs.

For each ``chaos.*`` archetype seam this writes a machine-readable contract
(``data/experiments/chaos_telemetry_contract.json``) and a human-readable
requirements doc (``data/experiments/chaos_candidate_requirements.md``).

Honesty rules (Pass 5, telemetry conclusion corrected in Pass 8):
- Required telemetry, confirmed card ids and blockers are *derived* from
  ``experiments/strategy_seams.yaml`` + ``data/cards/pass4_id_confirmation.json``
  and the telemetry that ``experiments/runner.py`` actually records. Nothing is
  invented.
- Pass 8 correction: earlier passes wrongly treated *every* opponent-side signal
  as hidden. In fact our seat's observation DOES expose the opponent's PUBLIC
  board state — their hand *count*, deck count, bench count, visible active/bench
  card ids, status flags, discard-pile contents, and the public game logs. What
  stays genuinely hidden/uncertain is the opponent's hand *contents* (which
  specific cards they hold), the *causal attribution* of a chaos card to an
  outcome, and whether a chaos play actually *helped* the opponent set up.
- Because the decisive proof for every chaos seam is causal ("did OUR disruption
  cause this?"), and that attribution is unavailable, chaos seams are at best
  ``partially_observable`` and remain a **research stream, not an upload stream**.
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

# Pass 8 telemetry correction. Opponent-side signals our seat's observation DOES
# expose (their PUBLIC board state). Mapping note in parentheses ties each to the
# raw field name in the spec's "Available" list.
OPPONENT_OBSERVABLE_TELEMETRY = {
    "opponent_hand_size",         # handCount
    "opponent_deck_count",        # deckCount
    "opponent_bench_size",        # bench count
    "opponent_active_id",         # visible active id
    "opponent_bench_ids",         # visible bench ids
    "opponent_status_flags",      # status flags
    "opponent_discard_contents",  # discard pile contents
    "game_logs",                  # public game logs
}

# Opponent-side / causal signals that stay genuinely hidden or unmeasurable from
# our seat — the reason chaos stays a research stream.
OPPONENT_HIDDEN_TELEMETRY = {
    "opponent_hand_contents",     # which specific cards they hold
    "opponent_lost_turns",        # causal: turns actually lost to status
    "own_attack_damage_dealt",    # causal: damage attributable to our play
}

# Spec-level corrected conclusion (Pass 8), surfaced verbatim at the top of both
# the JSON contract and the markdown doc so the headline is unambiguous.
TELEMETRY_CORRECTION = {
    "available": [
        "opponent handCount",
        "opponent deckCount",
        "opponent bench count",
        "visible active/bench IDs",
        "status flags",
        "discard contents",
        "game logs",
    ],
    "still_missing_or_uncertain": [
        "opponent hand contents",
        "causal attribution of chaos cards",
        "whether chaos helps opponent setup",
    ],
    "conclusion": "Chaos remains a research stream, not the next upload stream.",
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
        "min_metric": "partial — opponent hand SIZE is observable from our seat, "
        "but our own per-attack damage dealt is not recorded, so the "
        "damage-vs-hand-size relationship cannot be measured directly.",
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
        "min_metric": "partial — opponent bench SIZE is observable from our seat, "
        "but our own per-attack damage dealt is not recorded, so the "
        "damage-vs-bench-count relationship cannot be measured directly.",
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
        "min_metric": "partial — opponent deck count and hand SIZE are observable "
        "from our seat, so opponent deckout pressure CAN be tracked directly via "
        "the public count; only the causal share from our mill actions is unproven.",
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
        "min_metric": "partial — opponent status flags are observable from our seat "
        "(public board), but opponent lost turns are not surfaced as a metric, so "
        "the lock's turn-denial effect can only be inferred indirectly.",
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
        "min_metric": "partial — the exact-4 opponent hand SIZE condition IS "
        "observable from our seat (public count), so the lock state can be "
        "confirmed; only whether our own attack was enabled by it is unrecorded.",
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
        "telemetry_conclusion_corrected_in_pass": 8,
        "note": "Local-only research artifact. Pass 8 correction: the opponent's "
        "PUBLIC board state IS observable from our seat (counts, visible ids, "
        "status, discard, logs); only hand contents and causal attribution stay "
        "hidden. Chaos seams are therefore partially_observable at best and stay "
        "a research stream. No card ids invented; no conclusions fabricated.",
        "telemetry_correction": TELEMETRY_CORRECTION,
        "available_own_telemetry": sorted(AVAILABLE_OWN_TELEMETRY),
        "opponent_observable_telemetry": sorted(OPPONENT_OBSERVABLE_TELEMETRY),
        "opponent_hidden_telemetry": sorted(OPPONENT_HIDDEN_TELEMETRY),
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
        # Pass 8 split: opponent signals are no longer uniformly hidden — public
        # board state is observable; only hand contents / causal signals are not.
        opp_observable = [s for s in opponent_signals
                          if s in OPPONENT_OBSERVABLE_TELEMETRY]
        opp_hidden = [s for s in opponent_signals
                      if s not in OPPONENT_OBSERVABLE_TELEMETRY]
        missing_own = [s for s in own_signals if s not in AVAILABLE_OWN_TELEMETRY]
        # Availability tiers:
        #   available            — no opponent signal at all + all own recorded
        #   partially_observable — every opponent signal is public board state and
        #                          own signals recorded, but causal attribution
        #                          (the decisive proof) is still unavailable
        #   blocked              — needs a genuinely hidden signal (hand contents /
        #                          causal) or an own signal the harness omits
        if not opponent_signals and not missing_own:
            availability = "available"
        elif not opp_hidden and not missing_own:
            availability = "partially_observable"
        else:
            availability = "blocked"

        blockers = []
        if opp_observable:
            blockers.append(
                "opponent PUBLIC board state IS observable (Pass 8 correction), "
                "but only as counts/visible ids, not proof of causation: "
                + ", ".join(sorted(set(opp_observable)))
            )
        if opp_hidden:
            blockers.append(
                "opponent hidden/causal telemetry still not available to our seat: "
                + ", ".join(sorted(set(opp_hidden)))
            )
        if availability == "partially_observable":
            blockers.append(
                "causal attribution unavailable: cannot prove our chaos play (not "
                "the opponent's own line) caused the observed board change, nor "
                "rule out that it helped them set up"
            )
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
                "opponent_side_observable": opp_observable,
                "opponent_side_hidden": opp_hidden,
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
        "**Key finding (Pass 8 correction):** earlier passes wrongly concluded "
        "that *all* opponent-side telemetry was hidden. In fact our seat observes "
        "the opponent's PUBLIC board state. The decisive proof for every chaos "
        "seam is nonetheless *causal* — \"did OUR disruption cause this?\" — and "
        "that attribution (plus the opponent's hand *contents*) remains "
        "unavailable. So the seams are **partially_observable** at best and chaos "
        "stays a **research stream, not the next upload stream**."
    )
    lines.append("")
    lines.append("### Available (corrected)")
    lines.append("")
    for item in TELEMETRY_CORRECTION["available"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("### Still missing / uncertain")
    lines.append("")
    for item in TELEMETRY_CORRECTION["still_missing_or_uncertain"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append(f"**Conclusion:** {TELEMETRY_CORRECTION['conclusion']}")
    lines.append("")
    lines.append("Own-side telemetry recorded by the harness:")
    lines.append("")
    for sig in sorted(AVAILABLE_OWN_TELEMETRY):
        lines.append(f"- `{sig}`")
    lines.append("")
    lines.append("Opponent-side telemetry that IS observable (public board state):")
    lines.append("")
    for sig in sorted(OPPONENT_OBSERVABLE_TELEMETRY):
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
        if entry["opponent_side_observable"]:
            lines.append(
                "- **Opponent-side signals observable (public board state):** "
                + ", ".join(f"`{s}`" for s in entry["opponent_side_observable"])
            )
        if entry["opponent_side_hidden"]:
            lines.append(
                "- **Opponent-side signals still hidden/causal:** "
                + ", ".join(f"`{s}`" for s in entry["opponent_side_hidden"])
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
