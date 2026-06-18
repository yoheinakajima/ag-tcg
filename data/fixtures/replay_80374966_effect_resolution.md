# Pass 8 effect-resolution fixtures — episode 80374966

Deterministic decision fixtures frozen from the replay's true failure regime (effect-resolution safety). Each fixture freezes one real prompt; the candidate `agent(observation)` is graded for **legality** (always hard) and a per-fixture **preference** whose `severity` is `hard` (blocks promotion on failure) or `advisory` (reported only).

- source replay: `data/replays/80374966.json`
- gradeable fixtures: 8 (4 hard, 4 advisory)
- documented (non-gradeable) seams: 1

## Fixtures

### ultra_ball_discard_energy_safe  _(hard)_
- step 28 seat 0 | context `discard` | effect 1121 | min 2 max 2 n 6
- option cards: [723, 3, 1219, 3, 1262, 3]
- board: [721, 721, 721] | deck 33 hand 6
- preference: `avoid_cards` cards=[721, 722, 723]
- nuance: Ultra Ball cost: discard 2 of 6 hand cards. Options include three Basic {W} Energy (3) as safe fodder alongside a setup Mega Abomasnow ex (723). The replay discarded the Mega (a setup piece) while energy fodder was available — the discard that bricked the Snover line. Safe energy discards must be preferred over setup Pokemon.

### ultra_ball_search_missing_basic_or_evolution  _(advisory)_
- step 9 seat 0 | context `search_to_hand` | effect 1121 | min 0 max 1 n 9
- option cards: [722, 721, 723, 723, 722, 722, 721, 722, 723]
- board: [721, 721] | deck 46 hand 3
- preference: `avoid_cards` cards=[723]
- nuance: Ultra Ball search-to-hand with Snover (722) / Kyogre (721) / Mega Abomasnow ex (723) all available and no Snover on board (active Kyogre only). Fetching a Mega with no Snover line to evolve from is a dead draw; the basic Snover/Kyogre line should be taken first. minCount 0 so declining is also legal.

### secret_box_forced_discard_all  _(hard)_
- step 11 seat 0 | context `discard` | effect 1092 | min 3 max 3 n 3
- option cards: [3, 3, 722]
- board: [721, 721] | deck 45 hand 3
- preference: `forced_all`
- nuance: Secret Box discard with minCount == maxCount == n_options == 3: the only legal selection is all three options, so the Snover (722) among them cannot be spared. This is a FORCED discard, classified forced_all / na — NEVER a policy failure. The real 'should Secret Box have been played' seam is a pre-play decision the in-resolution fixtures cannot represent (see secret_box_play_safety).

### secret_box_to_hand_coherent_package  _(advisory)_
- step 12 seat 0 | context `search_to_hand` | effect 1092 | min 0 max 1 n 5
- option cards: [1145, 1145, 1121, 1121, 1121]
- board: [721, 721] | deck 45 hand 0
- preference: `avoid_cards` cards=[1145]
- nuance: Secret Box search-to-hand: options are Mega Signal (1145) and Ultra Ball (1121) with no Snover line on board (active Kyogre) and a healthy deck (45). Mega Signal only advances a Snover line that does not yet exist, so it would set up an orphan Mega; a flexible Ultra Ball is the more coherent pick here. Full coherent-package reasoning (Powerglass when an attacker has no tool; Lillie/Petrel only when deck is healthy; avoid redundant stadium) spans the step 12-15 pick sequence; this fixture grades the orphan-Mega Signal half deterministically.

### mega_signal_no_orphan_mega  _(hard)_
- step 17 seat 0 | context `search_to_hand` | effect 1145 | min 0 max 1 n 3
- option cards: [723, 723, 723]
- board: [721, 721] | deck 41 hand 3
- preference: `decline`
- nuance: Mega Signal search where all three options resolve to Mega Abomasnow ex (723) and no Snover (722) is on the board. Fetching a Mega with no Snover line to evolve from is a dead draw; minCount 0 so the safe play is to decline. The replay took the orphan Mega (flagged fetched_mega_without_snover_line).

### deckout_guard_low_deck  _(hard)_
- step 112 seat 0 | context `search_to_hand` | effect 1219 | min 0 max 1 n 1
- option cards: [1227]
- board: [721, 722, 722, 722] | deck 7 hand 27
- preference: `decline`
- nuance: Team Rocket's Petrel search offered with deckCount 7 (<= 8) — the replayed seat went on to deck out (final deckCount 0). Resolving an optional draw/search this near empty risks self-loss; minCount 0 so the deckout-safe play is to decline. The policy deckout guard escalates this penalty at <=8, <=4 and <=2; the replay provides the deck=7 instance, the tighter thresholds are policy targets (no separate replay frame exists for them).

### setup_active_kyogre_vs_snover__kyogre  _(advisory)_
- step 3 seat 0 | context `choose_active` | effect None | min 1 max 1 n 2
- option cards: [721, 721]
- board: [] | deck 53 hand 7
- preference: `prefer_cards` cards=[721, 722, 723]
- nuance: Initial active choice, seat 0: both legal options are Kyogre (721). The Kyogre line (immediate attack/energy plan) is taken. This is the Kyogre-active variant — any setup-line basic is a valid active; the fixture asserts a correct pick lands on a setup basic, not a single hard-coded answer.

### setup_active_kyogre_vs_snover__snover  _(advisory)_
- step 4 seat 1 | context `choose_active` | effect None | min 1 max 1 n 3
- option cards: [722, 722, 721]
- board: [] | deck 53 hand 7
- preference: `prefer_cards` cards=[721, 722, 723]
- nuance: Initial active choice, seat 1: options are Snover (722) / Snover / Kyogre (721); Snover is taken to lean on evolution support. This is the Snover-active variant — the complement of the Kyogre variant. Both are valid; the fixture asserts the pick is a setup-line basic, not a single hard-coded answer.

### secret_box_play_safety  _(documented)_
- context `main_play_decision` | effect 1092 | **not gradeable** (documented seam)
- nuance: Secret Box PRE-PLAY safety: whether to play Secret Box (1092) at all when fewer than 3 safe discards would remain. This is a main-menu (context 0) decision. In episode 80374966 no context-0 option resolves to a hand card id (play options reference board slots via inPlayArea/inPlayIndex, not a resolvable hand index), so the pre-play choice cannot be frozen as a deterministic graded fixture. Recorded as a documented seam, not a fabricated check. Real downstream evidence of the bad play: the forced step-11 Snover discard (secret_box_forced_discard_all) and the eventual deck-out. The policy guard (policy_secret_box_play_guard_v1) targets this seam at the live decision; if a forced unsafe play occurs it is marked forced_bad/unsafe and never blamed on the discard subprompt.
