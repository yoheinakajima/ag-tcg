#!/usr/bin/env python3
"""PASS 46J (Part C) — Diamond specialist TURN-PLANNER blueprint.

Emits the design contract for the v0 deck-specific turn planner for the internal parent
``diamond_toolbox_diancie`` — a REAL planner (DiamondBoardView / DiamondRoleMap /
DiamondTurnPlan + 11 per-context policies), NOT a flat option/family scorer.

This builder is SELF-VALIDATING and READ-ONLY:
  * the embedded DiamondRoleMap is DERIVED from the Part-B audit JSON (every role card id
    must be one of the 15 verified deck ids — no invented ids), and the inferred main
    attacker must match the audit (766 Mega Diancie ex);
  * every one of the 11 per-context policies must map to a REAL cabt option-type code
    (``OPTION_TYPE_CLASS``, parity-tested in the 46H candidate / ``action_resolver``) and,
    where applicable, a REAL typed ``decisions.decide`` kind — so no context is invented;
  * the unsupported-claims list must cover every honesty boundary the typed layer marks
    unsupported (attack damage / lethal / ko / spread / boss / gust) plus best-action /
    card-value / hidden-zone.

Writes data/experiments/pass46j_diamond_planner_blueprint.{json,md}. Mutates nothing; no
ObjectStorage / EventStore / Kaggle / cg runtime / online Search is touched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
AUDIT_JSON = EXP / "pass46j_diamond_source_audit.json"

# Real cabt option-type -> coarse action family (parity-tested vs action_resolver /
# the 46H candidate OPTION_TYPE_CLASS). Used ONLY to prove each policy targets a real code.
OPTION_TYPE_CLASS = {
    0: "effect_choice", 1: "effect_choice", 2: "effect_choice", 3: "select_card",
    6: "move_energy", 7: "play_from_hand", 8: "attach_energy", 9: "use_ability",
    10: "play_in_play", 12: "end_turn", 13: "attack", 14: "end_turn",
}
# Real typed decision kinds (ptcg_activegraph.pilot_typed.decisions.decide).
SUPPORTED_DECIDE_KINDS = {
    "setup_active", "setup_bench_multi", "search_to_hand", "discard", "draw_count",
    "emergency_backup_bench", "attach_energy",
}
UNSUPPORTED_DECIDE_KINDS = {"attack", "ko_target", "lethal", "spread", "boss", "gust"}


def _load_audit() -> dict:
    if not AUDIT_JSON.exists():
        raise SystemExit(f"missing audit: {AUDIT_JSON} (run Part B first)")
    return json.loads(AUDIT_JSON.read_text(encoding="utf-8"))


def _role_map(audit: dict) -> tuple[dict, dict]:
    """Build the per-card DiamondRoleMap purely from the verified Part-B audit."""
    rv = audit["roles_verified_from_metadata"]
    ri = audit["roles_inferred"]
    cards = {c["card_id"]: c for c in audit["cards"]}
    main = set(ri["main_attacker_candidates"])
    backup = set(ri["backup_attacker_candidates"])
    role_by_id: dict[int, list[str]] = {}
    for cid, c in cards.items():
        tokens: list[str] = []
        if cid in rv["energy_cards"]:
            tokens.append("energy")
        if cid in rv["basic_pokemon"]:
            tokens.append("basic")
        if c["ex"]:
            tokens.append("ex")
        if cid in main:
            tokens.append("main_attacker")
        if cid in backup:
            tokens.append("backup_attacker")
        if cid in rv["damage_attacker_pokemon"] and cid not in main and cid not in backup:
            tokens.append("attacker")
        if cid in rv["energy_accel_cards"]:
            tokens.append("energy_accel")
        if cid in rv["healer_cards"]:
            tokens.append("healer")
        if cid in rv["bench_fill_cards"]:
            tokens.append("bench_fill")
        if cid in rv["search_cards"]:
            tokens.append("search")
        if cid in rv["draw_cards"]:
            tokens.append("draw")
        if cid in rv["opponent_switch_disruption_cards"]:
            tokens.append("disruption")
        # functional-tag derived specials
        for tag, tok in (("anti_ex_tech", "anti_ex"), ("copy_attack_tech", "copy_tech"),
                         ("turn1_attack_ability", "turn1_enabler"),
                         ("damage_reduction_ability", "damage_reduction"),
                         ("scaling_discard_attacker", "scaling_discard")):
            if tag in c["functions_inferred"]:
                tokens.append(tok)
        role_by_id[cid] = tokens
    # ordered attacker priority: main, then ex backups by HP, then remaining attackers
    def hp(cid):
        return cards[cid]["hp"] or 0
    attackers = [cid for cid in cards if cid in main or cid in backup]
    attacker_priority = sorted(
        attackers, key=lambda c: (1 if c in main else 0,
                                  1 if "ex" in role_by_id[c] else 0, hp(c)), reverse=True)
    priorities = {
        "attacker_priority": attacker_priority,
        "energy_target_rule": [
            "in-play attacker that is the DESIRED active (main attacker preferred)",
            "any in-play attacker we are fueling toward an attack",
            "the planned desired-active Pokémon being set up",
            "a benched backup attacker (only if no active attacker present)",
        ],
        "search_target_rule": [
            "main attacker (766) if not yet in play and the plan wants a clock",
            "energy (5) if attached/in-hand energy is short for the planned attack",
            "bench-fill basics if bench is thin (engine: 767/751/1086)",
            "draw/consistency (1224) or pokemon-to-hand (1121/1231) otherwise",
        ],
        "safe_discard_rule": [
            "surplus basic energy when clearly flush (keep enough for the planned attack)",
            "duplicate trainers beyond what the turn can use",
            "non-essential tech (434 copy / 331 anti-ex) when not relevant to the matchup",
            "NEVER the last copy of the main attacker or the last energy needed to attack",
        ],
    }
    return role_by_id, priorities


def _contexts() -> list[dict]:
    """The 11 per-context policies. Each cites the REAL option code(s) and decide kind."""
    return [
        {
            "name": "choose_active",
            "families": ["setup_active", "emergency_backup_bench"],
            "option_type_codes": [3, 7],
            "decide_kind": "setup_active|emergency_backup_bench",
            "policy": "Covers BOTH the initial setup Active AND a forced promote after a KO "
                      "(emergency_backup_bench / bench-to-active select). Pick the Pokémon to "
                      "make Active toward desired_active_role: for SETUP prefer a durable "
                      "opener (turn1_enabler 525 Meloetta ex or a high-HP basic) and keep the "
                      "main attacker (766) benched to grow unless it is the only legal active; "
                      "for a forced PROMOTE prefer an already-fueled in-play attacker (by "
                      "VISIBLE attached-energy count) else a durable body. Ranks legal "
                      "indices only.",
            "plan_fields": ["phase", "desired_active_role", "attacker_target",
                            "retreat_switch_goal"],
            "honesty": "No KO/lethal/exact-HP-survival claim; HP / attached-energy COUNT / "
                       "role are visible & coarse, not a computed survival/damage threshold.",
        },
        {
            "name": "setup_bench",
            "families": ["setup_bench"], "option_type_codes": [7, 10],
            "decide_kind": "setup_bench_multi",
            "policy": "Fill the bench with the engine that advances the plan: energy_accel "
                      "(183), bench-fill/search bodies (767/751/1086), a copy of the main "
                      "attacker (766) to grow, and a backup attacker. Prefer setup-advancing "
                      "bodies over inert ones; respect bench_pick_count.",
            "plan_fields": ["phase", "setup_bench", "attacker_target", "backup_target"],
            "honesty": "Bench-value is heuristic; no tempo/value claim.",
        },
        {
            "name": "attach_energy",
            "families": ["attach_energy"], "option_type_codes": [8],
            "decide_kind": "attach_energy",
            "policy": "Attach to energy_target — the in-play attacker we are fueling toward "
                      "its attack (main attacker 766 preferred, else the desired active, "
                      "else a backup attacker being set up). Targets are read from the "
                      "option's own inPlayArea/index over YOUR board.",
            "plan_fields": ["energy_target", "desired_active_role", "attack_now"],
            "honesty": "Energy adequacy is judged by the VISIBLE attached-energy COUNT only "
                       "(a coarse heuristic); attack costs are not reliably observable, so "
                       "NO exact-cost / threshold / lethal / damage claim — we fuel the "
                       "PLANNED attacker, not a computed number.",
        },
        {
            "name": "play_from_hand_engine",
            "families": ["play_from_hand"], "option_type_codes": [7],
            "decide_kind": None,
            "policy": "Sequence the trainer/engine plays that advance the plan: draw (1224 "
                      "Cheren) when hand is thin / early; search (1121 Ultra Ball, 1086 "
                      "Poffin, 1231 Dawn) toward search_targets; disruption (1182) when the "
                      "plan flags it. Pokémon-to-hand/bench plays ranked by role. The card "
                      "is resolved from the option's own hand/select entry.",
            "plan_fields": ["phase", "search_targets", "draw_deckout_safety"],
            "honesty": "No engine-internal (supporter-per-turn) claim asserted; we only "
                       "rank offered legal options.",
        },
        {
            "name": "play_in_play",
            "families": ["play_in_play", "evolve"], "option_type_codes": [10],
            "decide_kind": None,
            "policy": "All deck Pokémon are Basic (no evolution line), so treat as a "
                      "place-to-bench / in-play action that advances setup; rank by role "
                      "(energy_accel, bench_fill, backup attacker) like setup_bench.",
            "plan_fields": ["phase", "setup_bench"],
            "honesty": "Evolve/place ambiguity acknowledged; no value claim.",
        },
        {
            "name": "use_ability",
            "families": ["use_ability"], "option_type_codes": [9],
            "decide_kind": None,
            "policy": "Prefer using an offered ability that advances board/consistency over "
                      "ending the turn, but BELOW taking the planned attack. The deck's "
                      "abilities (766 Diamond Coat passive -30; 525 Debut Performance turn-1 "
                      "enabler) are largely passive; if an activatable ability option "
                      "appears we cannot read its exact effect from the schema, so default "
                      "is a mild advance-the-board preference.",
            "plan_fields": ["phase", "attack_now"],
            "honesty": "Ability effect not decoded from option schema; no effect/value claim.",
        },
        {
            "name": "move_energy",
            "families": ["move_energy"], "option_type_codes": [6],
            "decide_kind": None,
            "policy": "Rare; when a move-energy option targets toward the energy_target "
                      "(planned attacker) prefer it, else neutral offered-order. Targets "
                      "read from the option over YOUR board only.",
            "plan_fields": ["energy_target"],
            "honesty": "No exact-energy-economy/lethal claim.",
        },
        {
            "name": "search_to_hand",
            "families": ["search_to_hand"], "option_type_codes": [3],
            "decide_kind": "search_to_hand",
            "policy": "The specialist core: when a search effect lets us pick a card from "
                      "the deck (to hand or bench), pick toward search_targets given board "
                      "gaps — main attacker if absent and a clock is wanted; energy if the "
                      "planned attack is energy-short; bench-fill basics if bench is thin; "
                      "draw/consistency otherwise. Picks among OFFERED card ids only.",
            "plan_fields": ["search_targets", "attacker_target", "energy_target", "phase"],
            "honesty": "Reads only the OFFERED select list (deck card identities the engine "
                       "reveals for the choice); never the hidden deck order or full deck.",
        },
        {
            "name": "discard",
            "families": ["discard"], "option_type_codes": [3],
            "decide_kind": "discard",
            "policy": "Choose safe_discard when a cost/effect requires discarding (e.g. "
                      "Ultra Ball cost; Garland Ray's discard-energy scaling): shed surplus "
                      "energy / duplicate trainers / irrelevant tech; keep enough energy for "
                      "the planned attack and never discard the last main attacker. Respect "
                      "discard_count.",
            "plan_fields": ["safe_discard", "energy_target", "draw_deckout_safety"],
            "honesty": "The discard-for-scaling tradeoff is heuristic; NO exact-damage / "
                       "lethal / KO claim about Garland Ray.",
        },
        {
            "name": "draw_count",
            "families": ["draw_count"], "option_type_codes": [0, 1, 2],
            "decide_kind": "draw_count",
            "policy": "When an effect offers a choice of how many to draw, pick the refill "
                      "that respects draw_deckout_safety (do not draw so many that deck-out "
                      "risk rises). Bounded by the offered numbers.",
            "plan_fields": ["draw_deckout_safety", "phase"],
            "honesty": "Deck-out safety from VISIBLE deck_count only; no deck-order claim.",
        },
        {
            "name": "attack",
            "families": ["attack"], "option_type_codes": [13],
            "decide_kind": "attack(UNSUPPORTED for damage/lethal/ko/spread/gust)",
            "policy": "attack_now GATE only: when the plan wants a clock and a fueled "
                      "attacker is active, PREFER attacking over passing/ending. Among "
                      "multiple attack options we do NOT rank by damage (numeric attackId "
                      "only — damage/effect not in the schema); we keep offered order. "
                      "Attacking is preferred to end_turn only when attack_now is set.",
            "plan_fields": ["attack_now", "desired_active_role", "phase"],
            "honesty": "HARD boundary: no exact-damage, lethal, KO, missed-KO, spread, "
                       "Boss/gust target, or best-attack claim — attack outcome is not "
                       "observable from the option schema.",
        },
    ]


def _board_view_fields() -> list[dict]:
    return [
        {"field": "turn", "source": "board_snapshot.turn", "honest_unknown": "None"},
        {"field": "acting_seat", "source": "board_snapshot.acting_seat/your_index"},
        {"field": "went_first", "source": "inferred from turn==1 & seat; else unknown"},
        {"field": "phase", "source": "INFERRED {setup|develop|attack|end} from turn + "
                                     "active/bench/energy presence", "honest_unknown": "unknown"},
        {"field": "self_counts", "source": "visible_counts_by_zone(self): hand/deck/prize/"
                                           "discard/bench counts + active_present"},
        {"field": "opp_counts", "source": "visible_counts_by_zone(opp): COUNTS ONLY "
                                          "(prize_remaining, bench_count, active_present)"},
        {"field": "my_active_id", "source": "players[seat].active card id (visible)",
         "honest_unknown": "None"},
        {"field": "my_active_role", "source": "DiamondRoleMap[my_active_id]"},
        {"field": "my_bench_ids", "source": "players[seat].bench card ids (visible)"},
        {"field": "my_active_energy_count", "source": "visible energy attached to active"},
        {"field": "opp_active_id / opp_active_is_ex", "source": "ONLY if visible in frame; "
                                                               "else unknown (drives anti_ex)"},
        {"field": "select_ctx", "source": "n_options/min_count/max_count/families_present/"
                                          "is_forced_single from the select window"},
        {"field": "checkable", "source": "False when the frame is unparseable -> raw fallback"},
    ]


def _turn_plan_fields() -> list[dict]:
    return [
        {"field": "phase", "desc": "setup | develop | attack | end (inferred)"},
        {"field": "desired_active_role", "desc": "role we want active now (e.g. main_attacker "
                                                 "mid-game; turn1_enabler/durable early)"},
        {"field": "attacker_target", "desc": "card id of intended main attacker in play|None"},
        {"field": "backup_target", "desc": "card id of intended backup attacker|None"},
        {"field": "energy_target", "desc": "in-play card id to fuel with energy|None"},
        {"field": "setup_bench", "desc": "ordered roles/ids to bench to advance the engine"},
        {"field": "search_targets", "desc": "ordered roles/ids to fetch given board gaps"},
        {"field": "safe_discard", "desc": "ids safe to discard given the board"},
        {"field": "retreat_switch_goal", "desc": "promote_main_attacker | none (visible-only)"},
        {"field": "attack_now", "desc": "bool gate — heuristic, NOT lethal/KO"},
        {"field": "draw_deckout_safety", "desc": "max safe draw given visible deck_count"},
        {"field": "fallback_reason", "desc": "why the plan is degraded / honest-unknown"},
    ]


def _unsupported_claims() -> list[str]:
    return [
        "exact_damage", "lethal", "ko", "missed_ko", "boss_gust_target", "spread",
        "best_action", "best_attack", "card_value", "tempo_value",
        "opponent_hand_contents", "opponent_deck_order", "own_deck_order",
        "prize_contents", "kaggle_score_or_strength",
    ]


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    audit = _load_audit()
    deck_ids = {int(k) for k in audit["copy_counts"]}
    role_by_id, priorities = _role_map(audit)
    contexts = _contexts()
    bv = _board_view_fields()
    tp = _turn_plan_fields()
    unsupported = _unsupported_claims()

    # ---- self-validation (fail-closed) -------------------------------------------------
    problems: list[str] = []
    for cid in role_by_id:
        if cid not in deck_ids:
            problems.append(f"role-map card {cid} not in verified deck (invented id?)")
    main_attackers = [cid for cid, t in role_by_id.items() if "main_attacker" in t]
    if main_attackers != [766]:
        problems.append(f"main attacker must be [766]; got {main_attackers}")
    for ctx in contexts:
        for code in ctx["option_type_codes"]:
            if code not in OPTION_TYPE_CLASS:
                problems.append(f"{ctx['name']}: option code {code} not a real cabt code")
        dk = ctx["decide_kind"]
        if isinstance(dk, str) and dk:
            for tok in dk.split("|"):
                if tok.startswith("attack("):
                    continue
                if tok not in SUPPORTED_DECIDE_KINDS:
                    problems.append(
                        f"{ctx['name']}: decide_kind {tok!r} not a real supported kind")
    for boundary in ("lethal", "spread", "boss", "gust", "ko_target"):
        # every typed unsupported kind must be reflected in our unsupported-claims set
        tok = "ko" if boundary == "ko_target" else boundary
        if not any(tok in u for u in unsupported):
            problems.append(f"unsupported boundary {boundary!r} not covered in claims list")
    if len(contexts) != 11:
        problems.append(f"expected exactly 11 per-context policies; got {len(contexts)}")
    n_codes = {c for ctx in contexts for c in ctx["option_type_codes"]}
    real_action_codes = {0, 1, 2, 3, 6, 7, 8, 9, 10, 13}  # end_turn (12/14) is the default
    uncovered = sorted(real_action_codes - n_codes)

    ok = not problems
    blueprint = {
        "pass": "46j", "part": "C", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "no_online_search_in_hot_path": True,
        "never_raises_returns_legal_indices": True,
        "parent_id": audit["parent_id"],
        "is_planner_not_flat_scorer": True,
        "design_summary": (
            "DiamondBoardView (visible board view) -> DiamondTurnPlan (one coherent plan: "
            "phase, desired active role, attacker/backup/energy targets, setup/search/"
            "discard intents, attack_now gate, deck-out safety) -> 11 per-context policies "
            "that rank ONLY the legal option indices for the current decision. The plan is "
            "computed ONCE per decision and SHARED across contexts, so the agent's choices "
            "cohere across attach/search/discard/attack rather than scoring each option in "
            "isolation."),
        "diamond_role_map": {str(k): v for k, v in sorted(role_by_id.items())},
        "role_priorities": priorities,
        "board_view_fields": bv,
        "turn_plan_fields": tp,
        "per_context_policies": contexts,
        "n_context_policies": len(contexts),
        "real_option_type_class": {str(k): v for k, v in OPTION_TYPE_CLASS.items()},
        "dispatch_grounding": {
            "note": "DISPATCH IS BY RAW OPTION `type` CODE / resolved action_class — NEVER "
                    "by turn_primitives family-name strings, whose vocabulary differs "
                    "(classify_action_family returns attach / ability / main_play / evolve / "
                    "unknown). The bridge below documents code -> action_class -> our context "
                    "-> typed decide kind so the two vocabularies never silently diverge.",
            "bridge": [
                {"codes": [0, 1, 2], "action_class": "effect_choice",
                 "context": "draw_count (numeric draw) else default", "decide_kind": "draw_count"},
                {"codes": [3], "action_class": "select_card",
                 "context": "search_to_hand (deck) / discard (discard) / choose_active "
                            "(bench->active promote)",
                 "decide_kind": "search_to_hand|discard|emergency_backup_bench"},
                {"codes": [6], "action_class": "move_energy", "context": "move_energy",
                 "decide_kind": None},
                {"codes": [7], "action_class": "play_from_hand",
                 "context": "choose_active (setup) / setup_bench / play_from_hand_engine",
                 "decide_kind": "setup_active|setup_bench_multi"},
                {"codes": [8], "action_class": "attach_energy", "context": "attach_energy",
                 "decide_kind": "attach_energy"},
                {"codes": [9], "action_class": "use_ability", "context": "use_ability",
                 "decide_kind": None},
                {"codes": [10], "action_class": "play_in_play", "context": "play_in_play",
                 "decide_kind": None},
                {"codes": [12, 14], "action_class": "end_turn", "context": "default handler",
                 "decide_kind": None},
                {"codes": [13], "action_class": "attack", "context": "attack (gate only)",
                 "decide_kind": "attack(UNSUPPORTED for damage/lethal/ko/spread/gust)"},
            ],
        },
        "retreat_switch_note": (
            "Retreat/switch of YOUR own active is governed by the retreat_switch_goal plan "
            "field (visible-only). cabt exposes no positively-observed dedicated retreat code "
            "in OPTION_TYPE_CLASS; if a distinct retreat option appears it is ranked by "
            "retreat_switch_goal, and any retreat-cost sub-selection (energy move/discard) "
            "routes to the move_energy / discard policies. A forced promote after a KO is "
            "handled by choose_active (emergency_backup_bench). No gust/forced-switch target "
            "claim is made."),
        "attribution_plan": {
            "no_46h_weight_reuse": True,
            "rationale": "The planner must earn any edge from the SHARED plan + Diamond "
                         "roles, not from reused 46H linear weights; it imports no 46H "
                         "profile and ships its own plan-driven ordering.",
            "baselines": ["parent diamond_toolbox_diancie",
                          "46H cg_typed_diamond_option_value_v1 (generic scorer)",
                          "46H cg_typed_diamond_family_only_floor_v1 (family floor)"],
            "non_inertness": "Trace choice deltas vs parent AND vs 46H option_value, broken "
                             "down BY CONTEXT and option family; require plan-field-driven "
                             "changes (not cosmetic); illegal=0; exceptions=0.",
            "ablations": [
                "no_shared_plan (rank options without the shared DiamondTurnPlan)",
                "no_diamond_roles (neutral role map)",
                "attack_gate_disabled (attack_now forced false)",
            ],
            "ablation_requirement": "each ablation must measurably change behavior to credit "
                                    "the corresponding design element; otherwise that element "
                                    "is inert and cannot be claimed as the source of any edge.",
            "decision_rule_note": "promising requires parent H2H confirmed / strongly-"
                                  "directional clean seats AND separation from the generic "
                                  "scorers (Fisher increment) AND safety / validation / "
                                  "non-inertness (0 illegal) / no leakage.",
        },
        "default_handler": {
            "covers": ["effect_choice(0,1,2 when not a draw-count)", "end_turn(12,14)",
                       "select_card with unknown source", "unknown/unmappable options"],
            "behaviour": "honest neutral: keep offered order / prefer a productive "
                         "non-end_turn option only when attack_now is unset; always returns "
                         "legal indices; never raises.",
            "action_codes_not_in_named_policies": uncovered,
        },
        "unsupported_claims": unsupported,
        "typed_unsupported_kinds_mirrored": sorted(UNSUPPORTED_DECIDE_KINDS),
        "validation": {"ok": ok, "problems": problems},
        "source_audit": str(AUDIT_JSON.relative_to(REPO)),
    }
    (EXP / "pass46j_diamond_planner_blueprint.json").write_text(
        json.dumps(blueprint, indent=2) + "\n", encoding="utf-8")

    name_by_id = {c["card_id"]: c["name"] for c in audit["cards"]}

    def nm(cid):
        return f"{cid} {name_by_id.get(cid, '?')}"

    md = [
        "# Pass 46J — Part C: Diamond specialist turn-planner blueprint", "",
        f"Parent (internal): `{audit['parent_id']}`. A REAL deck-specific TURN PLANNER, "
        "not a flat option/family scorer.", "",
        "> Plan-first design: a single DiamondTurnPlan is computed per decision from a "
        "visible-only DiamondBoardView, then 11 per-context policies rank ONLY the legal "
        "option indices so attach / search / discard / attack choices COHERE. Never raises; "
        "always returns legal indices. No online Search in the hot path. Honesty boundaries "
        "below are hard.", "",
        f"**Self-validation: ok = {ok}**" + (f" — problems: {problems}" if problems else ""),
        "",
        "## DiamondBoardView (visible only — no hidden zones)",
        "| field | source |", "|---|---|",
    ]
    md += [f"| `{f['field']}` | {f['source']} |" for f in bv]
    md += ["", "## DiamondTurnPlan", "| field | meaning |", "|---|---|"]
    md += [f"| `{f['field']}` | {f['desc']} |" for f in tp]
    md += ["", "## DiamondRoleMap (derived from Part-B audit — every id verified)",
           "| card | roles |", "|---|---|"]
    md += [f"| {nm(cid)} | {', '.join(role_by_id[cid]) or '—'} |"
           for cid in sorted(role_by_id)]
    md += ["", "### Role priorities (inferred — not value/strength claims)",
           f"- attacker priority: {[nm(c) for c in priorities['attacker_priority']]}",
           "- energy-target rule: " + "; ".join(priorities["energy_target_rule"]),
           "- search-target rule: " + "; ".join(priorities["search_target_rule"]),
           "- safe-discard rule: " + "; ".join(priorities["safe_discard_rule"])]
    md += ["", "## 11 per-context policies (each maps to a REAL cabt option code / kind)",
           "| # | context | option codes | decide kind | plan fields | honesty |",
           "|---|---|---|---|---|---|"]
    for i, ctx in enumerate(contexts, 1):
        md.append(
            f"| {i} | **{ctx['name']}** | {ctx['option_type_codes']} | "
            f"`{ctx['decide_kind']}` | {', '.join(ctx['plan_fields'])} | {ctx['honesty']} |")
    md += ["", "### Policy detail"]
    for i, ctx in enumerate(contexts, 1):
        md.append(f"{i}. **{ctx['name']}** — {ctx['policy']}")
    md += ["", "## Default handler (not one of the 11 named policies)",
           f"- covers: {blueprint['default_handler']['covers']}",
           f"- behaviour: {blueprint['default_handler']['behaviour']}",
           f"- action codes not in named policies: "
           f"{blueprint['default_handler']['action_codes_not_in_named_policies']} "
           "(12/14 = end_turn handled by the attack_now/productive-alternative default)"]
    md += ["", "## Dispatch grounding (raw option code -> context — NOT family-name strings)",
           blueprint["dispatch_grounding"]["note"], "",
           "| option codes | action_class | our context | typed decide kind |",
           "|---|---|---|---|"]
    for b in blueprint["dispatch_grounding"]["bridge"]:
        md.append(f"| {b['codes']} | {b['action_class']} | {b['context']} | "
                  f"`{b['decide_kind']}` |")
    md += ["", "## Retreat / switch / promote", blueprint["retreat_switch_note"]]
    ap = blueprint["attribution_plan"]
    md += ["", "## Attribution plan (planner separable from 46H generic scorers)",
           f"- **no 46H weight reuse:** {ap['no_46h_weight_reuse']} — {ap['rationale']}",
           "- baselines: " + "; ".join(ap["baselines"]),
           f"- non-inertness: {ap['non_inertness']}",
           "- ablations: " + "; ".join(ap["ablations"]),
           f"- ablation requirement: {ap['ablation_requirement']}",
           f"- decision rule: {ap['decision_rule_note']}"]
    md += ["", "## Unsupported claims (hard honesty boundary)",
           ", ".join(f"`{u}`" for u in unsupported),
           "", f"Mirrors the typed layer's unsupported kinds: "
           f"{sorted(UNSUPPORTED_DECIDE_KINDS)}.",
           "", "## Runtime contract",
           "- `agent(obs_dict) -> list[int]` legal option indices (or the 60 deck ids on the "
           "deck-submission step).",
           "- Pure / read-only: NO ObjectStorage, EventStore, Kaggle, cg-runtime mutation, "
           "file IO, or online Search in the hot path.",
           "- Never raises: any parse failure -> raw-obs legal fallback (first legal / full "
           "legal window).",
           "- Deck is the parent's deck, byte-identical; refs are benchmark-only."]
    (EXP / "pass46j_diamond_planner_blueprint.md").write_text("\n".join(md) + "\n",
                                                              encoding="utf-8")

    print(json.dumps({
        "ok": ok, "problems": problems, "n_context_policies": len(contexts),
        "main_attacker": main_attackers,
        "role_map_card_count": len(role_by_id),
        "all_role_ids_in_deck": all(c in deck_ids for c in role_by_id),
        "action_codes_uncovered_by_named_policies": uncovered,
    }, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
