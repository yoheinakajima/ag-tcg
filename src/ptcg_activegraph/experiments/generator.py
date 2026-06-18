"""Candidate generation: policy variants and deck variants.

Two tracks:

* **Policy candidates** — take the baseline ``main.py`` source and inject a
  small, append-only override block that reassigns scoring constants
  (``_OPTION_TYPE_SCORES``, ``_ATTACK_ID_BONUS``, ``_POSITIVE``, ``_NEGATIVE``).
  These helpers are read at call time via module globals, so the injected block
  (placed just before ``if __name__ == "__main__":``) changes behaviour without
  editing any existing line. The result stays standard-library-only,
  self-contained, and keeps the ``select=None`` deck-return behaviour.

* **Deck candidates** — start from the baseline 60-card list and apply signed
  per-card-id deltas grounded in ``data/cards/EN_Card_Data.csv``. We never
  invent card ids: every id used already appears in the baseline deck. Basic
  energy (the only card allowed > 4 copies) is the trim source; non-energy
  cards are only bumped from an existing count of 2 up to at most 4, so deck
  legality holds. Every generated deck is still re-validated and smoke-tested
  before it can be ranked.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ..decks.deck_io import load_deck, save_deck
from .branch import Branch, make_run_dir, write_branch_yaml
from .config import ExperimentConfig

_INJECT_ANCHOR = 'if __name__ == "__main__":'

# Baseline card identities (confirmed from data/cards/EN_Card_Data.csv). Used
# only for human-readable hypotheses and to pick which counts to adjust; the
# generator never relies on these for legality (the validator + smoke do).
CARD_NAMES = {
    3: "Basic {W} Energy",
    721: "Kyogre",
    722: "Snover",
    723: "Mega Abomasnow ex",
    1092: "Secret Box",
    1121: "Ultra Ball",
    1145: "Mega Signal",
    1163: "Powerglass",
    1219: "Team Rocket's Petrel",
    1227: "Lillie's Determination",
    1262: "Surfing Beach",
}
ENERGY_ID = 3


# ---------------------------------------------------------------------------
# Policy candidate specs
# ---------------------------------------------------------------------------
# Each override key maps to an injected statement:
#   option_type_scores -> _OPTION_TYPE_SCORES.update({...})
#   attack_id_bonus    -> _ATTACK_ID_BONUS = <int>
#   positive           -> _POSITIVE.update({...})
#   negative           -> _NEGATIVE.update({...})

POLICY_SPECS: list[dict] = [
    {
        "branch_id": "policy_attack_heavy",
        "seam_id": "policy.attack_priority",
        "archetype": "linear_aggro",
        "hypothesis": "Strongly preferring confirmed attacks (type 13) and "
        "knockouts should raise attack rate and shorten games without crashing.",
        "overrides": {
            "option_type_scores": {13: 220, 14: -90},
            "attack_id_bonus": 70,
            "positive": {"attack": 140, "knockout": 170, "knock": 150},
        },
    },
    {
        "branch_id": "policy_pass_avoidant",
        "seam_id": "policy.pass_avoidance",
        "archetype": "linear_aggro",
        "hypothesis": "Heavier penalties on pass/end (type 14) options should "
        "cut the pass rate and keep the agent acting when real plays exist.",
        "overrides": {
            "option_type_scores": {14: -160},
            "negative": {"pass": -260, "end": -260, "done": -220},
        },
    },
    {
        "branch_id": "policy_evolution_bias",
        "seam_id": "policy.evolution_priority",
        "archetype": "setup_evolution",
        "hypothesis": "Biasing toward evolve/evolution options should help the "
        "Snover -> Mega Abomasnow ex line set up before attacking.",
        "overrides": {
            "positive": {"evolve": 95, "evolution": 90},
        },
    },
    {
        "branch_id": "policy_energy_bias",
        "seam_id": "policy.energy_priority",
        "archetype": "setup_evolution",
        "hypothesis": "Prioritising attach/energy (and placement type 8) when no "
        "attack is available should accelerate powering up attackers.",
        "overrides": {
            "option_type_scores": {8: 28},
            "positive": {"attach": 85, "energy": 85},
        },
    },
    {
        "branch_id": "policy_draw_search_bias",
        "seam_id": "policy.search_targeting",
        "archetype": "consistency_engine",
        "hypothesis": "Boosting draw/search/supporter/item preference should "
        "improve setup consistency turn over turn.",
        "overrides": {
            "positive": {"draw": 85, "search": 85, "supporter": 70, "item": 60},
        },
    },
    {
        "branch_id": "policy_bench_pressure",
        "seam_id": "policy.bench_pressure",
        "archetype": "linear_aggro",
        "hypothesis": "Favouring placement (type 8) builds a wider bench earlier, "
        "giving more attackers to promote after a knockout.",
        "overrides": {
            "option_type_scores": {8: 45},
            "positive": {"bench": 60},
        },
    },
    {
        "branch_id": "policy_setup_evolution",
        "seam_id": "archetype.setup_evolution",
        "archetype": "setup_evolution",
        "hypothesis": "A combined evolution + energy setup tilt should reach the "
        "Mega Abomasnow ex line faster, trading early tempo for ceiling.",
        "overrides": {
            "option_type_scores": {8: 24},
            "positive": {"evolve": 90, "evolution": 85, "attach": 75, "energy": 75},
        },
    },
    {
        "branch_id": "policy_conservative_baseline",
        "seam_id": "archetype.baseline_exploit",
        "archetype": "baseline_exploit",
        "hypothesis": "An exact copy of the v1 control (no overrides) anchors the "
        "batch and confirms the harness reproduces the baseline.",
        "overrides": {},
    },
]


# ---------------------------------------------------------------------------
# Deck candidate specs (deltas are signed per-card-id; sum must be 0)
# ---------------------------------------------------------------------------

DECK_SPECS: list[dict] = [
    {
        "branch_id": "deck_energy_trim_light",
        "seam_id": "deck.energy_trim",
        "archetype": "consistency_engine",
        "hypothesis": "Trimming 4 Basic {W} Energy for +2 Kyogre and +2 Ultra "
        "Ball keeps power online while adding an attacker and a search item.",
        "deltas": {ENERGY_ID: -4, 721: +2, 1121: +2},
    },
    {
        "branch_id": "deck_energy_trim_medium",
        "seam_id": "deck.energy_trim",
        "archetype": "consistency_engine",
        "hypothesis": "A larger 10-energy trim maxing Kyogre, Ultra Ball, Mega "
        "Signal, Powerglass and Surfing Beach to 4 should sharply raise "
        "consistency; watch for energy droughts.",
        "deltas": {ENERGY_ID: -10, 721: +2, 1121: +2, 1145: +2, 1163: +2, 1262: +2},
    },
    {
        "branch_id": "deck_baseline_consistency",
        "seam_id": "deck.consistency_engine",
        "archetype": "consistency_engine",
        "hypothesis": "Trimming 4 energy for +2 Ultra Ball and +2 Mega Signal "
        "maximises draw/search density for steadier setups.",
        "deltas": {ENERGY_ID: -4, 1121: +2, 1145: +2},
    },
    {
        "branch_id": "deck_attacker_focus",
        "seam_id": "deck.attacker_focus",
        "archetype": "linear_aggro",
        "hypothesis": "Trimming 2 energy for +2 Kyogre adds a second Basic "
        "attacker line (Snover/Mega Abomasnow ex already max at 4).",
        "deltas": {ENERGY_ID: -2, 721: +2},
    },
]

# Deck experiments confirmed-or-blocked but not generated this pass, with a
# transparent reason (no invented cards, no unconfirmed strategy).
DECK_BLOCKED: list[dict] = [
    {
        "branch_id": "deck_abomasnow_line_focus",
        "seam_id": "deck.abomasnow_line_focus",
        "archetype": "setup_evolution",
        "hypothesis": "Lean further into Snover -> Mega Abomasnow ex.",
        "blocked_reason": "card ids confirmed (Snover 722, Mega Abomasnow ex 723) "
        "but both are already at the 4-copy maximum in the baseline; nothing to add.",
    },
    {
        "branch_id": "deck_anti_baseline",
        "seam_id": "deck.anti_baseline",
        "archetype": "anti_meta",
        "hypothesis": "Tech specific counters against the mirror.",
        "blocked_reason": "no clear counter cards identified in metadata yet; "
        "would require inventing card ids.",
    },
]


# ---------------------------------------------------------------------------
# Pass 6 deck variants AROUND the v2 control (deck_energy_trim_light).
# Each delta is relative to the ROOT baseline deck and equals the v2 deltas
# ({3:-4, 721:+2, 1121:+2}) PLUS one small single-card swap, so the only change
# vs the v2 control is that swap. The v2 *exact* deck itself is an integrity
# anchor (deck_energy_trim_light), never re-emitted here. All ids are confirmed
# in data/cards/EN_Card_Data.csv: Secret Box 1092 (baseline x1), Powerglass 1163
# (x2), Mega Signal 1145 (x2), Surfing Beach 1262 (x2), Team Rocket's Petrel 1219
# (x4). Every resulting deck is 60 cards and stays at/below 4 copies per card.
# ---------------------------------------------------------------------------

PASS6_DECK_SPECS: list[dict] = [
    {
        "branch_id": "deck_v2_no_secret_box__powerglass",
        "seam_id": "deck.secret_box_swap",
        "archetype": "consistency_engine",
        "hypothesis": "Cut the lone Secret Box (1092) for a 3rd Powerglass (1163) "
        "to test whether a steadier energy-acceleration item beats the one-shot "
        "Secret Box toolbox over the v2 control.",
        "deltas": {ENERGY_ID: -4, 721: +2, 1121: +2, 1092: -1, 1163: +1},
    },
    {
        "branch_id": "deck_v2_no_secret_box__mega_signal",
        "seam_id": "deck.secret_box_swap",
        "archetype": "consistency_engine",
        "hypothesis": "Cut the lone Secret Box (1092) for a 3rd Mega Signal (1145) "
        "to bias toward fetching the Snover -> Mega Abomasnow ex line more often "
        "than the Secret Box toolbox does.",
        "deltas": {ENERGY_ID: -4, 721: +2, 1121: +2, 1092: -1, 1145: +1},
    },
    {
        "branch_id": "deck_v2_no_secret_box__surfing_beach",
        "seam_id": "deck.secret_box_swap",
        "archetype": "tempo_control",
        "hypothesis": "Cut the lone Secret Box (1092) for a 3rd Surfing Beach "
        "(1262) to test whether extra stadium/recovery value beats the Secret Box "
        "toolbox over the v2 control.",
        "deltas": {ENERGY_ID: -4, 721: +2, 1121: +2, 1092: -1, 1262: +1},
    },
    {
        "branch_id": "deck_v2_less_petrel__powerglass",
        "seam_id": "deck.petrel_swap",
        "archetype": "consistency_engine",
        "hypothesis": "Trim one Team Rocket's Petrel (1219, baseline x4) for a 3rd "
        "Powerglass (1163) to test whether more energy acceleration outweighs the "
        "fourth disruption supporter over the v2 control.",
        "deltas": {ENERGY_ID: -4, 721: +2, 1121: +2, 1219: -1, 1163: +1},
    },
]


# ---------------------------------------------------------------------------
# Generation-2 combination candidate specs
# ---------------------------------------------------------------------------
# A combo applies a policy override block AND a deck delta together, so we can
# test interaction effects (does the evolution tilt help more once the deck is
# leaned toward consistency?). Every combo references existing single-seam specs
# by id — no new card ids, no new override constants are invented here.

COMBO_SPECS: list[dict] = [
    {
        "branch_id": "combo_evo_bias__baseline_consistency",
        "seam_id": "combo.evolution_consistency",
        "archetype": "setup_evolution",
        "policy_refs": ["policy_evolution_bias"],
        "deck_ref": "deck_baseline_consistency",
        "hypothesis": "Evolution-priority policy plus the +Ultra Ball/+Mega Signal "
        "consistency deck should reach the Mega Abomasnow ex line more reliably "
        "than either change alone.",
        "required": True,
    },
    {
        "branch_id": "combo_evo_bias__energy_trim_medium",
        "seam_id": "combo.evolution_energy_trim",
        "archetype": "setup_evolution",
        "policy_refs": ["policy_evolution_bias"],
        "deck_ref": "deck_energy_trim_medium",
        "hypothesis": "Evolution-priority policy with the deeper 10-energy trim "
        "tests whether faster setup offsets the higher energy-drought risk.",
        "required": True,
    },
    {
        "branch_id": "combo_evo_pass__baseline_consistency",
        "seam_id": "combo.evolution_pass_consistency",
        "archetype": "setup_evolution",
        "policy_refs": ["policy_evolution_bias", "policy_pass_avoidant"],
        "deck_ref": "deck_baseline_consistency",
        "hypothesis": "Stacking evolution-priority and pass-avoidance over the "
        "consistency deck should keep the agent acting AND setting up, compounding "
        "two scout leaders.",
        "required": True,
    },
    {
        "branch_id": "combo_evo_pass__energy_trim_medium",
        "seam_id": "combo.evolution_pass_energy_trim",
        "archetype": "setup_evolution",
        "policy_refs": ["policy_evolution_bias", "policy_pass_avoidant"],
        "deck_ref": "deck_energy_trim_medium",
        "hypothesis": "Evolution + pass-avoidance policy on the aggressive 10-energy "
        "trim deck tests the fastest-setup, fewest-wasted-turns configuration.",
        "required": True,
    },
    {
        "branch_id": "combo_evo_attack__baseline_consistency",
        "seam_id": "combo.evolution_attack_consistency",
        "archetype": "setup_evolution",
        "policy_refs": ["policy_evolution_bias", "policy_attack_heavy"],
        "deck_ref": "deck_baseline_consistency",
        "hypothesis": "Evolution setup tilt plus an attack-priority finisher over "
        "the consistency deck tests whether setup-then-swing beats pure setup.",
        "required": True,
    },
    {
        "branch_id": "combo_evo_attack__energy_trim_medium",
        "seam_id": "combo.evolution_attack_energy_trim",
        "archetype": "setup_evolution",
        "policy_refs": ["policy_evolution_bias", "policy_attack_heavy"],
        "deck_ref": "deck_energy_trim_medium",
        "hypothesis": "Evolution + attack-priority policy on the 10-energy trim deck "
        "tests the most aggressive setup-and-swing build in the pass.",
        "required": True,
    },
    # Optional combos (generated when budget allows; clearly lower priority).
    {
        "branch_id": "combo_energy_bias__energy_trim_light",
        "seam_id": "combo.energy_priority_trim",
        "archetype": "consistency_engine",
        "policy_refs": ["policy_energy_bias"],
        "deck_ref": "deck_energy_trim_light",
        "hypothesis": "Energy-attach priority paired with a light energy trim tests "
        "whether smarter attachment compensates for slightly fewer energy cards.",
        "required": False,
    },
    {
        "branch_id": "combo_draw_search__baseline_consistency",
        "seam_id": "combo.search_consistency",
        "archetype": "consistency_engine",
        "policy_refs": ["policy_draw_search_bias"],
        "deck_ref": "deck_baseline_consistency",
        "hypothesis": "Draw/search policy bias over the consistency deck doubles "
        "down on setup density; tests for over-drawing diminishing returns.",
        "required": False,
    },
    {
        "branch_id": "combo_setup_evo__energy_trim_medium",
        "seam_id": "combo.setup_archetype_trim",
        "archetype": "setup_evolution",
        "policy_refs": ["policy_setup_evolution"],
        "deck_ref": "deck_energy_trim_medium",
        "hypothesis": "The combined evolution+energy archetype policy on the deep "
        "trim deck tests the strongest single-policy setup tilt with deck support.",
        "required": False,
    },
]


# ---------------------------------------------------------------------------
# Pass 4: replay-derived effect-resolution policy candidates
# ---------------------------------------------------------------------------
# IMPORTANT honesty note: the only override hook is keyword/option-type weighting
# (_POSITIVE / _NEGATIVE / _OPTION_TYPE_SCORES / _ATTACK_ID_BONUS). There is NO
# board-state card-targeting hook in main.py, so true "discard the worst card /
# search the missing board piece" effect resolution cannot be expressed. These
# candidates are therefore honest LIGHTWEIGHT KEYWORD-WEIGHT APPROXIMATIONS:
# they bias the ranker toward high-value card *names* (which appear in the
# JSON-serialized option text) over first-legal / basic-energy choices. Each
# hypothesis states this limitation explicitly. All card ids referenced are
# confirmed in data/cards/EN_Card_Data.csv (see pass4_id_confirmation.json).

PASS4_POLICY_SPECS: list[dict] = [
    {
        "branch_id": "policy_effect_resolution_v1",
        "seam_id": "policy.effect_resolution_targeting",
        "archetype": "consistency_engine",
        "hypothesis": "Effect-resolution targeting (approx): on search/to-hand "
        "prompts, bias toward high-value targets by card name (Ultra Ball, Mega "
        "Signal, Secret Box, Lillie's Determination, Mega Abomasnow line, Kyogre) "
        "over first-legal/basic energy. Keyword-weight approximation only — board "
        "state is not reachable through the override hook.",
        "overrides": {
            "positive": {
                "ultra ball": 70, "mega signal": 60, "secret box": 60,
                "lillie": 55, "abomasnow": 50, "kyogre": 45, "snover": 45,
                "powerglass": 35,
            },
        },
    },
    {
        "branch_id": "policy_ultra_ball_v1",
        "seam_id": "policy.ultra_ball_discard_and_search",
        "archetype": "consistency_engine",
        "hypothesis": "Ultra Ball (1121) emphasis (approx): nudge toward playing "
        "Ultra Ball and toward fetching the missing attacker/evolution line "
        "(Mega Abomasnow / Snover / Kyogre). 'Discard energy first' is a board "
        "decision the keyword hook cannot target, so only the search-target side "
        "is approximated here.",
        "overrides": {
            "positive": {"ultra ball": 85, "abomasnow": 55, "snover": 50, "kyogre": 45},
        },
    },
    {
        "branch_id": "policy_secret_box_v1",
        "seam_id": "policy.secret_box_mode_selection",
        "archetype": "consistency_engine",
        "hypothesis": "Secret Box (1092) mode selection (approx): boost choosing "
        "Secret Box and high-leverage classes by name (Ultra Ball, Mega Signal, "
        "Lillie's Determination, Powerglass, Surfing Beach). Stays conservative "
        "where names are absent. Keyword-weight approximation only.",
        "overrides": {
            "positive": {
                "secret box": 85, "ultra ball": 55, "mega signal": 50,
                "lillie": 45, "powerglass": 35, "surfing beach": 30,
            },
        },
    },
    {
        "branch_id": "policy_attach_targeting_v1",
        "seam_id": "policy.attach_targeting",
        "archetype": "setup_evolution",
        "hypothesis": "Attach targeting (approx): prefer attach/place actions "
        "(type 8) and active-target keywords so energy/tools land on the current "
        "attacker. Precise 'attach to next-turn attacker' needs board state, so "
        "this is the lightweight keyword/type approximation.",
        "overrides": {
            "option_type_scores": {8: 30},
            "positive": {"attach": 70, "energy": 55, "active": 30},
        },
    },
]

# Pass 4 combos: v2 deck (deck_energy_trim_light deltas) + effect-resolution
# policy, plus a v2-deck control anchor (no policy override) so the scout board
# has a same-deck reference point the ranker recognizes as the control.
PASS4_COMBO_SPECS: list[dict] = [
    {
        "branch_id": "combo_v2_deck__effect_resolution_v1",
        "seam_id": "combo.v2_effect_resolution",
        "archetype": "consistency_engine",
        "policy_refs": ["policy_effect_resolution_v1"],
        "deck_ref": "deck_energy_trim_light",
        "hypothesis": "The v2 control deck (trim 4 energy, +2 Kyogre, +2 Ultra "
        "Ball) plus effect-resolution targeting tests whether smarter search/"
        "effect choices compound with the stronger deck.",
        "required": True,
    },
    {
        "branch_id": "pass4_control_v2_anchor",
        "seam_id": "archetype.baseline_exploit",
        "archetype": "baseline_exploit",
        "policy_refs": [],
        "deck_ref": "deck_energy_trim_light",
        "hypothesis": "Exact v2 control (v2 deck, no policy override) anchors the "
        "Pass 4 scout batch and confirms the harness reproduces the v2 baseline "
        "as a ~50% mirror.",
        "required": True,
    },
]

# Pass 4 chaos scout candidates. BLOCKED: a legal 60-card chaos decklist cannot
# be assembled from the ~8-10 confirmed core cards per archetype without
# inventing the remaining ~50 ids, which this pass forbids. Recorded honestly so
# the report shows them as blocked-with-reason rather than guessed at.
CHAOS_BLOCKED: list[dict] = [
    {
        "branch_id": "chaos_hand_avalanche_froslass_light",
        "seam_id": "chaos.hand_avalanche_froslass",
        "archetype": "chaos",
        "hypothesis": "Preserve large opponent hands, then convert hand size to "
        "damage with Mega Froslass ex.",
        "core_card_ids": [861, 103, 860, 1223, 1237, 1213, 1103, 1087, 1197],
        "blocked_reason": "core ids confirmed in metadata, but a legal 60-card "
        "list needs ~50 more ids (energy, supporting line, trainers) that are not "
        "confirmed for this archetype; building it would require inventing ids.",
    },
    {
        "branch_id": "chaos_bench_bloat_zoroark_or_hypno",
        "seam_id": "chaos.bench_bloat_punisher",
        "archetype": "chaos",
        "hypothesis": "Crowd the opponent bench with Accompanying Flute, then "
        "punish bench size with bench-scaling attackers.",
        "core_card_ids": [1091, 615, 430, 79, 95, 956, 1059, 1187, 1204],
        "blocked_reason": "core ids confirmed, but completing a legal 60-card deck "
        "requires ~50 unconfirmed support/energy ids; no invented ids allowed.",
    },
    {
        "branch_id": "chaos_durant_basic_mill",
        "seam_id": "chaos.mill_resource_destruction",
        "archetype": "chaos",
        "hypothesis": "Disrupt opponent deck/hand/energy so brittle bots lose key "
        "pieces, run out of energy, or deck out.",
        "core_card_ids": [198, 58, 896, 881, 440, 290, 1120, 1149, 1087],
        "blocked_reason": "core ids confirmed, but a legal 60-card mill list needs "
        "~50 unconfirmed support/energy ids; cannot complete without inventing ids.",
    },
    {
        "branch_id": "chaos_status_confusion_light",
        "seam_id": "chaos.status_confusion_lock",
        "archetype": "chaos",
        "hypothesis": "Use Confusion/Burn/Sleep and forced switching to create "
        "mis-sequencing and lost turns for opposing bots.",
        "core_card_ids": [1095, 1265, 813, 1204, 861, 968, 854, 1243],
        "blocked_reason": "core ids confirmed, but the remaining ~50 ids for a "
        "legal deck are unconfirmed; no invented ids allowed.",
    },
    {
        "branch_id": "chaos_vivillon_decidueye_research",
        "seam_id": "chaos.vivillon_decidueye_four_card_lock",
        "archetype": "chaos",
        "hypothesis": "Use Vivillon/Judge to set the opponent to exactly 4 cards, "
        "enabling Decidueye ex's reduced-cost attack while disrupting hand quality.",
        "core_card_ids": [1017, 1018, 1019, 1020, 1021, 1022, 1213, 1261, 1231, 1225],
        "blocked_reason": "core ids confirmed, but completing a legal 60-card "
        "Vivillon/Decidueye list needs ~50 unconfirmed ids; cannot invent ids.",
    },
]


# ---------------------------------------------------------------------------
# Pass 6 (Part H): BUILDABLE chaos candidates.
#
# Honesty note: a chaos archetype is buildable here only when (a) its attacker's
# full evolution line is confirmed in EN_Card_Data, and (b) a legal 60-card shell
# (<=4 copies per card NAME, >=1 Basic, matching basic energy) can be filled with
# confirmed ids alone. Each ``deck_counts`` below is an explicit {card_id: count}
# multiset; every id is confirmed and the energy id matches the attacker's type.
# Telemetry note: Pass-6 corrected the contract (T002) -- opponent handCount /
# benchCount / deckCount ARE observable -- so these chaos win-conditions are now
# measurable from the live observation (only opponent CONTENTS stay hidden).
PASS6_CHAOS_SPECS: list[dict] = [
    {
        "branch_id": "chaos_v6_froslass_handcount",
        "seam_id": "chaos.hand_avalanche_froslass",
        "archetype": "chaos",
        "hypothesis": "Mega Froslass ex's Resentful Refrain scales 50x with the "
        "opponent's hand size (now an OBSERVABLE handCount); keep their hand large "
        "and convert it to damage. Energy-coherent {W} line.",
        # Snorunt(103,Basic{W}) -> Mega Froslass ex(861,Stage1{W}); generic {W}
        # support all confirmed. 36 non-energy + 24 Basic {W} Energy = 60.
        "deck_counts": {
            103: 4,    # Snorunt (basic; evolves to Mega Froslass ex)
            861: 4,    # Mega Froslass ex (hand-size scaler)
            1121: 4,   # Ultra Ball
            1223: 4,   # Harlequin (supporter)
            1237: 4,   # Lucian (supporter)
            1197: 4,   # Xerosic's Machinations (supporter)
            1103: 4,   # Meddling Memo (item)
            1163: 4,   # Powerglass (item)
            1262: 4,   # Surfing Beach (stadium)
            ENERGY_ID: 24,  # Basic {W} Energy
        },
    },
    {
        "branch_id": "chaos_v6_durant_mill",
        "seam_id": "chaos.mill_resource_destruction",
        "archetype": "chaos",
        "hypothesis": "Durant ex is a Basic {G} attacker/mill engine; pair its "
        "Vengeful Crush with energy/hand denial so brittle bots lose key pieces or "
        "deck out. Energy-coherent {G} build, all confirmed ids.",
        # Durant ex(198,Basic{G}); disruption items + supporters confirmed.
        # 32 non-energy + 28 Basic {G} Energy (id 1) = 60.
        "deck_counts": {
            198: 4,    # Durant ex (basic attacker + Sudden Shearing mill ability)
            1121: 4,   # Ultra Ball
            1120: 4,   # Crushing Hammer (energy denial)
            1149: 4,   # Energy Swatter (energy denial)
            1087: 4,   # Hand Trimmer (hand denial)
            1103: 4,   # Meddling Memo (item)
            1213: 4,   # Judge (hand disruption)
            1197: 4,   # Xerosic's Machinations (supporter)
            1: 28,     # Basic {G} Energy
        },
    },
]

# Still BLOCKED in Pass 6: bench-bloat punisher. Accompanying Flute (1091) is
# confirmed, but the bench-COUNT-scaling attackers in this archetype --
# Zoroark(615<-Zorua), Gengar(1059<-Haunter<-Gastly), Incineroar ex(79<-Torracat
# <-Litten) -- all need evolution-basic ids that are NOT confirmed, and the only
# confirmed Basic alternatives (Teal Mask Ogerpon 95 {G}, Zeraora 956 {L}) have
# no confirmed bench-count-scaling attack. Building it would require either
# inventing evolution-basic ids or fabricating a bench-scaling mechanic.
PASS6_CHAOS_BLOCKED: list[dict] = [
    {
        "branch_id": "chaos_v6_bench_bloat_punisher",
        "seam_id": "chaos.bench_bloat_punisher",
        "archetype": "chaos",
        "hypothesis": "Crowd the opponent bench with Accompanying Flute (benchCount "
        "is now observable), then punish bench size with bench-scaling attackers.",
        "core_card_ids": [1091, 615, 1059, 79, 95, 956],
        "blocked_reason": "Accompanying Flute (1091) and the win-condition metric "
        "(opp benchCount) are confirmed/observable, but every bench-COUNT-scaling "
        "attacker in this archetype is an evolution whose basic is unconfirmed "
        "(Zoroark<-Zorua, Gengar<-Haunter<-Gastly, Incineroar ex<-Torracat<-Litten);"
        " the only confirmed Basics (Ogerpon 95, Zeraora 956) have no confirmed "
        "bench-scaling attack. Cannot build without inventing ids or fabricating "
        "the scaling mechanic.",
    },
]


# ---------------------------------------------------------------------------
# Pass 5: replay-informed, BOARD-AWARE candidates.
#
# Honesty note (important): the Pass-4 override hook only mutates keyword/option
# -type weight dicts, and the keyword scorer only ever sees the *option* dict
# ({area,index,type}) — never the card identity, which lives in
# current.players[me].hand[index].id / select.deck[index].id. So card-name
# weights are effectively inert for card-pick prompts. Pass 5 therefore injects
# a real board-aware scoring layer (`render_p5_block`) that resolves each
# option's card id via (area,index) against the live observation and reads board
# state (active/bench ids) + deckCount, then ADDS a delta to the base score.
# It is fully exception-wrapped (never raises, falls back to the base score) and
# does not touch the select=None deck-return path or index validation. All card
# ids below are confirmed in data/cards/EN_Card_Data.csv (see
# pass4_id_confirmation.json); none are invented. Whether these policies help is
# left to local evaluation — they are candidates, not assumptions.
#
# All Pass-5 candidates are combos over the v2 control deck (deck_energy_trim_
# light) so the ONLY variable vs the v2 anchor is the board-aware policy.
# ---------------------------------------------------------------------------

_V2_DECK_REF = "deck_energy_trim_light"

PASS5_COMBO_SPECS: list[dict] = [
    {
        "branch_id": "pass5_control_v2_anchor",
        "seam_id": "archetype.baseline_exploit",
        "archetype": "baseline_exploit",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": "Exact v2 control (v2 deck, no policy override) anchors the "
        "Pass 5 board-aware batch and confirms the harness reproduces the v2 "
        "baseline as a ~50% mirror.",
        "required": True,
    },
    {
        "branch_id": "policy_effect_resolution_v2",
        "seam_id": "policy.effect_resolution_targeting",
        "archetype": "consistency_engine",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": "Board-aware effect resolution: on discard prompts, protect "
        "setup pieces (Snover 722 / Mega Abomasnow ex 723 / Kyogre 721) that are "
        "not yet in play and steer the discard toward spare Basic {W} Energy (3); "
        "on search-to-hand prompts, fetch the missing engine/attacker. Directly "
        "targets the replay failures (Secret Box discarded Snover; Ultra Ball "
        "discarded Mega Abomasnow).",
        "p5_rules": {
            "discard_avoid_ids": [722, 723, 721],
            "discard_avoid_weight": -300,
            "discard_prefer_ids": [3],
            "discard_prefer_weight": 150,
            "search_prefer_ids": [722, 723, 721, 1121, 1145, 1092],
            "search_prefer_weight": 90,
        },
        "required": True,
    },
    {
        "branch_id": "policy_ultra_ball_v2",
        "seam_id": "policy.ultra_ball_discard_and_search",
        "archetype": "consistency_engine",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": "Ultra Ball (1121) board-aware resolution: when paying the "
        "Ultra Ball discard cost, prefer discarding spare energy over the "
        "Snover/Mega/Kyogre line that is not yet on board, then fetch the missing "
        "attacker/evolution piece (Snover first, then Mega Abomasnow, Kyogre).",
        "p5_rules": {
            "discard_avoid_ids": [722, 723, 721],
            "discard_avoid_weight": -300,
            "discard_prefer_ids": [3],
            "discard_prefer_weight": 150,
            "search_prefer_ids": [722, 723, 721],
            "search_prefer_weight": 90,
            "search_snover_before_mega": True,
            "snover_first_bonus": 70,
            "mega_without_snover_penalty": -70,
        },
        "required": True,
    },
    {
        "branch_id": "policy_secret_box_v2",
        "seam_id": "policy.secret_box_mode_selection",
        "archetype": "consistency_engine",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": "Secret Box (1092) board-aware resolution: never discard the "
        "Snover/Mega/Kyogre line to pay a cost when it is not on board (the exact "
        "step-11 replay bug), and fetch a coherent engine package (Ultra Ball, "
        "Mega Signal, the Snover line) on the to-hand side.",
        "p5_rules": {
            "discard_avoid_ids": [722, 723, 721],
            "discard_avoid_weight": -400,
            "discard_prefer_ids": [3],
            "discard_prefer_weight": 150,
            "search_prefer_ids": [1121, 1145, 722, 723, 721],
            "search_prefer_weight": 85,
        },
        "required": True,
    },
    {
        "branch_id": "policy_mega_signal_v2",
        "seam_id": "policy.mega_signal_evolution_search",
        "archetype": "setup_evolution",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": "Mega Signal (1145) line-coherence: only fetch Mega Abomasnow "
        "ex (723) when its Snover (722) basic is already on board; otherwise prefer "
        "fetching Snover first so the evolution line is not stranded (the step-17 "
        "replay failure: Mega fetched with no Snover line).",
        "p5_rules": {
            "search_prefer_ids": [722, 723],
            "search_prefer_weight": 60,
            "search_snover_before_mega": True,
            "snover_first_bonus": 90,
            "mega_without_snover_penalty": -120,
        },
        "required": True,
    },
    {
        "branch_id": "policy_deckout_guard_v1",
        "seam_id": "policy.deckout_awareness",
        "archetype": "tempo_control",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": "Deckout awareness: when the player's own deckCount is at or "
        "below a threshold, penalize further search-to-hand draws so the deck is "
        "not burned down into a self-inflicted deck-out loss (the seat-0 replay "
        "loss). Reads deckCount from the live observation.",
        "p5_rules": {
            "deckout_threshold": 8,
            "deckout_search_penalty": -180,
        },
        "required": True,
    },
    {
        "branch_id": "combo_effect_resolution_v2__deckout_guard",
        "seam_id": "combo.effect_resolution_deckout",
        "archetype": "consistency_engine",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": "Combine board-aware effect resolution (protect setup, fetch "
        "the missing line) with deckout awareness (stop over-searching when the "
        "deck runs low) to test whether the two replay-derived fixes compound.",
        "p5_rules": {
            "discard_avoid_ids": [722, 723, 721],
            "discard_avoid_weight": -300,
            "discard_prefer_ids": [3],
            "discard_prefer_weight": 150,
            "search_prefer_ids": [722, 723, 721, 1121, 1145, 1092],
            "search_prefer_weight": 90,
            "search_snover_before_mega": True,
            "snover_first_bonus": 70,
            "mega_without_snover_penalty": -70,
            "deckout_threshold": 8,
            "deckout_search_penalty": -180,
        },
        "required": True,
    },
    {
        "branch_id": "policy_setup_snover_active",
        "seam_id": "policy.setup_active_choice",
        "archetype": "setup_evolution",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": "Opening setup: prefer placing Snover (722) during opening "
        "placement prompts so the Mega Abomasnow ex evolution line starts on "
        "board. Reads the option's resolved card id during placement contexts.",
        "p5_rules": {
            "setup_contexts": [1, 2],
            "setup_prefer_ids": [722],
            "setup_prefer_weight": 80,
        },
        "required": True,
    },
    {
        "branch_id": "policy_setup_kyogre_active",
        "seam_id": "policy.setup_active_choice",
        "archetype": "setup_evolution",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": "Opening setup: prefer placing Kyogre (721) during opening "
        "placement prompts as a standalone basic attacker that does not depend on "
        "an evolution line being assembled first.",
        "p5_rules": {
            "setup_contexts": [1, 2],
            "setup_prefer_ids": [721],
            "setup_prefer_weight": 80,
        },
        "required": True,
    },
    {
        "branch_id": "policy_setup_hybrid",
        "seam_id": "policy.setup_active_choice",
        "archetype": "setup_evolution",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": "Opening setup (hybrid): prefer the Snover (722) line first "
        "but also value Kyogre (721) during placement, so the opening keeps both "
        "the evolution line and a standalone attacker available.",
        "p5_rules": {
            "setup_contexts": [1, 2],
            "setup_prefer_ids": [722, 721],
            "setup_prefer_weight": 60,
        },
        "required": True,
    },
]


# ---------------------------------------------------------------------------
# Pass 6 policy candidates (v3): Pass-5 board-aware scoring PLUS a decline
# layer (render_p6_block) that can return [] on dead/unsafe prompts when an
# empty selection is legal (minCount == 0). The decline layer is the only thing
# that lets the agent fix the "fetch a Mega with no Snover line" (step 17) and
# "search the deck down into a deck-out" (step 112) replay failures, which pure
# re-weighting (Pass 5) cannot express. All ids are confirmed in data/cards
# (Snover 722, Mega Abomasnow ex 723, Kyogre 721, Basic {W} Energy 3); none are
# invented. Every candidate is a combo over the v2 control deck so the only
# variable vs the anchor is the injected policy. Whether these help is left to
# local evaluation -- they are candidates, not assumptions.
# ---------------------------------------------------------------------------

PASS6_COMBO_SPECS: list[dict] = [
    {
        "branch_id": "pass6_control_v2_anchor",
        "seam_id": "archetype.baseline_exploit",
        "archetype": "baseline_exploit",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": "Exact v2 control (v2 deck, no policy override) anchors the "
        "Pass 6 batch and confirms the harness reproduces the v2 baseline as a "
        "~50% mirror.",
        "required": True,
    },
    {
        "branch_id": "policy_effect_resolution_v3",
        "seam_id": "policy.effect_resolution_targeting",
        "archetype": "consistency_engine",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": "Effect resolution v3 = Pass-5 board-aware re-weighting "
        "(protect Snover 722 / Mega Abomasnow ex 723 / Kyogre 721 on discard, "
        "discard spare Basic {W} Energy 3, fetch the missing line, Snover before "
        "Mega) PLUS a decline layer: when a Mega Signal search offers only Mega "
        "Abomasnow ex (723) and no Snover (722) is on board, decline rather than "
        "strand the evolution line (the step-17 replay failure).",
        "p5_rules": {
            "discard_avoid_ids": [722, 723, 721],
            "discard_avoid_weight": -300,
            "discard_prefer_ids": [3],
            "discard_prefer_weight": 150,
            "search_prefer_ids": [722, 723, 721, 1121, 1145, 1092],
            "search_prefer_weight": 90,
            "search_snover_before_mega": True,
            "snover_first_bonus": 70,
            "mega_without_snover_penalty": -70,
        },
        "p6_rules": {
            "decline_mega_signal_no_snover": True,
        },
        "required": True,
    },
    {
        "branch_id": "policy_secret_box_safety_v1",
        "seam_id": "policy.secret_box_mode_selection",
        "archetype": "consistency_engine",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": "Secret Box (1092) safety: on optional discard-to-pay "
        "prompts, never discard the Snover/Mega/Kyogre line when it is not yet on "
        "board (the step-11 replay bug), steering the discard to spare Basic {W} "
        "Energy (3) instead. Note: when the prompt is forced (minCount equals the "
        "option count) no choice exists, so this only changes optional discards.",
        "p5_rules": {
            "discard_avoid_ids": [722, 723, 721],
            "discard_avoid_weight": -400,
            "discard_prefer_ids": [3],
            "discard_prefer_weight": 150,
        },
        "required": True,
    },
    {
        "branch_id": "policy_deckout_guard_v2",
        "seam_id": "policy.deckout_awareness",
        "archetype": "tempo_control",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": "Deckout guard v2: when the player's own deckCount is at or "
        "below the threshold, decline optional search-to-hand prompts entirely "
        "(not merely penalize them) so the deck is not burned into a self-inflicted "
        "deck-out loss (the step-112 replay loss). Reads deckCount from the live "
        "observation; only declines when minCount == 0.",
        "p5_rules": {
            "deckout_threshold": 8,
            "deckout_search_penalty": -180,
        },
        "p6_rules": {
            "deckout_decline_threshold": 8,
        },
        "required": True,
    },
    {
        "branch_id": "policy_attachment_targeting_v1",
        "seam_id": "policy.energy_attachment_targeting",
        "archetype": "tempo_control",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": "Attachment targeting: bias energy-attachment prompts toward "
        "attaching to an active/attacker rather than passing, and prefer Basic {W} "
        "Energy (3) onto the board. Keyword/option-type re-weighting only -- precise "
        "'attach to next-turn attacker' needs board state the option dict does not "
        "carry, so this is an approximation.",
        "overrides": {
            "option_type_scores": {8: 40},
            "positive": {"attach": 90, "energy": 70, "active": 35},
        },
        "required": True,
    },
    {
        "branch_id": "combo_effect_resolution_v3__deckout_guard_v2",
        "seam_id": "combo.effect_resolution_deckout",
        "archetype": "consistency_engine",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": "Combine effect resolution v3 (protect setup, fetch the "
        "missing line, decline dead Mega fetches) with deckout guard v2 (decline "
        "optional searches when the deck runs low) to test whether the two "
        "replay-derived decline fixes compound.",
        "p5_rules": {
            "discard_avoid_ids": [722, 723, 721],
            "discard_avoid_weight": -300,
            "discard_prefer_ids": [3],
            "discard_prefer_weight": 150,
            "search_prefer_ids": [722, 723, 721, 1121, 1145, 1092],
            "search_prefer_weight": 90,
            "search_snover_before_mega": True,
            "snover_first_bonus": 70,
            "mega_without_snover_penalty": -70,
            "deckout_threshold": 8,
            "deckout_search_penalty": -180,
        },
        "p6_rules": {
            "decline_mega_signal_no_snover": True,
            "deckout_decline_threshold": 8,
        },
        "required": True,
    },
    {
        "branch_id": "combo_effect_resolution_v3__secret_box_safety",
        "seam_id": "combo.effect_resolution_secret_box",
        "archetype": "consistency_engine",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": "Combine effect resolution v3 with the stronger Secret Box "
        "discard-safety weight to test whether harder protection of the setup line "
        "on discard prompts compounds with the decline-dead-Mega-fetch fix.",
        "p5_rules": {
            "discard_avoid_ids": [722, 723, 721],
            "discard_avoid_weight": -400,
            "discard_prefer_ids": [3],
            "discard_prefer_weight": 150,
            "search_prefer_ids": [722, 723, 721, 1121, 1145, 1092],
            "search_prefer_weight": 90,
            "search_snover_before_mega": True,
            "snover_first_bonus": 70,
            "mega_without_snover_penalty": -70,
        },
        "p6_rules": {
            "decline_mega_signal_no_snover": True,
        },
        "required": True,
    },
    {
        "branch_id": "combo_full_v3",
        "seam_id": "combo.full_v3",
        "archetype": "consistency_engine",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": "Full v3 stack: board-aware effect resolution + Secret Box "
        "discard safety + deckout decline + attachment-targeting re-weighting, to "
        "test the maximal replay-derived policy bundle against the v2 anchor.",
        "overrides": {
            "option_type_scores": {8: 40},
            "positive": {"attach": 90, "energy": 70, "active": 35},
        },
        "p5_rules": {
            "discard_avoid_ids": [722, 723, 721],
            "discard_avoid_weight": -400,
            "discard_prefer_ids": [3],
            "discard_prefer_weight": 150,
            "search_prefer_ids": [722, 723, 721, 1121, 1145, 1092],
            "search_prefer_weight": 90,
            "search_snover_before_mega": True,
            "snover_first_bonus": 70,
            "mega_without_snover_penalty": -70,
            "deckout_threshold": 8,
            "deckout_search_penalty": -180,
        },
        "p6_rules": {
            "decline_mega_signal_no_snover": True,
            "deckout_decline_threshold": 8,
        },
        "required": True,
    },
]


# ---------------------------------------------------------------------------
# Pass 8: fixture-first effect-safety candidates (board-aware selection rewrite)
#
# All candidates are combos over the v2 control deck so the ONLY variable vs the
# pass8 anchor is the injected p8_rules block (render_p8_block). They are
# self-contained: each carries its merged ``p8_rules`` inline (no policy_refs),
# so the 4 "combo" candidates are simply unions of the 4 single-rule guards.
# Promotion is gated on the HARD replay fixtures (see scripts/run_pass8_fixture_gate.py).
# ---------------------------------------------------------------------------

PASS8_COMBO_SPECS: list[dict] = [
    {
        "branch_id": "pass8_control_v2_anchor",
        "seam_id": "archetype.baseline_exploit",
        "archetype": "baseline_exploit",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": (
            "Exact v2 control deck with no effect-safety override; anchors the "
            "Pass 8 batch and re-confirms the v2 control reproduces. Expected to "
            "FAIL the hard fixture gate (it is the unpatched failure regime)."
        ),
        "required": True,
    },
    {
        "branch_id": "policy_secret_box_play_guard_v1",
        "seam_id": "policy.secret_box_mode_selection",
        "archetype": "effect_safety",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": (
            "Secret Box to-hand should not fetch an orphan Mega Signal (1145) "
            "when no Snover line is on board. The literal play-time decline is a "
            "documented non-extractable seam; this enforces the resolvable half."
        ),
        "p8_rules": {"search_avoid_orphan_mega_signal": True},
        "required": True,
    },
    {
        "branch_id": "policy_mega_signal_line_guard_v1",
        "seam_id": "policy.line_coherence",
        "archetype": "effect_safety",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": (
            "Decline Mega Signal when every target is Mega Abomasnow ex (723) and "
            "no Snover (722) is on board, and avoid fetching an orphan Mega in "
            "ordinary searches. Fixes step-17 orphan-Mega failure."
        ),
        "p8_rules": {
            "decline_mega_signal_no_snover": True,
            "search_avoid_orphan_evolution": True,
        },
        "required": True,
    },
    {
        "branch_id": "policy_deckout_guard_v2_p8",
        "seam_id": "policy.deckout_awareness",
        "archetype": "effect_safety",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": (
            "Decline an optional ctx-7 search/draw when own deckCount <= 8 so the "
            "agent never thins itself into a deckout loss. Fixes step-112."
        ),
        "p8_rules": {"deckout_decline_threshold": 8},
        "required": True,
    },
    {
        "branch_id": "policy_to_hand_role_priority_v1",
        "seam_id": "policy.to_hand_role_priority",
        "archetype": "effect_safety",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": (
            "When paying a discard cost, discard plain Basic W Energy before any "
            "setup Pokemon (721/722/723); when searching to hand, prefer the "
            "missing Snover/Kyogre basics over orphan evolutions. Fixes step-28."
        ),
        "p8_rules": {
            "discard_protect_setup": True,
            "search_avoid_orphan_evolution": True,
            "search_avoid_orphan_mega_signal": True,
        },
        "required": True,
    },
    {
        "branch_id": "combo_safety_core_v3",
        "seam_id": "policy.line_coherence",
        "archetype": "effect_safety",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": (
            "Mega-signal line guard + deckout guard: covers the two highest-value "
            "hard fixtures (orphan Mega and deckout) in one block."
        ),
        "p8_rules": {
            "decline_mega_signal_no_snover": True,
            "search_avoid_orphan_evolution": True,
            "deckout_decline_threshold": 8,
        },
        "required": True,
    },
    {
        "branch_id": "combo_discard_safe__deckout_v3",
        "seam_id": "policy.to_hand_role_priority",
        "archetype": "effect_safety",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": (
            "ToHand role priority (discard-protect + search-avoid-orphan) + "
            "deckout guard: covers the Ultra-Ball discard hard fixture plus the "
            "deckout hard fixture."
        ),
        "p8_rules": {
            "discard_protect_setup": True,
            "search_avoid_orphan_evolution": True,
            "search_avoid_orphan_mega_signal": True,
            "deckout_decline_threshold": 8,
        },
        "required": True,
    },
    {
        "branch_id": "combo_play_guard__mega_signal_v3",
        "seam_id": "policy.secret_box_mode_selection",
        "archetype": "effect_safety",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": (
            "Secret Box play guard + Mega-signal line guard: the two "
            "Secret-Box/Mega-Signal coherence guards together."
        ),
        "p8_rules": {
            "search_avoid_orphan_mega_signal": True,
            "decline_mega_signal_no_snover": True,
            "search_avoid_orphan_evolution": True,
        },
        "required": True,
    },
    {
        "branch_id": "combo_full_safety_v3",
        "seam_id": "policy.effect_resolution_targeting",
        "archetype": "effect_safety",
        "policy_refs": [],
        "deck_ref": _V2_DECK_REF,
        "hypothesis": (
            "Lead candidate: ALL four effect-safety guards merged. Designed to "
            "pass every HARD replay fixture (Ultra-Ball discard, Mega orphan, "
            "deckout) and every advisory preference at once."
        ),
        "p8_rules": {
            "discard_protect_setup": True,
            "search_avoid_orphan_evolution": True,
            "search_avoid_orphan_mega_signal": True,
            "decline_mega_signal_no_snover": True,
            "deckout_decline_threshold": 8,
        },
        "required": True,
    },
]


# ---------------------------------------------------------------------------
# Pass 8: deck-neighborhood candidates around the Secret Box risk.
#
# All deltas are ROOT-relative and INCLUDE the v2 deltas ({3:-4, 721:+2,
# 1121:+2}) so the result is "v2 plus one swap". Buildable variants are in
# PASS8_DECK_SPECS; copy-limit / availability violations are recorded honestly in
# PASS8_DECK_BLOCKED (never silently dropped). The two existing Pass-6 swaps
# (no-Secret-Box -> Powerglass / Mega Signal) are reused by plan_pass8_decks
# rather than re-declared. v2 counts: Water(3)x29, Kyogre(721)x4, Snover(722)x4,
# Mega Abomasnow ex(723)x4, Secret Box(1092)x1, Ultra Ball(1121)x4, Mega
# Signal(1145)x2, Powerglass(1163)x2, Petrel(1219)x4, Lillie(1227)x4,
# Surfing Beach(1262)x2.
# ---------------------------------------------------------------------------

PASS8_DECK_SPECS: list[dict] = [
    {
        "branch_id": "deck_v2_no_secret_box__water_energy",
        "seam_id": "deck.secret_box_swap",
        "archetype": "consistency_engine",
        "hypothesis": "Cut the lone Secret Box (1092) for a 30th Water Energy (3) "
        "to test whether raw energy density beats the one-shot Secret Box toolbox "
        "over the v2 control.",
        "deltas": {ENERGY_ID: -3, 721: +2, 1121: +2, 1092: -1},
    },
    {
        "branch_id": "deck_v2_minus_lillie__mega_signal",
        "seam_id": "deck.lillie_swap",
        "archetype": "consistency_engine",
        "hypothesis": "Trim one Lillie (1227, baseline x4) for a 3rd Mega Signal "
        "(1145) to bias toward fetching the Snover -> Mega Abomasnow ex line at the "
        "cost of one draw supporter, keeping the Secret Box.",
        "deltas": {ENERGY_ID: -4, 721: +2, 1121: +2, 1227: -1, 1145: +1},
    },
    {
        "branch_id": "deck_v2_minus_petrel__mega_signal",
        "seam_id": "deck.petrel_swap",
        "archetype": "consistency_engine",
        "hypothesis": "Trim one Team Rocket's Petrel (1219, baseline x4) for a 3rd "
        "Mega Signal (1145) to test more line-fetching versus the fourth disruption "
        "supporter, keeping the Secret Box.",
        "deltas": {ENERGY_ID: -4, 721: +2, 1121: +2, 1219: -1, 1145: +1},
    },
    {
        "branch_id": "deck_v2_secret_box_kept__less_draw",
        "seam_id": "deck.draw_trim",
        "archetype": "tempo_control",
        "hypothesis": "Keep the Secret Box but trim one Lillie (1227) for a 30th "
        "Water Energy (3) to test whether the toolbox is better served by fewer "
        "all-in draw resets and a steadier energy base.",
        "deltas": {ENERGY_ID: -3, 721: +2, 1121: +2, 1227: -1},
    },
]


# Deck-neighborhood candidates that CANNOT be built legally — surfaced honestly.
PASS8_DECK_BLOCKED: list[dict] = [
    {
        "branch_id": "deck_v2_no_secret_box__lillie",
        "seam_id": "deck.secret_box_swap",
        "archetype": "consistency_engine",
        "hypothesis": "Cut the lone Secret Box (1092) for a 5th Lillie (1227) to "
        "maximize draw-reset consistency.",
        "deltas": {ENERGY_ID: -4, 721: +2, 1121: +2, 1092: -1, 1227: +1},
        "blocked_reason": "Lillie (1227) is already at the 4-copy limit in the v2 "
        "deck; adding a 5th to replace Secret Box would exceed the TCG 4-copy rule. "
        "Recorded for completeness; not generated.",
    },
]


# Pass 8 deck x policy combo: the Secret Box play-guard policy over a
# no-Secret-Box deck, to confirm the guard is harmless (or helpful) once the
# card it most directly governs is gone.
PASS8_DECK_COMBO_SPECS: list[dict] = [
    {
        "branch_id": "combo_deck_no_secret_box__secret_box_play_guard",
        "seam_id": "policy.secret_box_mode_selection",
        "archetype": "effect_safety",
        "policy_refs": [],
        "deck_ref": "deck_v2_no_secret_box__mega_signal",
        "hypothesis": "Run the Secret Box play-guard (avoid fetching an orphan Mega "
        "Signal with no Snover line) over the no-Secret-Box / +Mega Signal deck to "
        "test the deck x policy interaction at the Mega Signal line.",
        "p8_rules": {"search_avoid_orphan_mega_signal": True},
        "required": True,
    },
]


# ---------------------------------------------------------------------------
# Override rendering / injection
# ---------------------------------------------------------------------------

def render_override_block(branch_id: str, seam_id: str, overrides: dict) -> str:
    """Render the append-only override block for a policy candidate."""
    lines = [f"\n# === EXPERIMENT OVERRIDE: {branch_id} (seam={seam_id}) ==="]
    if not overrides:
        lines.append("# (no overrides: exact v1 control copy)")
    if overrides.get("option_type_scores"):
        lines.append(f"_OPTION_TYPE_SCORES.update({_fmt(overrides['option_type_scores'])})")
    if overrides.get("attack_id_bonus") is not None:
        lines.append(f"_ATTACK_ID_BONUS = {int(overrides['attack_id_bonus'])}")
    if overrides.get("positive"):
        lines.append(f"_POSITIVE.update({_fmt(overrides['positive'])})")
    if overrides.get("negative"):
        lines.append(f"_NEGATIVE.update({_fmt(overrides['negative'])})")
    lines.append("# === END OVERRIDE ===\n")
    return "\n".join(lines)


def _fmt(d: dict) -> str:
    # Deterministic, valid-Python dict literal with int keys preserved.
    items = ", ".join(f"{k!r}: {v!r}" for k, v in d.items())
    return "{" + items + "}"


def render_p5_block(branch_id: str, seam_id: str, rules: dict) -> str:
    """Render the Pass-5 board-aware scoring override block.

    The block resolves each option's card id via (area,index) against the live
    observation and reads board state (active/bench ids) + deckCount, then ADDS
    a per-option delta to the base score. It is fully exception-wrapped so it
    never raises and falls back to the base score, and it does not touch the
    select=None deck-return path or index validation in the host agent.
    """
    rules_lit = repr(dict(rules))
    return f'''
# === PASS5 BOARD-AWARE OVERRIDE: {branch_id} (seam={seam_id}) ===
# Resolves option card ids via (area,index) and reads board state + deckCount,
# then ADDS a delta to the base score. Never raises (falls back to base score).
_P5_RULES = {rules_lit}
_P5_BASE_SCORE = _score_option


def _p5_me(obs):
    try:
        cur = obs.get("current")
        me = cur.get("yourIndex")
        players = cur.get("players")
        if isinstance(players, list) and isinstance(me, int) and 0 <= me < len(players):
            return players[me]
    except Exception:
        return None
    return None


def _p5_resolve_card_id(option, obs):
    try:
        if not isinstance(option, dict):
            return None
        area = option.get("area")
        index = option.get("index")
        if not isinstance(index, int) or isinstance(index, bool):
            return None
        sel = obs.get("select") if isinstance(obs, dict) else None
        if area == 1 and isinstance(sel, dict):
            deck = sel.get("deck")
            if isinstance(deck, list) and 0 <= index < len(deck):
                c = deck[index]
                return c.get("id") if isinstance(c, dict) else None
        if area == 2:
            p = _p5_me(obs)
            hand = p.get("hand") if isinstance(p, dict) else None
            if isinstance(hand, list) and 0 <= index < len(hand):
                c = hand[index]
                return c.get("id") if isinstance(c, dict) else None
    except Exception:
        return None
    return None


def _p5_board_ids(obs):
    ids = []
    try:
        p = _p5_me(obs) or {{}}
        for slot in ("active", "bench"):
            for e in p.get(slot) or []:
                if isinstance(e, dict) and isinstance(e.get("id"), int):
                    ids.append(e["id"])
    except Exception:
        return ids
    return ids


def _p5_deck_count(obs):
    try:
        p = _p5_me(obs)
        dc = p.get("deckCount") if isinstance(p, dict) else None
        return dc if isinstance(dc, int) and not isinstance(dc, bool) else None
    except Exception:
        return None


def _p5_delta(option, obs):
    d = 0
    try:
        R = _P5_RULES
        sel = obs.get("select") if isinstance(obs, dict) else None
        ctx = sel.get("context") if isinstance(sel, dict) else None
        cid = _p5_resolve_card_id(option, obs)
        board = _p5_board_ids(obs)
        # Discard prompt (context 8): protect setup pieces not yet in play and
        # steer the discard toward spare basic energy instead.
        if ctx == 8 and cid is not None:
            if cid in R.get("discard_avoid_ids", ()) and cid not in board:
                d += R.get("discard_avoid_weight", 0)
            if cid in R.get("discard_prefer_ids", ()):
                d += R.get("discard_prefer_weight", 0)
        # Search-to-hand prompt (context 7): fetch the missing engine/attacker.
        if ctx == 7 and cid is not None:
            if cid in R.get("search_prefer_ids", ()):
                d += R.get("search_prefer_weight", 0)
            if R.get("search_snover_before_mega"):
                if cid == 722 and 722 not in board:
                    d += R.get("snover_first_bonus", 0)
                if cid == 723 and 722 not in board:
                    d += R.get("mega_without_snover_penalty", 0)
        # Deckout guard: when the deck is short, stop over-searching/drawing.
        if ctx == 7:
            thr = R.get("deckout_threshold")
            dc = _p5_deck_count(obs)
            if isinstance(thr, int) and isinstance(dc, int) and dc <= thr:
                d += R.get("deckout_search_penalty", 0)
        # Opening setup placement (contexts 1/2): choose the intended starter.
        if ctx in R.get("setup_contexts", ()) and cid is not None:
            if cid in R.get("setup_prefer_ids", ()):
                d += R.get("setup_prefer_weight", 0)
    except Exception:
        return 0
    return d


def _p5_score(option, idx, obs):
    base = _P5_BASE_SCORE(option, idx, obs)
    try:
        return base + _p5_delta(option, obs)
    except Exception:
        return base


_score_option = _p5_score
# === END PASS5 OVERRIDE ===
'''


def render_p6_block(branch_id: str, seam_id: str, rules: dict) -> str:
    """Render the Pass-6 board-aware *decline* override block.

    The Pass-5 layer can only re-weight options; it cannot make the agent skip a
    prompt. Several replay failures (fetching a Mega with no Snover line on
    board; over-searching when the deck is nearly empty) are only fixable by
    *declining* — returning an empty selection when ``minCount == 0`` makes that
    legal. This block wraps the host ``_embedded_agent`` so that, when a decline
    rule fires on an own-observation-only condition, it returns ``[]`` instead of
    picking a dead option; otherwise it defers to the original embedded policy
    (which still carries any Pass-5 scoring). It never raises (falls back to the
    original embedded policy) and never touches the deck-return path. All card
    ids are confirmed in data/cards (Snover 722, Mega Abomasnow ex 723).
    """
    rules_lit = repr(dict(rules))
    return f'''
# === PASS6 DECLINE OVERRIDE: {branch_id} (seam={seam_id}) ===
# Wraps _embedded_agent: declines (returns []) on own-observation decline rules
# when minCount == 0; otherwise defers to the original embedded policy. Reads
# only the candidate's own board/deckCount + the option card ids it is offered.
_P6_RULES = {rules_lit}
_P6_ORIG_EMBEDDED = _embedded_agent


def _p6_me(obs):
    try:
        cur = obs.get("current")
        me = cur.get("yourIndex")
        players = cur.get("players")
        if isinstance(players, list) and isinstance(me, int) and 0 <= me < len(players):
            return players[me]
    except Exception:
        return None
    return None


def _p6_resolve_card_id(option, obs):
    try:
        if not isinstance(option, dict):
            return None
        area = option.get("area")
        index = option.get("index")
        if not isinstance(index, int) or isinstance(index, bool):
            return None
        sel = obs.get("select") if isinstance(obs, dict) else None
        if area == 1 and isinstance(sel, dict):
            deck = sel.get("deck")
            if isinstance(deck, list) and 0 <= index < len(deck):
                c = deck[index]
                return c.get("id") if isinstance(c, dict) else None
        if area == 2:
            p = _p6_me(obs)
            hand = p.get("hand") if isinstance(p, dict) else None
            if isinstance(hand, list) and 0 <= index < len(hand):
                c = hand[index]
                return c.get("id") if isinstance(c, dict) else None
    except Exception:
        return None
    return None


def _p6_board_ids(obs):
    ids = []
    try:
        p = _p6_me(obs) or {{}}
        for slot in ("active", "bench"):
            for e in p.get(slot) or []:
                if isinstance(e, dict) and isinstance(e.get("id"), int):
                    ids.append(e["id"])
    except Exception:
        return ids
    return ids


def _p6_deck_count(obs):
    try:
        p = _p6_me(obs)
        dc = p.get("deckCount") if isinstance(p, dict) else None
        return dc if isinstance(dc, int) and not isinstance(dc, bool) else None
    except Exception:
        return None


def _p6_should_decline(obs):
    try:
        R = _P6_RULES
        sel = _get_select(obs)
        if not isinstance(sel, dict):
            return False
        options = _get_options(sel)
        if not options:
            return False
        mn, mx = _get_min_max_count(sel, len(options))
        # Only ever decline when an empty selection is legal.
        if mn != 0 or mx <= 0:
            return False
        ctx = sel.get("context")
        # Deckout guard: stop searching/drawing when the deck is at/below the
        # threshold so the agent does not burn itself into a deck-out.
        thr = R.get("deckout_decline_threshold")
        if ctx == 7 and isinstance(thr, int):
            dc = _p6_deck_count(obs)
            if isinstance(dc, int) and dc <= thr:
                return True
        # Mega Signal line coherence: if every offered target is Mega Abomasnow
        # ex (723) and no Snover (722) is on board to evolve from, the fetch is
        # dead -- decline rather than strand the evolution line.
        if ctx == 7 and R.get("decline_mega_signal_no_snover"):
            board = _p6_board_ids(obs)
            cids = [_p6_resolve_card_id(o, obs) for o in options]
            cids = [c for c in cids if c is not None]
            if cids and all(c == 723 for c in cids) and 722 not in board:
                return True
    except Exception:
        return False
    return False


def _p6_embedded(obs):
    try:
        if _p6_should_decline(obs):
            return []
    except Exception:
        pass
    return _P6_ORIG_EMBEDDED(obs)


_embedded_agent = _p6_embedded
# === END PASS6 OVERRIDE ===
'''


def render_p8_block(branch_id: str, seam_id: str, rules: dict) -> str:
    """Render the Pass-8 board-aware *effect-safety* override block.

    Where Pass-5 can only re-weight and Pass-6 can only decline, several replay
    failures need an actual *selection rewrite*: discarding plain Basic {{W}}
    Energy instead of a setup Pokemon to pay a cost (Ultra Ball), or fetching the
    missing Snover/Kyogre basic instead of an orphan Mega / Mega Signal. This
    block wraps the host ``_embedded_agent`` and, for own-observation-only
    conditions, returns a safe selection; otherwise it defers to the original
    embedded policy. Every returned selection is run through the host
    ``_validate_action`` so it is always legal. It never raises (falls back to
    the original embedded policy) and never touches the deck-return path. All
    card ids are confirmed in data/cards/EN_Card_Data.csv (Basic {{W}} Energy 3,
    Kyogre 721, Snover 722, Mega Abomasnow ex 723, Mega Signal 1145).

    Rule keys (all optional, all boolean unless noted):
      deckout_decline_threshold   int: decline ctx-7 search/draw when own
                                  deckCount <= threshold (minCount 0 only).
      decline_mega_signal_no_snover: decline ctx-7 when every offered target is
                                  Mega Abomasnow ex (723) and no Snover (722) is
                                  on board.
      search_avoid_orphan_evolution: in ctx-7 search-to-hand, avoid fetching
                                  Mega Abomasnow ex (723) when no Snover line is
                                  on board; prefer the Snover/Kyogre basics.
      search_avoid_orphan_mega_signal: in ctx-7 search-to-hand, avoid fetching
                                  Mega Signal (1145) when no Snover line exists.
      discard_protect_setup       in ctx-8 discard cost, never discard a setup
                                  Pokemon (721/722/723) when enough non-setup
                                  fodder (Basic {{W}} Energy first) can cover the
                                  whole cost.
    """
    rules_lit = repr(dict(rules))
    return f'''
# === PASS8 EFFECT-SAFETY OVERRIDE: {branch_id} (seam={seam_id}) ===
# Wraps _embedded_agent: returns a safe, validated selection for own-observation
# effect-resolution rules (decline / discard-protect / search-avoid-orphan);
# otherwise defers to the original embedded policy. Reads only the candidate's
# own board / deckCount / hand and the offered option card ids.
_P8_RULES = {rules_lit}
_P8_ORIG_EMBEDDED = _embedded_agent
_P8_SNOVER = 722
_P8_KYOGRE = 721
_P8_MEGA = 723
_P8_MEGA_SIGNAL = 1145
_P8_ENERGY = 3
_P8_SETUP = (721, 722, 723)


def _p8_me(obs):
    try:
        cur = obs.get("current")
        me = cur.get("yourIndex")
        players = cur.get("players")
        if isinstance(players, list) and isinstance(me, int) and 0 <= me < len(players):
            return players[me]
    except Exception:
        return None
    return None


def _p8_resolve(option, obs):
    try:
        if not isinstance(option, dict):
            return None
        area = option.get("area")
        index = option.get("index")
        if not isinstance(index, int) or isinstance(index, bool):
            return None
        sel = obs.get("select") if isinstance(obs, dict) else None
        if area == 1 and isinstance(sel, dict):
            deck = sel.get("deck")
            if isinstance(deck, list) and 0 <= index < len(deck):
                c = deck[index]
                return c.get("id") if isinstance(c, dict) else None
        if area == 2:
            p = _p8_me(obs)
            hand = p.get("hand") if isinstance(p, dict) else None
            if isinstance(hand, list) and 0 <= index < len(hand):
                c = hand[index]
                return c.get("id") if isinstance(c, dict) else None
    except Exception:
        return None
    return None


def _p8_board_ids(obs):
    ids = []
    try:
        p = _p8_me(obs) or {{}}
        for slot in ("active", "bench"):
            for e in p.get(slot) or []:
                if isinstance(e, dict) and isinstance(e.get("id"), int):
                    ids.append(e["id"])
    except Exception:
        return ids
    return ids


def _p8_deck_count(obs):
    try:
        p = _p8_me(obs)
        dc = p.get("deckCount") if isinstance(p, dict) else None
        return dc if isinstance(dc, int) and not isinstance(dc, bool) else None
    except Exception:
        return None


def _p8_should_decline(obs, sel, options, mn, mx):
    try:
        R = _P8_RULES
        if mn != 0 or mx <= 0:
            return False
        ctx = sel.get("context")
        thr = R.get("deckout_decline_threshold")
        if ctx == 7 and isinstance(thr, int) and not isinstance(thr, bool):
            dc = _p8_deck_count(obs)
            if isinstance(dc, int) and dc <= thr:
                return True
        if ctx == 7 and R.get("decline_mega_signal_no_snover"):
            board = _p8_board_ids(obs)
            cids = [_p8_resolve(o, obs) for o in options]
            cids = [c for c in cids if c is not None]
            if cids and all(c == _P8_MEGA for c in cids) and _P8_SNOVER not in board:
                return True
    except Exception:
        return False
    return False


def _p8_discard_pick(obs, sel, options, mn, mx):
    try:
        R = _P8_RULES
        if not R.get("discard_protect_setup"):
            return None
        need = mn if mn > 0 else mx
        if need <= 0:
            return None
        ids = [_p8_resolve(o, obs) for o in options]
        setup_idx = [i for i, c in enumerate(ids) if c in _P8_SETUP]
        if not setup_idx:
            return None
        safe_idx = [i for i, c in enumerate(ids)
                    if c is not None and c not in _P8_SETUP]
        if len(safe_idx) < need:
            return None
        safe_idx.sort(key=lambda i: (0 if ids[i] == _P8_ENERGY else 1, i))
        return sorted(safe_idx[:need])
    except Exception:
        return None


def _p8_search_pick(obs, sel, options, mn, mx):
    try:
        R = _P8_RULES
        board = _p8_board_ids(obs)
        no_snover = _P8_SNOVER not in board
        avoid = set()
        if R.get("search_avoid_orphan_evolution") and no_snover:
            avoid.add(_P8_MEGA)
        if R.get("search_avoid_orphan_mega_signal") and no_snover:
            avoid.add(_P8_MEGA_SIGNAL)
        if not avoid:
            return None
        ids = [_p8_resolve(o, obs) for o in options]
        bad = [i for i, c in enumerate(ids) if c in avoid]
        if not bad:
            return None
        good = [i for i, c in enumerate(ids)
                if c is not None and c not in avoid]
        if good:
            pref = {{_P8_SNOVER: 0, _P8_KYOGRE: 1}}
            good.sort(key=lambda i: (pref.get(ids[i], 2), i))
            need = mn if mn > 0 else 1
            need = min(need, mx, len(good))
            return sorted(good[:need]) if need > 0 else []
        if mn == 0:
            return []
        return None
    except Exception:
        return None


def _p8_embedded(obs):
    try:
        sel = _get_select(obs)
        if isinstance(sel, dict):
            options = _get_options(sel)
            if options:
                mn, mx = _get_min_max_count(sel, len(options))
                if _p8_should_decline(obs, sel, options, mn, mx):
                    return []
                ctx = sel.get("context")
                if ctx == 8:
                    pick = _p8_discard_pick(obs, sel, options, mn, mx)
                    if pick is not None:
                        return _validate_action(pick, len(options), mn, mx)
                if ctx == 7:
                    pick = _p8_search_pick(obs, sel, options, mn, mx)
                    if pick is not None:
                        return _validate_action(pick, len(options), mn, mx)
    except Exception:
        pass
    return _P8_ORIG_EMBEDDED(obs)


_embedded_agent = _p8_embedded
# === END PASS8 OVERRIDE ===
'''


def inject_override(baseline_src: str, block: str) -> str:
    """Insert ``block`` just before the ``if __name__`` guard (or at EOF)."""
    idx = baseline_src.find(_INJECT_ANCHOR)
    if idx == -1:
        return baseline_src.rstrip() + "\n" + block + "\n"
    return baseline_src[:idx] + block + "\n\n" + baseline_src[idx:]


# ---------------------------------------------------------------------------
# Deck delta application
# ---------------------------------------------------------------------------

def apply_deck_deltas(baseline_ids: list[int], deltas: dict) -> list[int]:
    """Apply signed per-id deltas to a 60-card list; return a new sorted list."""
    counts = Counter(baseline_ids)
    for cid, delta in deltas.items():
        counts[int(cid)] = counts.get(int(cid), 0) + int(delta)
    out: list[int] = []
    for cid in sorted(counts):
        n = counts[cid]
        if n < 0:
            raise ValueError(f"delta drove card {cid} below zero ({n})")
        out.extend([cid] * n)
    return out


def _illegal_copy_counts(card_ids: list[int], card_db=None, max_copies: int = 4) -> dict:
    """Return {card_id: count} for non-basic-energy cards exceeding max_copies."""
    over: dict[int, int] = {}
    for cid, n in Counter(card_ids).items():
        if n <= max_copies:
            continue
        if _is_basic_energy(cid, card_db):
            continue
        over[cid] = n
    return over


def _is_basic_energy(cid: int, card_db=None) -> bool:
    """True for any "Basic {X} Energy" card (unlimited copies allowed).

    The shared card_db reports ``is_energy=False`` for basic energy, so detect it
    by name instead. ``ENERGY_ID`` (the deck's {W} energy) is always recognised.
    """
    if cid == ENERGY_ID:
        return True
    if card_db is not None:
        try:
            name = str(card_db.basic_features(cid).get("name", "")).lower()
            if name.startswith("basic ") and name.endswith(" energy"):
                return True
        except Exception:
            pass
    return False


def deck_diff(baseline_ids: list[int], new_ids: list[int]) -> dict:
    base, new = Counter(baseline_ids), Counter(new_ids)
    diff = {}
    for cid in sorted(set(base) | set(new)):
        d = new.get(cid, 0) - base.get(cid, 0)
        if d:
            diff[str(cid)] = {
                "name": CARD_NAMES.get(cid, f"card {cid}"),
                "from": base.get(cid, 0),
                "to": new.get(cid, 0),
                "delta": d,
            }
    return diff


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------

def generate_policy_candidate(
    spec: dict,
    baseline_main: str | Path,
    baseline_deck: str | Path,
    runs_root: str | Path,
    ts: str | None = None,
) -> Branch:
    """Write a policy candidate (baseline + override) into a fresh run dir."""
    baseline_src = Path(baseline_main).read_text(encoding="utf-8")
    block = render_override_block(spec["branch_id"], spec["seam_id"], spec["overrides"])
    candidate_src = inject_override(baseline_src, block)

    run_dir = make_run_dir(spec["branch_id"], root=runs_root, ts=ts)
    (run_dir / "main.py").write_text(candidate_src, encoding="utf-8")
    # Policy candidates reuse the exact baseline deck.
    deck_ids = load_deck(baseline_deck)
    save_deck(run_dir / "deck.csv", deck_ids)

    branch = Branch(
        branch_id=spec["branch_id"],
        seam_id=spec["seam_id"],
        family="policy" if spec["seam_id"].startswith("policy") else "archetype",
        kind="control" if not spec["overrides"] else "policy",
        archetype=spec.get("archetype", ""),
        hypothesis=spec["hypothesis"],
        run_dir=str(run_dir),
        policy_overrides=spec["overrides"],
        policy_diff=spec["overrides"],
        deck_summary={"source": "baseline", "size": len(deck_ids)},
    )
    write_branch_yaml(branch, run_dir)
    return branch


def generate_deck_candidate(
    spec: dict,
    baseline_main: str | Path,
    baseline_deck: str | Path,
    runs_root: str | Path,
    card_db=None,
    ts: str | None = None,
) -> Branch:
    """Write a deck candidate (baseline main + mutated deck) into a run dir."""
    from ..decks.validator import validate_deck

    baseline_ids = load_deck(baseline_deck)
    new_ids = apply_deck_deltas(baseline_ids, spec["deltas"])

    result = validate_deck(new_ids, card_db=card_db)
    if not result.valid:
        raise ValueError(
            f"generated deck for {spec['branch_id']} is invalid: "
            + "; ".join(result.errors)
        )
    # Strict copy-limit enforcement for candidates: the shared validator treats
    # "non-energy card > 4 copies" as a warning (so the baseline's many basic
    # energy never fail), but a generated candidate must NEVER exceed 4 copies of
    # any non-basic-energy card. Hard-fail here so an illegal deck can never be
    # packaged or queued.
    over = _illegal_copy_counts(new_ids, card_db)
    if over:
        raise ValueError(
            f"generated deck for {spec['branch_id']} exceeds 4 copies of "
            "non-energy card(s): "
            + ", ".join(f"{cid}x{n}" for cid, n in over.items())
        )

    run_dir = make_run_dir(spec["branch_id"], root=runs_root, ts=ts)
    # Deck candidates reuse the exact baseline runtime policy.
    Path(run_dir / "main.py").write_text(
        Path(baseline_main).read_text(encoding="utf-8"), encoding="utf-8"
    )
    save_deck(run_dir / "deck.csv", new_ids)

    diff = deck_diff(baseline_ids, new_ids)
    branch = Branch(
        branch_id=spec["branch_id"],
        seam_id=spec["seam_id"],
        family="deck_construction",
        kind="deck",
        archetype=spec.get("archetype", ""),
        hypothesis=spec["hypothesis"],
        run_dir=str(run_dir),
        deck_diff=diff,
        deck_summary={
            "size": len(new_ids),
            "unique": len(set(new_ids)),
            "warnings": result.warnings,
        },
    )
    write_branch_yaml(branch, run_dir)
    return branch


def generate_chaos_candidate(
    spec: dict,
    baseline_main: str | Path,
    runs_root: str | Path,
    card_db=None,
    ts: str | None = None,
) -> Branch:
    """Write a buildable chaos candidate (baseline main + explicit deck) to a run dir.

    Unlike deck candidates, a chaos deck is a FULL replacement expressed as an
    explicit ``spec['deck_counts']`` {card_id: count} multiset (not a delta from
    the root deck). The runtime policy is the unchanged baseline main.py; the
    archetype lives entirely in the deck. The deck is validated and hard-fails on
    any illegal copy count so an illegal chaos list can never be packaged.
    """
    from ..decks.validator import validate_deck

    counts = spec["deck_counts"]
    new_ids: list[int] = []
    for cid in sorted(counts):
        new_ids.extend([cid] * counts[cid])

    result = validate_deck(new_ids, card_db=card_db)
    if not result.valid:
        raise ValueError(
            f"generated chaos deck for {spec['branch_id']} is invalid: "
            + "; ".join(result.errors)
        )
    over = _illegal_copy_counts(new_ids, card_db)
    if over:
        raise ValueError(
            f"generated chaos deck for {spec['branch_id']} exceeds 4 copies of "
            "non-energy card(s): "
            + ", ".join(f"{cid}x{n}" for cid, n in over.items())
        )

    run_dir = make_run_dir(spec["branch_id"], root=runs_root, ts=ts)
    Path(run_dir / "main.py").write_text(
        Path(baseline_main).read_text(encoding="utf-8"), encoding="utf-8"
    )
    save_deck(run_dir / "deck.csv", new_ids)

    branch = Branch(
        branch_id=spec["branch_id"],
        seam_id=spec["seam_id"],
        family="archetype",
        kind="chaos",
        archetype=spec.get("archetype", "chaos"),
        hypothesis=spec["hypothesis"],
        run_dir=str(run_dir),
        deck_summary={
            "size": len(new_ids),
            "unique": len(set(new_ids)),
            "counts": {str(c): n for c, n in counts.items()},
            "warnings": result.warnings,
        },
    )
    write_branch_yaml(branch, run_dir)
    return branch


def _policy_by_id(branch_id: str) -> dict:
    for s in POLICY_SPECS + PASS4_POLICY_SPECS:
        if s["branch_id"] == branch_id:
            return s
    raise KeyError(f"unknown policy spec ref: {branch_id}")


def _deck_by_id(branch_id: str) -> dict:
    for s in DECK_SPECS + PASS6_DECK_SPECS + PASS8_DECK_SPECS:
        if s["branch_id"] == branch_id:
            return s
    raise KeyError(f"unknown deck spec ref: {branch_id}")


def merge_overrides(specs: list[dict]) -> dict:
    """Merge several policy override dicts into one (later refs win on scalars)."""
    merged: dict = {}
    for spec in specs:
        ov = spec.get("overrides", {})
        for key in ("option_type_scores", "positive", "negative"):
            if ov.get(key):
                merged.setdefault(key, {})
                merged[key].update(ov[key])
        if ov.get("attack_id_bonus") is not None:
            merged["attack_id_bonus"] = ov["attack_id_bonus"]
    return merged


def generate_combo_candidate(
    spec: dict,
    baseline_main: str | Path,
    baseline_deck: str | Path,
    runs_root: str | Path,
    card_db=None,
    ts: str | None = None,
) -> Branch:
    """Write a generation-2 combo (policy override block + deck delta) into a run dir.

    The combo references existing single-seam specs by id: it merges their policy
    overrides into one injected block AND applies the referenced deck's deltas, so
    we test the interaction of both changes at once. Same legality gates as the
    deck track (validate + strict 4-copy limit) apply.
    """
    from ..decks.validator import validate_deck

    policy_specs = [_policy_by_id(pid) for pid in spec.get("policy_refs", [])]
    deck_spec = _deck_by_id(spec["deck_ref"])
    # A combo spec may also carry its own inline keyword/option-type overrides
    # (used by Pass-6 attachment-targeting candidates that have no policy_refs).
    merge_specs = list(policy_specs)
    if spec.get("overrides"):
        merge_specs.append(spec)
    overrides = merge_overrides(merge_specs)
    deltas = deck_spec["deltas"]

    baseline_ids = load_deck(baseline_deck)
    new_ids = apply_deck_deltas(baseline_ids, deltas)
    result = validate_deck(new_ids, card_db=card_db)
    if not result.valid:
        raise ValueError(
            f"combo deck for {spec['branch_id']} is invalid: " + "; ".join(result.errors)
        )
    over = _illegal_copy_counts(new_ids, card_db)
    if over:
        raise ValueError(
            f"combo deck for {spec['branch_id']} exceeds 4 copies of non-energy "
            "card(s): " + ", ".join(f"{cid}x{n}" for cid, n in over.items())
        )

    baseline_src = Path(baseline_main).read_text(encoding="utf-8")
    block = render_override_block(spec["branch_id"], spec["seam_id"], overrides)
    candidate_src = inject_override(baseline_src, block)

    # Pass-5 candidates additionally inject a board-aware scoring layer that
    # resolves card ids via (area,index) and reads board state + deckCount.
    p5_rules = spec.get("p5_rules")
    if p5_rules:
        p5_block = render_p5_block(spec["branch_id"], spec["seam_id"], p5_rules)
        candidate_src = inject_override(candidate_src, p5_block)

    # Pass-6 candidates may additionally inject a *decline* layer that wraps the
    # embedded agent so it can skip a dead/unsafe prompt (return []) when an
    # empty selection is legal (minCount == 0).
    p6_rules = spec.get("p6_rules")
    if p6_rules:
        p6_block = render_p6_block(spec["branch_id"], spec["seam_id"], p6_rules)
        candidate_src = inject_override(candidate_src, p6_block)

    # Pass-8 candidates inject a board-aware *effect-safety* layer that can
    # rewrite the selection (decline / discard-protect / search-avoid-orphan),
    # not just re-weight or decline. Applied last so it wraps any earlier layer.
    p8_rules = spec.get("p8_rules")
    if p8_rules:
        p8_block = render_p8_block(spec["branch_id"], spec["seam_id"], p8_rules)
        candidate_src = inject_override(candidate_src, p8_block)

    run_dir = make_run_dir(spec["branch_id"], root=runs_root, ts=ts)
    (run_dir / "main.py").write_text(candidate_src, encoding="utf-8")
    save_deck(run_dir / "deck.csv", new_ids)

    policy_record = dict(overrides)
    if p5_rules:
        policy_record["p5_rules"] = dict(p5_rules)
    if p6_rules:
        policy_record["p6_rules"] = dict(p6_rules)
    if p8_rules:
        policy_record["p8_rules"] = dict(p8_rules)
    diff = deck_diff(baseline_ids, new_ids)
    branch = Branch(
        branch_id=spec["branch_id"],
        seam_id=spec["seam_id"],
        family="combo",
        kind="combo",
        archetype=spec.get("archetype", ""),
        hypothesis=spec["hypothesis"],
        run_dir=str(run_dir),
        policy_overrides=policy_record,
        policy_diff=policy_record,
        deck_diff=diff,
        deck_summary={
            "size": len(new_ids),
            "unique": len(set(new_ids)),
            "warnings": result.warnings,
            "policy_refs": list(spec.get("policy_refs", [])),
            "deck_ref": spec["deck_ref"],
            "board_aware": bool(p5_rules or p8_rules),
        },
        notes=[
            "board-aware p8 effect-safety policy over " + spec["deck_ref"] if p8_rules
            else "board-aware p5 policy over " + spec["deck_ref"] if p5_rules
            else f"combo of {'+'.join(spec.get('policy_refs', []))} x {spec['deck_ref']}"
        ],
    )
    write_branch_yaml(branch, run_dir)
    return branch


# ---------------------------------------------------------------------------
# Planning: which candidates are testable now, ordered by priority
# ---------------------------------------------------------------------------

def plan_candidates(config: ExperimentConfig) -> list[dict]:
    """Return all candidate specs annotated with testability and priority.

    Sorted by priority (desc). Each item: ``{spec, track, seam_id, priority,
    testable, reason}``. Blocked deck experiments are included with
    ``testable=False`` so the report can show them honestly.
    """
    plan: list[dict] = []

    def _annotate(spec: dict, track: str) -> dict:
        seam = config.seam(spec["seam_id"])
        testable, reason = (True, "")
        if seam is None:
            testable, reason = False, f"unknown seam {spec['seam_id']}"
        else:
            testable, reason = config.is_testable(seam)
        return {
            "spec": spec,
            "track": track,
            "seam_id": spec["seam_id"],
            "branch_id": spec["branch_id"],
            "priority": config.priority_for(spec["seam_id"]),
            "testable": testable,
            "reason": reason,
        }

    for spec in POLICY_SPECS:
        plan.append(_annotate(spec, "policy"))
    for spec in DECK_SPECS:
        plan.append(_annotate(spec, "deck"))
    for spec in DECK_BLOCKED:
        item = _annotate(spec, "deck")
        item["testable"] = False
        item["reason"] = spec.get("blocked_reason", item["reason"])
        plan.append(item)

    plan.sort(key=lambda x: (-x["priority"], x["branch_id"]))
    return plan


def plan_generation2(config: ExperimentConfig, include_optional: bool = True) -> list[dict]:
    """Plan the generation-2 confirmation + combination batch.

    Returns ordered ``{spec, track, ...}`` items:
      1. the v1 control exact-copy anchor,
      2. every single-seam spec referenced by a combo (so each combo can be
         compared against its own components in the same batch),
      3. the combo candidates (required combos first, optional after).

    ``track`` is one of ``policy`` / ``deck`` / ``combo``; ``generation`` is set
    so the report can separate gen-1 confirmations from gen-2 combinations.
    """
    combos = [c for c in COMBO_SPECS if include_optional or c.get("required")]

    # Single-seam components referenced by the chosen combos, de-duplicated and
    # kept in a stable order.
    policy_refs: list[str] = []
    deck_refs: list[str] = []
    for c in combos:
        for pid in c.get("policy_refs", []):
            if pid not in policy_refs:
                policy_refs.append(pid)
        if c["deck_ref"] not in deck_refs:
            deck_refs.append(c["deck_ref"])

    def _meta(spec: dict, track: str, generation: int) -> dict:
        return {
            "spec": spec,
            "track": track,
            "seam_id": spec["seam_id"],
            "branch_id": spec["branch_id"],
            "priority": config.priority_for(spec["seam_id"]),
            "testable": True,
            "reason": "",
            "generation": generation,
        }

    plan: list[dict] = []
    # 1. Control anchor (exact v1 copy: empty overrides).
    control = next(s for s in POLICY_SPECS if not s["overrides"])
    plan.append(_meta(control, "policy", 1))
    # 2. Single-seam confirmations.
    for pid in policy_refs:
        plan.append(_meta(_policy_by_id(pid), "policy", 1))
    for did in deck_refs:
        plan.append(_meta(_deck_by_id(did), "deck", 1))
    # 3. Combos (required first, then optional).
    for c in sorted(combos, key=lambda x: (not x.get("required"), x["branch_id"])):
        plan.append(_meta(c, "combo", 2))
    return plan


def plan_pass4(config: ExperimentConfig) -> list[dict]:
    """Plan the Pass 4 replay-derived + chaos scout batch.

    Returns ordered ``{spec, track, ...}`` items, ``generation=4``:
      1. the v2 control anchor (v2 deck, no policy override),
      2. the replay-derived effect-resolution policy candidates (priority desc),
      3. the v2-deck x effect-resolution combo,
      4. the chaos archetype candidates, ALL marked ``testable=False`` with a
         blocked reason (a legal 60-card chaos list cannot be built from the
         confirmed cores without inventing ids).
    """
    def _meta(spec: dict, track: str, testable: bool, reason: str) -> dict:
        return {
            "spec": spec,
            "track": track,
            "seam_id": spec["seam_id"],
            "branch_id": spec["branch_id"],
            "priority": config.priority_for(spec["seam_id"]),
            "testable": testable,
            "reason": reason,
            "generation": 4,
        }

    plan: list[dict] = []
    # 1. v2 control anchor (the combo with empty policy_refs over the v2 deck).
    anchor = next(c for c in PASS4_COMBO_SPECS if c["branch_id"] == "pass4_control_v2_anchor")
    plan.append(_meta(anchor, "combo", True, ""))
    # 2. Effect-resolution policy candidates, highest priority first.
    policy_items = [_meta(s, "policy", True, "") for s in PASS4_POLICY_SPECS]
    policy_items.sort(key=lambda x: (-x["priority"], x["branch_id"]))
    plan.extend(policy_items)
    # 3. The v2-deck x effect-resolution combo.
    for c in PASS4_COMBO_SPECS:
        if c["branch_id"] == "pass4_control_v2_anchor":
            continue
        plan.append(_meta(c, "combo", True, ""))
    # 4. Chaos candidates: blocked, recorded for the report.
    for spec in CHAOS_BLOCKED:
        plan.append(_meta(spec, "chaos", False, spec.get("blocked_reason", "blocked")))
    return plan


def plan_pass5(config: ExperimentConfig) -> list[dict]:
    """Plan the Pass 5 replay-informed, board-aware candidate batch.

    Returns ordered ``{spec, track, ...}`` items, ``generation=5``:
      1. the v2 control anchor (v2 deck, no policy override),
      2. the board-aware replay-informed candidates (effect resolution, Ultra
         Ball / Secret Box / Mega Signal line coherence, deckout guard, the
         combined fix, and the three opening-setup variants), highest priority
         first.

    All candidates are combos over the v2 deck, so the only variable vs the
    anchor is the injected board-aware policy. Chaos archetypes are NOT emitted
    here as blocked candidates: their telemetry-readiness is recorded separately
    by ``scripts/build_chaos_readiness.py`` (Part H).
    """
    def _meta(spec: dict, track: str) -> dict:
        return {
            "spec": spec,
            "track": track,
            "seam_id": spec["seam_id"],
            "branch_id": spec["branch_id"],
            "priority": config.priority_for(spec["seam_id"]),
            "testable": True,
            "reason": "",
            "generation": 5,
        }

    plan: list[dict] = []
    anchor = next(
        c for c in PASS5_COMBO_SPECS if c["branch_id"] == "pass5_control_v2_anchor"
    )
    plan.append(_meta(anchor, "combo"))
    rest = [
        _meta(c, "combo")
        for c in PASS5_COMBO_SPECS
        if c["branch_id"] != "pass5_control_v2_anchor"
    ]
    rest.sort(key=lambda x: (-x["priority"], x["branch_id"]))
    plan.extend(rest)
    return plan


def plan_pass6(config: ExperimentConfig) -> list[dict]:
    """Plan the Pass 6 policy-v3 candidate batch.

    Returns ordered ``{spec, track, ...}`` items, ``generation=6``:
      1. the v2 control anchor (v2 deck, no policy override),
      2. the v3 policy candidates -- Pass-5 board-aware scoring PLUS the decline
         layer (effect resolution v3, secret box safety, deckout guard v2,
         attachment targeting, and the three v3 combos), highest priority first.

    All candidates are combos over the v2 deck so the only variable vs the
    anchor is the injected policy. The decline layer (render_p6_block) is what
    lets the v3 candidates fix the step-17 (Mega-with-no-Snover) and step-112
    (search-into-deckout) replay failures that pure re-weighting cannot.
    """
    def _meta(spec: dict, track: str) -> dict:
        return {
            "spec": spec,
            "track": track,
            "seam_id": spec["seam_id"],
            "branch_id": spec["branch_id"],
            "priority": config.priority_for(spec["seam_id"]),
            "testable": True,
            "reason": "",
            "generation": 6,
        }

    plan: list[dict] = []
    anchor = next(
        c for c in PASS6_COMBO_SPECS if c["branch_id"] == "pass6_control_v2_anchor"
    )
    plan.append(_meta(anchor, "combo"))
    rest = [
        _meta(c, "combo")
        for c in PASS6_COMBO_SPECS
        if c["branch_id"] != "pass6_control_v2_anchor"
    ]
    rest.sort(key=lambda x: (-x["priority"], x["branch_id"]))
    plan.extend(rest)
    return plan


def plan_pass6_decks(config: ExperimentConfig) -> list[dict]:
    """Plan the Pass 6 deck-variant batch (single-card swaps around v2).

    Returns ordered ``{spec, track="deck", ...}`` items, ``generation=6``. The v2
    *exact* deck is NOT emitted here -- it is an integrity anchor. Each variant is
    one confirmed-id single-card swap over the v2 control deck.
    """
    items = [
        {
            "spec": spec,
            "track": "deck",
            "seam_id": spec["seam_id"],
            "branch_id": spec["branch_id"],
            "priority": config.priority_for(spec["seam_id"]),
            "testable": True,
            "reason": "",
            "generation": 6,
        }
        for spec in PASS6_DECK_SPECS
    ]
    items.sort(key=lambda x: (-x["priority"], x["branch_id"]))
    return items


def plan_pass6_chaos(config: ExperimentConfig) -> list[dict]:
    """Plan the Pass 6 chaos batch.

    Returns ordered ``{spec, track="chaos", ...}`` items, ``generation=6``.
    Buildable specs (``PASS6_CHAOS_SPECS``) carry ``testable=True``; the still
    blocked bench-bloat punisher (``PASS6_CHAOS_BLOCKED``) is surfaced with
    ``testable=False`` and its exact ``reason`` so nothing is silently dropped.
    """
    items: list[dict] = []
    for spec in PASS6_CHAOS_SPECS:
        items.append({
            "spec": spec,
            "track": "chaos",
            "seam_id": spec["seam_id"],
            "branch_id": spec["branch_id"],
            "priority": config.priority_for(spec["seam_id"]),
            "testable": True,
            "reason": "",
            "generation": 6,
        })
    for spec in PASS6_CHAOS_BLOCKED:
        items.append({
            "spec": spec,
            "track": "chaos",
            "seam_id": spec["seam_id"],
            "branch_id": spec["branch_id"],
            "priority": config.priority_for(spec["seam_id"]),
            "testable": False,
            "reason": spec["blocked_reason"],
            "generation": 6,
        })
    items.sort(key=lambda x: (not x["testable"], -x["priority"], x["branch_id"]))
    return items


def plan_pass8(config: ExperimentConfig) -> list[dict]:
    """Plan the Pass 8 fixture-first effect-safety candidate batch.

    Returns ordered ``{spec, track, ...}`` items, ``generation=8``:
      1. the v2 control anchor (v2 deck, no effect-safety override),
      2. the eight effect-safety candidates (4 single-rule guards + 4 combos),
         highest priority first.

    All candidates are combos over the v2 deck so the only variable vs the anchor
    is the injected board-aware effect-safety policy (render_p8_block). Promotion
    to any submission queue is gated separately on the HARD replay fixtures.
    """
    def _meta(spec: dict, track: str) -> dict:
        return {
            "spec": spec,
            "track": track,
            "seam_id": spec["seam_id"],
            "branch_id": spec["branch_id"],
            "priority": config.priority_for(spec["seam_id"]),
            "testable": True,
            "reason": "",
            "generation": 8,
        }

    plan: list[dict] = []
    anchor = next(
        c for c in PASS8_COMBO_SPECS if c["branch_id"] == "pass8_control_v2_anchor"
    )
    plan.append(_meta(anchor, "combo"))
    rest = [
        _meta(c, "combo")
        for c in PASS8_COMBO_SPECS
        if c["branch_id"] != "pass8_control_v2_anchor"
    ]
    rest.sort(key=lambda x: (-x["priority"], x["branch_id"]))
    plan.extend(rest)
    return plan


def plan_pass8_decks(config: ExperimentConfig) -> list[dict]:
    """Plan the Pass 8 deck-neighborhood batch around the Secret Box risk.

    Returns ordered items, ``generation=8``:
      * two REUSED Pass-6 swaps (no-Secret-Box -> Powerglass / Mega Signal),
      * four NEW v2 single-swap variants (PASS8_DECK_SPECS), track="deck",
      * one deck x policy combo (Secret Box play-guard over the no-Secret-Box
        deck), track="combo",
      * the blocked copy-limit variant (5th Lillie), ``testable=False`` with its
        exact reason so nothing is silently dropped.
    """
    def _meta(spec: dict, track: str, testable: bool = True,
              reason: str = "") -> dict:
        return {
            "spec": spec,
            "track": track,
            "seam_id": spec["seam_id"],
            "branch_id": spec["branch_id"],
            "priority": config.priority_for(spec["seam_id"]),
            "testable": testable,
            "reason": reason,
            "generation": 8,
        }

    items: list[dict] = []
    # Reuse the two existing Pass-6 Secret-Box swaps rather than re-declaring them.
    for did in ("deck_v2_no_secret_box__mega_signal",
                "deck_v2_no_secret_box__powerglass"):
        items.append(_meta(_deck_by_id(did), "deck"))
    for spec in PASS8_DECK_SPECS:
        items.append(_meta(spec, "deck"))
    for spec in PASS8_DECK_COMBO_SPECS:
        items.append(_meta(spec, "combo"))
    for spec in PASS8_DECK_BLOCKED:
        items.append(_meta(spec, "deck", testable=False,
                           reason=spec.get("blocked_reason", "blocked")))
    items.sort(key=lambda x: (not x["testable"], -x["priority"], x["branch_id"]))
    return items
