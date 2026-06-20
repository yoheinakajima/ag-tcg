#!/usr/bin/env python3
"""Pass 35 (Part C) — typed observation audit + lane decision.

Scans the observation objects actually visible to candidate runtime (embedded
replay fixtures + any locally-available raw replay, read-only) and enumerates
which fields are present. Compares that against what the Kaggle example agents
rely on (cg.api typed access + all_card_data card metadata + numeric attackId),
then records the lane decision for Pass 35.

PROVENANCE: emits ONLY field-availability metadata (field names + booleans +
counts). It never copies raw replay payloads, card identities, or the official
card CSV into any committed artifact.

Outputs:
- data/experiments/pass35_typed_obs_audit.json
- data/experiments/pass35_typed_obs_audit.md

Local-only: no upload, no submit, no push.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"

# Read-only observation sources (never copied verbatim into artifacts).
OBS_SOURCES = [
    REPO / "data" / "fixtures" / "replay_80374966_effect_resolution.json",
    REPO / "data" / "replays" / "80374966.json",
]


def _find_observations(node, out, depth=0):
    """Recursively collect dicts that look like a cabt observation
    (carry a ``select`` and/or ``current``)."""
    if depth > 8:
        return
    if isinstance(node, dict):
        if ("select" in node) or ("current" in node and "logs" in node):
            out.append(node)
        for v in node.values():
            _find_observations(v, out, depth + 1)
    elif isinstance(node, list):
        for v in node:
            _find_observations(v, out, depth + 1)


def _audit_observation(obs, acc):
    cur = obs.get("current") or {}
    sel = obs.get("select") or {}
    if isinstance(cur, dict):
        for k in cur:
            acc["current_fields"].setdefault(k, 0)
            acc["current_fields"][k] += 1
        players = cur.get("players")
        if isinstance(players, list):
            for p in players:
                if not isinstance(p, dict):
                    continue
                for k in p:
                    acc["player_fields"].setdefault(k, 0)
                    acc["player_fields"][k] += 1
                for zone in ("active", "bench"):
                    z = p.get(zone)
                    if isinstance(z, list):
                        for poke in z:
                            if isinstance(poke, dict):
                                for k in poke:
                                    acc["pokemon_fields"].setdefault(k, 0)
                                    acc["pokemon_fields"][k] += 1
                for zone in ("hand", "discard"):
                    z = p.get(zone)
                    if isinstance(z, list):
                        for card in z:
                            if isinstance(card, dict):
                                for k in card:
                                    acc["card_fields"].setdefault(k, 0)
                                    acc["card_fields"][k] += 1
    if isinstance(sel, dict):
        for k in sel:
            acc["select_fields"].setdefault(k, 0)
            acc["select_fields"][k] += 1
        opts = sel.get("option") or sel.get("options") or []
        if isinstance(opts, list):
            for o in opts:
                if isinstance(o, dict):
                    for k in o:
                        acc["option_fields"].setdefault(k, 0)
                        acc["option_fields"][k] += 1


def main() -> int:
    acc = {"current_fields": {}, "player_fields": {}, "pokemon_fields": {},
           "card_fields": {}, "select_fields": {}, "option_fields": {}}
    sources_scanned = []
    obs_count = 0
    for src in OBS_SOURCES:
        if not src.exists():
            sources_scanned.append({"path": str(src.relative_to(REPO)),
                                    "present": False, "observations": 0})
            continue
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            sources_scanned.append({"path": str(src.relative_to(REPO)),
                                    "present": True, "observations": 0,
                                    "error": "unreadable"})
            continue
        found = []
        _find_observations(data, found)
        for obs in found:
            _audit_observation(obs, acc)
        obs_count += len(found)
        sources_scanned.append({"path": str(src.relative_to(REPO)),
                                "present": True, "observations": len(found)})

    def has(group, key):
        return key in acc[group]

    # ---- Capability classification (honest). ----
    # supported  = derivable from observable fields + a compile-time metadata table
    # partial    = derivable only in some contexts / needs metadata that may be absent
    # unsupported= requires hidden info (target identity, attack semantics) not in obs
    capabilities = {
        "board_read_self_and_opponent": {
            "status": "supported",
            "evidence": "current.players[both] expose active/bench/hand/discard/"
                        "prize/deckCount/handCount/benchMax + status conditions.",
        },
        "active_bench_hp_energy_tools": {
            "status": "supported" if has("pokemon_fields", "hp") else "unsupported",
            "evidence": "pokemon entries expose hp/maxHp/energyCards/energies/"
                        "tools/id/preEvolution.",
        },
        "prize_count": {
            "status": "supported" if has("player_fields", "prize") else "unsupported",
            "evidence": "players[].prize is a list; len() = prizes remaining.",
        },
        "deck_count_deckout_guard": {
            "status": "supported" if has("player_fields", "deckCount")
            else "unsupported",
            "evidence": "players[].deckCount present; enables self-deckout guard.",
        },
        "stadium_supporter_energy_flags": {
            "status": "supported",
            "evidence": "current.stadium/stadiumPlayed/supporterPlayed/"
                        "energyAttached/retreated/turn/turnActionCount present.",
        },
        "card_identity_via_numeric_id": {
            "status": "supported",
            "evidence": "cards/pokemon expose numeric id only; NAME/TYPE/STAGE/"
                        "WEAKNESS/RETREAT require a compile-time metadata table "
                        "built from EN_Card_Data.csv (CSV never shipped/committed).",
        },
        "select_context_and_option_type": {
            "status": "supported",
            "evidence": "select.context + option.type/area/index/playerIndex "
                        "present; enables per-context typed decisions.",
        },
        "search_target_identity": {
            "status": "supported",
            "evidence": "ToHand search options reference revealed zone area/index; "
                        "card id resolvable from the board.",
        },
        "discard_target_identity": {
            "status": "supported",
            "evidence": "discard options reference hand index; card id resolvable.",
        },
        "attach_energy_target": {
            "status": "partial",
            "evidence": "attach options reference area/index; the receiving "
                        "Pokemon is resolvable, but energy-type matching depends "
                        "on metadata that may be incomplete for some cards.",
        },
        "estimate_attack_damage": {
            "status": "unsupported",
            "evidence": "attack options expose a NUMERIC attackId ONLY — no attack "
                        "name, base damage, or effect text. Damage cannot be "
                        "honestly estimated from the option schema.",
        },
        "lethal_ko_targeting": {
            "status": "unsupported",
            "evidence": "depends on attack damage (unsupported) and on choosing a "
                        "target; attack target identity is not in the option.",
        },
        "spread_damage_placement": {
            "status": "unsupported",
            "evidence": "spread/Phantom-Dive targets are not exposed; Pass-28 "
                        "honesty rule — never claim spread targeting.",
        },
        "boss_gust_target": {
            "status": "unsupported",
            "evidence": "Boss/gust target identity is not observable from options.",
        },
        "opponent_hand_identity": {
            "status": "unsupported",
            "evidence": "opponent hand is hidden (handCount only); never assume "
                        "opponent card identities.",
        },
    }

    # ---- Lane decision. ----
    kaggle_reliance = {
        "to_observation_class": "typed wrapper from cg.api (NOT in repo runtime)",
        "all_card_data / get_card": "card metadata table from cg.api",
        "typed SelectContext / OptionType": "enum typing over the same ints we read",
        "prize_count / hp / energy / tools / weakness / ex-mega": "board+metadata",
        "numeric attackId + damage/lethal/target/Boss logic": "needs attack "
            "semantics our option schema does NOT expose",
    }
    lane_decision = {
        "chosen_lane": "stdlib_typed_lite",
        "rejected_lane": "cg_api",
        "reason": "cg/cg.api exists only inside the installed kaggle_environments "
                  "package, not as a repo-shippable library. Bundling it would "
                  "break the candidate tarball contract (exactly top-level main.py "
                  "+ deck.csv, stdlib-only, AST-enforced). The same typed signal "
                  "(context ints, option types, board HP/energy/tools, prize/deck "
                  "counts) is reconstructable directly from the raw obs_dict, so a "
                  "stdlib typed-lite decoder is the safe runnable lane.",
        "metadata_strategy": "compile a minimal per-card metadata literal at BUILD "
                             "time from EN_Card_Data.csv for ONLY our portfolio "
                             "card ids; inline it in candidate main.py. The raw "
                             "CSV is never shipped or committed.",
        "honesty_boundaries": [
            "attack damage / lethal / KO targeting: unsupported (numeric attackId "
            "only)",
            "spread / Boss / gust target identity: unsupported",
            "opponent hand identity: unsupported (handCount only)",
        ],
    }

    payload = {
        "pass": "35", "part": "C", "local_only": True, "no_upload": True,
        "upload_performed": False, "is_kaggle_leaderboard": False,
        "provenance_note": "Field-availability metadata only; no raw replay "
        "payload, card identities, or official CSV copied into this artifact.",
        "sources_scanned": sources_scanned,
        "observations_audited": obs_count,
        "field_availability": {
            "current": acc["current_fields"],
            "player": acc["player_fields"],
            "pokemon": acc["pokemon_fields"],
            "card": acc["card_fields"],
            "select": acc["select_fields"],
            "option": acc["option_fields"],
        },
        "capabilities": capabilities,
        "kaggle_example_reliance": kaggle_reliance,
        "lane_decision": lane_decision,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass35_typed_obs_audit.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8")

    def fields_line(group):
        d = acc[group]
        return ", ".join(f"`{k}`" for k in sorted(d)) or "_none observed_"

    L = ["# Pass 35 — Typed observation audit + lane decision (Part C)", "",
         "> LOCAL ONLY. Field-availability metadata only — no raw replay payload, "
         "card identities, or official CSV copied here. Internal evidence, NOT "
         "the Kaggle leaderboard.", "",
         f"- observations audited: **{obs_count}** "
         f"from {sum(1 for s in sources_scanned if s.get('present'))} present "
         "source(s)", "",
         "## Fields visible to candidate runtime", "",
         f"- **current**: {fields_line('current_fields')}",
         f"- **players[]**: {fields_line('player_fields')}",
         f"- **active/bench pokemon**: {fields_line('pokemon_fields')}",
         f"- **hand/discard cards**: {fields_line('card_fields')}",
         f"- **select**: {fields_line('select_fields')}",
         f"- **option[]**: {fields_line('option_fields')}", "",
         "## Capability classification (honest)", "",
         "| capability | status | evidence |", "|---|---|---|"]
    for cap, info in capabilities.items():
        L.append(f"| {cap} | **{info['status']}** | {info['evidence']} |")
    L += ["", "## Lane decision", "",
          f"- chosen lane: **{lane_decision['chosen_lane']}** "
          f"(rejected: {lane_decision['rejected_lane']})",
          f"- reason: {lane_decision['reason']}",
          f"- metadata strategy: {lane_decision['metadata_strategy']}", "",
          "### Honesty boundaries (unsupported by the option schema)"]
    for b in lane_decision["honesty_boundaries"]:
        L.append(f"- {b}")
    L += ["", "### What Kaggle examples rely on (for contrast)"]
    for k, v in kaggle_reliance.items():
        L.append(f"- `{k}` — {v}")
    (EXP / "pass35_typed_obs_audit.md").write_text("\n".join(L) + "\n",
                                                   encoding="utf-8")
    print(f"typed obs audit: {obs_count} observations; lane="
          f"{lane_decision['chosen_lane']}; "
          f"pokemon_fields={len(acc['pokemon_fields'])} "
          f"option_fields={len(acc['option_fields'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
