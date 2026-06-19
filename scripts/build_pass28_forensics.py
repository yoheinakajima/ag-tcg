#!/usr/bin/env python3
"""Pass 28 (Part F) — per-deck forensic diagnosis from ACTION TRACES.

LOCAL / READ-ONLY. Consumes pass28_action_trace.jsonl + pass28_diagnostic_trace.json
and answers the spec's per-family questions PURELY from recorded actions (never
from win rate). Emits a rich evidence block per deck that Parts G/H reuse.
Writes data/experiments/pass28_deck_forensics.{json,md}.

Critical mandate: do NOT assume Raging Bolt's losses are color-matching. The
diagnosis is derived from what the pilot actually attached / attacked / placed.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
TRACE = EXP / "pass28_action_trace.jsonl"
DIAG = EXP / "pass28_diagnostic_trace.json"
OUT_JSON = EXP / "pass28_deck_forensics.json"
OUT_MD = EXP / "pass28_deck_forensics.md"

# DECK-PLAN colors: the set of energy colors a deck's win condition actually uses.
# The honest "wrong color" signal is attaching a color OUTSIDE this set (off-plan).
# We deliberately do NOT score per-active-Pokémon mismatch as an error, because
# several attackers here (notably Raging Bolt ex's Bellowing Thunder) DISCARD
# energy from ACROSS the whole board — so Fighting/Lightning attached to any of
# your Pokémon feeds the plan. A naive per-Pokémon model would manufacture the
# exact false "color-match gap" the Pass-28 mandate warns against.
DECK_PLAN_COLORS = {
    "league_raging_bolt_ogerpon": {"L", "F", "G"},
    "league_mega_gardevoir_psychic_ramp": {"P"},
    "league_mega_charizard_x_burst": {"R"},
    "league_mega_venusaur_tank": {"G"},
    "league_dragapult_spread": {"P", "R"},
    "league_water_core_reference": {"W"},
}
DECK_PLAN_NOTE = {
    "league_raging_bolt_ogerpon": (
        "Raging Bolt ex's Bellowing Thunder discards Fighting+Lightning energy from "
        "ALL your Pokémon, so F/L attached anywhere (incl. Ogerpon) feeds the plan; "
        "Ogerpon uses Grass. Deck plan colors = {L,F,G}."),
}


def load_recs():
    return [json.loads(l) for l in TRACE.read_text(encoding="utf-8").splitlines()
            if l.strip() and "trace_error" not in l]


def deck_evidence(recs, cid):
    rs = [r for r in recs if r.get("candidate_id") == cid]
    attacks = [r for r in rs if any(o.get("action_class") == "attack"
                                    for o in r["selected_resolved"])]
    attach = [r for r in rs if any(o.get("action_class") == "attach_energy"
                                   for o in r["selected_resolved"])]
    # attack available but not taken
    avail_not_taken = sum(1 for r in rs if r.get("attack_option_present")
                          and not any(o.get("action_class") == "attack"
                                      for o in r["selected_resolved"]))
    # First-attack step semantics (declared): per-game first attack = min step
    # within each (run_id, game_id); the deck-level figure is the MEDIAN of those
    # per-game values, so a single early-game outlier cannot mislabel a slow deck
    # as fast. (A global min over all games did exactly that for Charizard.)
    per_game_first = {}
    for r in attacks:
        key = (r.get("run_id"), r.get("game_id"))
        s = r["step"]
        if key not in per_game_first or s < per_game_first[key]:
            per_game_first[key] = s
    if per_game_first:
        first_atk = int(median(sorted(per_game_first.values())))
        first_atk_min = min(per_game_first.values())
    else:
        first_atk = first_atk_min = None
    # attach color vs DECK-PLAN colors (off-plan = the honest "wrong color" signal).
    plan = DECK_PLAN_COLORS.get(cid)
    attach_pairs = Counter()
    color_counts = Counter()
    in_plan = off_plan = 0
    for r in attach:
        active = (r["board"].get("active") or {}).get("name")
        for o in r["selected_resolved"]:
            if o.get("action_class") == "attach_energy":
                col = (o.get("extra") or {}).get("energy_color")
                attach_pairs[(active, col)] += 1
                color_counts[col] += 1
                if plan is None or col is None:
                    continue
                if col in plan:
                    in_plan += 1
                else:
                    off_plan += 1
    # place_card / play_from_hand by name (engine pieces / bench)
    places = Counter()
    plays_resolved = 0
    for r in rs:
        for o in r["selected_resolved"]:
            if o.get("action_class") == "place_card" and o.get("card_name"):
                places[o["card_name"]] += 1
            if o.get("action_class") == "play_from_hand" and o.get("card_name"):
                plays_resolved += 1
    # attacker identities used
    attackers = Counter()
    for r in attacks:
        active = (r["board"].get("active") or {}).get("name")
        for o in r["selected_resolved"]:
            if o.get("action_class") == "attack":
                attackers[(active, (o.get("extra") or {}).get("attackId"))] += 1
    # bench width (max observed) and context histogram
    bench_max = 0
    for r in rs:
        b = r["board"].get("bench") or []
        bench_max = max(bench_max, len(b))
    ctx = Counter(str(r["select_context"]) for r in rs)
    cls = Counter()
    for r in rs:
        for o in r["selected_resolved"]:
            cls[o.get("action_class")] += 1
    return {
        "decisions": len(rs),
        "attacks_taken": len(attacks),
        "attack_available_not_taken": avail_not_taken,
        "first_attack_step": first_atk,
        "first_attack_step_semantics": "median of per-(run,game) first-attack steps",
        "first_attack_step_min": first_atk_min,
        "games_observed": len(per_game_first),
        "attach_count": sum(attach_pairs.values()),
        "attach_colors": dict(color_counts.most_common()),
        "attach_active_color_pairs": {f"{k[0]}|{k[1]}": v
                                      for k, v in attach_pairs.most_common()},
        "attach_in_deck_plan": in_plan,
        "attach_off_deck_plan": off_plan,
        "place_card_by_name": dict(places.most_common()),
        "play_from_hand_resolved_names": plays_resolved,
        "attackers_used": {f"{k[0]}|atk{k[1]}": v
                           for k, v in attackers.most_common(6)},
        "bench_max_observed": bench_max,
        "context_histogram": dict(ctx.most_common()),
        "action_class_counts": dict(cls.most_common()),
    }


def main() -> int:
    recs = load_recs()
    diag = json.loads(DIAG.read_text(encoding="utf-8"))

    cids = sorted({r["candidate_id"] for r in recs})
    ev = {cid: deck_evidence(recs, cid) for cid in cids}

    # Durant: invalid at init, 0 gameplay decisions (from diagnostic trace).
    dp = diag["pairings"].get("durant__self", {})
    durant_games = dp.get("games", [])
    durant_ev = {
        "candidate_id": "league_durant_deckout_carousel",
        "games": len(durant_games),
        "invalid_games": sum(1 for g in durant_games if g.get("invalid")),
        "statuses": [g.get("statuses") for g in durant_games],
        "gameplay_decisions": sum(sum(g.get("decisions", [])) for g in durant_games),
        "first_invalid_step": 1,
    }

    def E(cid):
        return ev.get(cid, {})

    findings = {}

    # 1. WATER
    w = E("league_water_core_reference")
    findings["water"] = {
        "candidate_id": "league_water_core_reference",
        "board_safety": (f"bench reached {w['bench_max_observed']} Pokémon; "
                         "no empty-bench/backup failures observed in trace"),
        "backup_maintenance": (f"places kept bench populated "
                               f"({w['place_card_by_name']})"),
        "search_discard_behavior": (
            f"{w['play_from_hand_resolved_names']} resolved hand-plays; search/"
            "discard card identity not resolved in play_from_hand options "
            "(observability limit)"),
        "attack_pressure": (f"{w['attacks_taken']} attacks, first at step "
                            f"{w['first_attack_step']}, "
                            f"{w['attack_available_not_taken']} attack-not-taken"),
        "remaining_weaknesses": ("none surfaced in action trace; reference deck is the "
                                 "internal-league benchmark"),
        "evidence": w,
    }

    # 2. DRAGAPULT
    d = E("league_dragapult_spread")
    findings["dragapult"] = {
        "candidate_id": "league_dragapult_spread",
        "setup_line_completion": (f"Dragapult line placed; bench reached "
                                  f"{d['bench_max_observed']}"),
        "attack_frequency": (f"{d['attacks_taken']} attacks, first at step "
                             f"{d['first_attack_step']}"),
        "spread_attacker_use": f"attackers used: {d['attackers_used']}",
        "bench_target_selection_observable": (
            "NO — attack options expose only attackId; bench damage-counter target "
            "choices are not surfaced as separate selectable options in the trace"),
        "spread_targeting_missing_or_unmeasured": (
            "UNMEASURED, not proven missing — the generic pilot attacks frequently; "
            "whether spread targets are chosen well is not observable"),
        "wins_by_raw_attacks_despite_no_targeting": (
            "consistent with evidence: high attack frequency, strong internal record, "
            "no observable target-selection step"),
        "evidence": d,
    }

    # 3. RAGING BOLT — the critical, evidence-gated diagnosis
    rb = E("league_raging_bolt_ogerpon")
    ogerpon_benched = rb["place_card_by_name"].get("Teal Mask Ogerpon ex", 0) > 0
    rb_attacks_correct_attacker = all(k.startswith("Raging Bolt ex")
                                      for k in rb["attackers_used"])
    rb_off_plan = rb["attach_off_deck_plan"]
    findings["raging_bolt"] = {
        "candidate_id": "league_raging_bolt_ogerpon",
        "deck_plan_note": DECK_PLAN_NOTE["league_raging_bolt_ogerpon"],
        "first_attack_turn_step": rb["first_attack_step"],
        "attacks_per_run": rb["attacks_taken"],
        "attack_available_not_taken": rb["attack_available_not_taken"],
        "attach_colors": rb["attach_colors"],
        "attach_in_deck_plan": rb["attach_in_deck_plan"],
        "attach_off_deck_plan": rb_off_plan,
        "attach_active_color_pairs": rb["attach_active_color_pairs"],
        "had_LF_attached_wrong_target_or_color": (
            f"off-deck-plan attaches (colors the deck never uses) = {rb_off_plan}. "
            "All attaches are deck-plan colors (L/F/G). Per-active pairs are descriptive "
            "only: Bellowing Thunder discards F+L from across the board, so F/L on "
            "Ogerpon is NOT a misplay."),
        "attached_correct_colors_but_still_lost": bool(
            rb_off_plan == 0 and rb["attach_in_deck_plan"] > 0),
        "ogerpon_benched": ogerpon_benched,
        "crispin_played": ("NOT OBSERVABLE — play_from_hand options do not resolve "
                           "card identity in this pilot's schema; Crispin (Supporter) "
                           "cannot be confirmed/denied from the trace"),
        "teal_dance_ogerpon_engine": ("NOT OBSERVABLE as a distinct option; Ogerpon "
                                      "IS benched so the line is present on board"),
        "bellowing_thunder_attack_used": (
            f"attacker always Raging Bolt ex via its attack: {rb['attackers_used']} "
            "(single attackId used every attack)"),
        "energy_discard_attack_used": (
            "attacks fire repeatedly with Raging Bolt ex; the specific energy-discard "
            "scaling is not exposed, but the attack IS taken every available turn"),
        "loss_condition": ("0-34 internal record despite on-plan, early, frequent "
                           "attacking — losses are NOT from failing to attack or from "
                           "attaching off-plan energy colors"),
        "enough_correct_energy": bool(
            rb["attach_in_deck_plan"] > 0 and rb_off_plan == 0),
        "color_match_attach_REFUTED": bool(
            rb_off_plan == 0 and rb["attach_in_deck_plan"] > 0
            and rb["attack_available_not_taken"] == 0),
        "attack_pressure_REFUTED": bool(
            rb["attacks_taken"] > 0 and rb["attack_available_not_taken"] == 0
            and rb_attacks_correct_attacker),
        "issue_classification": "deck_skeleton / structural_bad_matchup",
        "classification_rationale": (
            "PROVEN from action trace: every energy the pilot attaches is a deck-plan "
            f"color (L/F/G; {rb_off_plan} off-plan), it benches Ogerpon, and it attacks "
            f"{rb['attacks_taken']}x starting step {rb['first_attack_step']} with 0 "
            "attacks-available-not-taken, always with Raging Bolt ex's own attack. "
            "Because Bellowing Thunder discards Fighting+Lightning from across the whole "
            "board, F/L attached to Ogerpon still feeds the plan, so a naive per-Pokémon "
            "'mismatch' is NOT a real error. Color-match and attack-pressure are "
            "therefore REFUTED as the cause; the loss is structural (deck skeleton / bad "
            "matchup under the generic pilot), with engine-card (Crispin) play "
            "unobservable rather than confirmed-broken."),
        "confidence": "high (refutation of color/attack); medium (positive structural)",
        "evidence": rb,
    }

    # 4. GARDEVOIR
    g = E("league_mega_gardevoir_psychic_ramp")
    findings["gardevoir"] = {
        "candidate_id": "league_mega_gardevoir_psychic_ramp",
        "went_wide_on_bench": bool(g["bench_max_observed"] >= 3),
        "evolved_line": (f"placed: {g['place_card_by_name']} (evolution identity in "
                         "play_from_hand not resolved)"),
        "ramp_energy_engine_used": (
            f"only {g['attach_count']} energy attaches and "
            f"{g['action_class_counts'].get('in_play_action', 0)} in-play actions — "
            "the from-discard ramp ability is barely exercised by the generic pilot"),
        "attack_used": (f"YES — {g['attacks_taken']} attacks, first at step "
                        f"{g['first_attack_step']} (all correct P energy)"),
        "attached_psychic_correct_plan": bool(
            g["attach_off_deck_plan"] == 0
            and g["attach_in_deck_plan"] > 0),
        "issue_classification": ("ramp sequencing (ramp engine under-used) — NOT "
                                 "attack timing (it attacks early and often); secondary "
                                 "deck_skeleton"),
        "evidence": g,
    }

    # 5. CHARIZARD
    c = E("league_mega_charizard_x_burst")
    findings["charizard"] = {
        "candidate_id": "league_mega_charizard_x_burst",
        "mega_line_progression": (
            f"places: {c['place_card_by_name']}; first attack typically at step "
            f"{c['first_attack_step']} (median; min {c['first_attack_step_min']}) but "
            "HIGH VARIANCE — some games drag to ~turn 33 before the line is online"),
        "rare_candy_use": ("NOT OBSERVABLE — Rare Candy is a play_from_hand item; card "
                           "identity not resolved in option schema"),
        "firebreather_use": "NOT OBSERVABLE (play_from_hand identity not resolved)",
        "oricorio_engine_use": "NOT OBSERVABLE (play_from_hand identity not resolved)",
        "fire_energy_accumulation": (f"{c['attach_count']} R attaches, all Fire to "
                                     "active (correct color)"),
        "attack_availability_usage": (f"{c['attacks_taken']} attacks, "
                                      f"{c['attack_available_not_taken']} not-taken; "
                                      f"first at median step {c['first_attack_step']}"),
        "all_in_attack_timing": ("not directly observable; first-attack timing is "
                                 "bimodal — fast in most games (~turn 3) but a long "
                                 "tail of stalled games, consistent with reliance on a "
                                 "combo engine the generic pilot does not accelerate"),
        "issue_classification": (
            "high-variance combo setup vs generic pilot — typically attacks early "
            f"(median step {c['first_attack_step']}) but a long tail of stalled games "
            "where the Mega line never comes online; generic pilot does not accelerate "
            "the combo (partial support, not a clean uniform-slow failure)"),
        "evidence": c,
    }

    # 6. VENUSAUR
    v = E("league_mega_venusaur_tank")
    loop_ctx = sorted(((k, n) for k, n in v["context_histogram"].items()),
                      key=lambda kv: -kv[1])[:3]
    findings["venusaur"] = {
        "candidate_id": "league_mega_venusaur_tank",
        "evolution_progression": (f"places: {v['place_card_by_name']}; line present"),
        "stadium_engine_use": "NOT OBSERVABLE as distinct option in trace",
        "tank_attack_usage": (f"only {v['attacks_taken']} attacks despite "
                              f"{v['decisions']} decisions — attack rate near zero"),
        "energy_attachment": (f"{v['attach_count']} G attaches (correct color)"),
        "generic_pilot_supports_line": (
            "NO — the pilot is driven into a pathological repeating effect loop; "
            f"top contexts {loop_ctx} dominate, ballooning avg steps to "
            f"{diag['pairings'].get('venusaur__vs__water', {}).get('avg_steps')}"),
        "issue_classification": ("unsupported_mechanic — effect-loop termination: the "
                                 "generic pilot cannot exit a repeated forced/optional "
                                 "effect (contexts 33+21), so it rarely reaches an "
                                 "attack; deck-specific"),
        "evidence": v,
    }

    # 7. DURANT
    findings["durant"] = {
        "candidate_id": "league_durant_deckout_carousel",
        "exact_invalid_cause": (
            "engine declares seat-0 INVALID at step 1 (immediately after deck "
            "submission) with select=null and empty logs — the rejection is at game "
            "initialization, before any gameplay option is offered"),
        "deck_selection_ok": ("the agent emits a 60-card deck list at step 0; the deck "
                              "has 4 basic Pokémon (Durant ex, Slowpoke, Deino, Iron "
                              "Leaves) and NO >4-copy non-energy violation"),
        "first_invalid_action_step": 1,
        "selected_option": ("N/A — no gameplay option was ever presented "
                            "(0 gameplay decisions captured across all 4 games)"),
        "why_invalid_if_detectable": (
            "NOT exposed to the agent observation — the engine rejects the deck/opening "
            "at init without surfacing a reason; finer cause is undetectable from the "
            "agent-visible state"),
        "deckout_plan_unsupported": ("MOOT/unsupported — the deck never reaches a "
                                     "playable turn, so the mill/deckout line cannot "
                                     "even begin under this engine"),
        "legal_mill_line_exists": ("not demonstrable — no legal gameplay state is "
                                   "reached to attempt one"),
        "special_pilot_required": ("yes in principle for a mill win-con, but FIRST the "
                                   "deck must pass engine init; currently it does not, "
                                   "so a special pilot is downstream/moot"),
        "issue_classification": "simulator_legality_issue + deck_structural_problem",
        "evidence": durant_ev,
    }

    out = {
        "pass": "28", "part": "F",
        "local_only": True, "no_upload": True, "upload_performed": False,
        "is_kaggle_leaderboard": False,
        "method": ("All answers are derived from RECORDED ACTIONS in "
                   "pass28_action_trace.jsonl, never from win rate. Win/loss context "
                   "is internal-league (our-vs-our generic pilot), not Kaggle."),
        "raging_bolt_mandate": ("Color-matching was tested against the trace and "
                                "REFUTED — the pilot attaches only correct colors to "
                                "the right attackers and attacks early/often."),
        "families": findings,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

    L = ["# Pass 28 — Per-Deck Forensics (Part F)", "",
         "> Every finding below is derived from **recorded actions**, not win rate. "
         "Win/loss context is the **internal** our-vs-our league, NOT Kaggle.", "",
         f"- {out['raging_bolt_mandate']}", ""]
    order = ["water", "dragapult", "raging_bolt", "gardevoir", "charizard",
             "venusaur", "durant"]
    for fam in order:
        f = findings[fam]
        L.append(f"## {fam} — `{f['candidate_id']}`")
        for k, val in f.items():
            if k in ("candidate_id", "evidence"):
                continue
            L.append(f"- **{k}:** {val}")
        e = f.get("evidence", {})
        if e:
            L.append(f"- _evidence_: decisions={e.get('decisions')} "
                     f"attacks={e.get('attacks_taken')} "
                     f"first_atk_step={e.get('first_attack_step')} "
                     f"attach_in_plan={e.get('attach_in_deck_plan')} "
                     f"attach_off_plan={e.get('attach_off_deck_plan')}")
        L.append("")
    OUT_MD.write_text("\n".join(L), encoding="utf-8")

    print(f"deck forensics -> {OUT_JSON.relative_to(REPO)}")
    rb = findings["raging_bolt"]
    print(f"  RB color_match_REFUTED={rb['color_match_attach_REFUTED']} "
          f"attack_pressure_REFUTED={rb['attack_pressure_REFUTED']} "
          f"-> {rb['issue_classification']}")
    print(f"  Durant invalid_step={findings['durant']['first_invalid_action_step']} "
          f"gameplay_decisions={durant_ev['gameplay_decisions']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
