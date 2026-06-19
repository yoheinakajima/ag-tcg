# Pass 28 — Core Gameplay Fixture Backlog (Part I)

> Fixtures are PLANNED, not executable: every Pass-28 gap is coupled to the live cabt effect/option engine and cannot be faithfully reduced to a standalone fixture yet. Each item references its trace evidence.

- executable_now: 0  planned: 4

## fx_effect_loop_termination (high, high)
- gap: effect_loop_termination
- source deck: league_mega_venusaur_tank
- source step: pass28_action_trace.jsonl: candidate_id=league_mega_venusaur_tank, select_context in {33,21} (~1957 repeats/game)
- reduced model: a board where an optional/forced effect (context 33, single type-6 option) re-presents indefinitely; agent must reach a terminating choice
- expected behavior: pilot exits the repeated effect within a bounded number of iterations and proceeds to attack
- required resolver support: effect-loop / repeated-context termination policy; ability-activation budget
- executable_now: False
- why blocked: the loop is produced by the live cabt effect engine; a faithful reduced model needs the engine's effect-context state machine, which is not available standalone
- deck scope: deck-specific (venusaur), but termination policy is generic

## fx_mill_deckout_init_legality (high, high (failure) / unknown (whether a legal line exists))
- gap: mill_deckout_unsupported
- source deck: league_durant_deckout_carousel
- source step: pass28_diagnostic_trace.json: durant__self, step 1 INVALID, 0 gameplay decisions
- reduced model: submit the Durant deck and assert the engine reaches a legal turn-1 state (or capture the exact init rejection)
- expected behavior: deck passes engine init and reaches turn 1 so a mill line can be attempted
- required resolver support: engine init-legality diagnostics + a special deckout pilot once init passes
- executable_now: False
- why blocked: the engine rejects at init without surfacing a reason to the agent observation; cannot faithfully reduce the cause without engine-internal validation output
- deck scope: deck-specific (durant)

## fx_ramp_sequencing (medium, medium)
- gap: ramp_sequencing
- source deck: league_mega_gardevoir_psychic_ramp
- source step: pass28_action_trace.jsonl: candidate_id=league_mega_gardevoir_psychic_ramp (low attach + low in_play_action counts)
- reduced model: board with energy in discard and a ramp ability available; agent should use the ability to re-attach
- expected behavior: pilot activates the from-discard ramp before/with attacking to power a bigger attack
- required resolver support: ability-driven energy re-attachment recognition in the option resolver
- executable_now: False
- why blocked: ramp is an ability whose option is not surfaced with resolvable identity; faithful reduction needs the engine's ability-option encoding
- deck scope: deck-specific (gardevoir)

## fx_evolution_sequencing_speed (medium, medium)
- gap: evolution_sequencing_speed
- source deck: league_mega_charizard_x_burst
- source step: pass28_action_trace.jsonl: candidate_id=league_mega_charizard_x_burst, first attack median step 6 / min 4, with a long tail of stalled games (~turn 33)
- reduced model: Stage-2/Mega line in hand/bench; agent should complete the line (Rare Candy if present) by a target turn
- expected behavior: evolution completes earlier so the first attack lands closer to aggro tempo
- required resolver support: evolution-path planning + Rare Candy recognition (play_from_hand identity)
- executable_now: False
- why blocked: Rare Candy / evolution plays are not resolved in the play_from_hand option schema, so the model cannot faithfully represent the sequencing decision yet
- deck scope: partial (Mega/Stage-2 decks)
