# Pass 6 — Chaos Telemetry Candidate Requirements (corrected observability)

  Local-only research artifact. **Pass 6 correction:** the Pass 5 claim that *all*
  opponent state is hidden was too conservative. Verified against replay
  `80374966` (`observation.current.players[i]`), our seat **observes** the
  opponent's **counts** (`handCount`, `deckCount`), **revealed board**
  (`active`/`bench` card ids, `benchMax`), **discard**, **prize count**, and
  **status flags** (asleep/burned/confused/paralyzed/poisoned). Only the
  **contents** of face-down zones stay hidden: opponent `hand` (null while
  `handCount` is real), `deck` (absent — only `deckCount`), and `prize`
  identities (null placeholders; count observable).

  Helper: `src/ptcg_activegraph/experiments/telemetry.py` `read_observation()`.

  **Consequence for chaos seams:** every seam's decisive *policy trigger* lives on
  an observable opponent signal (hand size, bench size, deck count, or status
  flags), so the trigger can now be measured. What remains is (a) for damage-style
  payoffs, the harness records win/loss not per-attack damage, so causation stays a
  win-rate **proxy**, and (b) the **build gate**: a legal 60-card decklist must be
  confirmed from MATCHed card ids (no invented ids) and pass smoke before a seam is
  evaluated. Where that gate is not met, the seam stays blocked with the exact
  reason — no conclusion fabricated.

  Opponent signals now observable: handCount, deckCount, active/bench ids, benchMax, discard, prize count, status flags.
  Opponent signals still hidden: hand contents, deck contents, prize identities, any face-down identity.

  ## `chaos.hand_avalanche_froslass`

- **Goal:** Keep the opponent's hand large, then scale Mega Froslass ex damage off that hand size.
- **Telemetry availability:** **available** (policy trigger observable: true)
- **Observable signals driving the policy:** opponent_hand_size, candidate_won
- **Proxy-only / unrecorded signals:** own_attack_damage_dealt
- **Required telemetry:** opponent_hand_size (opponent, observable=true), own_attack_damage_dealt (own, observable=false), candidate_won (own, observable=true)
- **Policy requirements:** official_card_csv, chaos_decklist_confirmed
- **Confirmed core card ids:** 861 Mega Froslass ex (MATCH), 103 Snorunt (MATCH), 860 Snorunt (MATCH), 1223 Harlequin (MATCH), 1237 Lucian (MATCH), 1213 Judge (MATCH), 1103 Meddling Memo (MATCH), 1087 Hand Trimmer (MATCH), 1197 Xerosic’s Machinations (MISMATCH)
- **Blockers:**
  - payoff-proof signals not recorded by the harness (win/loss proxy only): own_attack_damage_dealt
  - some core card ids are not a clean MATCH against the official card table (see status field)
  - REMAINING BUILD GATE: a legal 60-card decklist must be confirmed (no invented ids) and pass package verify + smoke before this seam can be evaluated
- **Remaining gate:** chaos_decklist_confirmed (legal 60-card list + smoke)
- **Minimum metric to unblock:** trigger is observable: measure win rate vs v2 control while the policy fires on the observable opponent signal (opponent_hand_size). Direct payoff (e.g. damage dealt) is not recorded, so causation stays a win-rate proxy, not a proven mechanism.

## `chaos.bench_bloat_punisher`

- **Goal:** Crowd the opponent's bench with Accompanying Flute, then punish with bench-count-scaling attackers.
- **Telemetry availability:** **available** (policy trigger observable: true)
- **Observable signals driving the policy:** opponent_bench_size, candidate_won
- **Proxy-only / unrecorded signals:** own_attack_damage_dealt
- **Required telemetry:** opponent_bench_size (opponent, observable=true), own_attack_damage_dealt (own, observable=false), candidate_won (own, observable=true)
- **Policy requirements:** official_card_csv, chaos_decklist_confirmed
- **Confirmed core card ids:** 1091 Accompanying Flute (MATCH), 615 Zoroark (MATCH), 430 Team Rocket's Hypno (MATCH), 79 Incineroar ex (MATCH), 95 Teal Mask Ogerpon (MATCH), 956 Zeraora (MATCH), 1059 Gengar (MATCH), 1187 Morty’s Conviction (MISMATCH), 1204 Lisia’s Appeal (MISMATCH)
- **Blockers:**
  - payoff-proof signals not recorded by the harness (win/loss proxy only): own_attack_damage_dealt
  - some core card ids are not a clean MATCH against the official card table (see status field)
  - REMAINING BUILD GATE: a legal 60-card decklist must be confirmed (no invented ids) and pass package verify + smoke before this seam can be evaluated
- **Remaining gate:** chaos_decklist_confirmed (legal 60-card list + smoke)
- **Minimum metric to unblock:** trigger is observable: measure win rate vs v2 control while the policy fires on the observable opponent signal (opponent_bench_size). Direct payoff (e.g. damage dealt) is not recorded, so causation stays a win-rate proxy, not a proven mechanism.

## `chaos.mill_resource_destruction`

- **Goal:** Disrupt the opponent's deck / hand / energy so a brittle bot loses pieces or decks out.
- **Telemetry availability:** **available** (policy trigger observable: true)
- **Observable signals driving the policy:** opponent_deck_count, opponent_hand_size, candidate_won, steps
- **Proxy-only / unrecorded signals:** —
- **Required telemetry:** opponent_deck_count (opponent, observable=true), opponent_hand_size (opponent, observable=true), candidate_won (own, observable=true), steps (own, observable=true)
- **Policy requirements:** official_card_csv, chaos_decklist_confirmed
- **Confirmed core card ids:** 198 Durant ex (MATCH), 58 Great Tusk (MATCH), 896 Mega Scrafty ex (MATCH), 881 Team Rocket's Diglett (MATCH), 440 Team Rocket's Larvitar (MATCH), 290 Tyranitar (MATCH), 1120 Crushing Hammer (MATCH), 1149 Energy Swatter (MATCH), 1087 Hand Trimmer (MATCH)
- **Blockers:**
  - REMAINING BUILD GATE: a legal 60-card decklist must be confirmed (no invented ids) and pass package verify + smoke before this seam can be evaluated
- **Remaining gate:** chaos_decklist_confirmed (legal 60-card list + smoke)
- **Minimum metric to unblock:** trigger is observable: measure win rate vs v2 control while the policy fires on the observable opponent signal (opponent_deck_count, opponent_hand_size). Direct payoff (e.g. damage dealt) is not recorded, so causation stays a win-rate proxy, not a proven mechanism.

## `chaos.status_confusion_lock`

- **Goal:** Stack Confusion / Burn / Sleep + forced switching so the bot mis-sequences and loses turns.
- **Telemetry availability:** **partial** (policy trigger observable: false)
- **Observable signals driving the policy:** opponent_status_flags, candidate_won
- **Proxy-only / unrecorded signals:** opponent_lost_turns
- **Required telemetry:** opponent_status_flags (opponent, observable=true), opponent_lost_turns (opponent, observable=false), candidate_won (own, observable=true)
- **Policy requirements:** official_card_csv, chaos_decklist_confirmed
- **Confirmed core card ids:** 1095 Dangerous Laser (MATCH), 1265 Dizzying Valley (MATCH), 813 Mismagius ex (MATCH), 1204 Lisia’s Appeal (MISMATCH), 861 Mega Froslass ex (MATCH), 968 Dachsbun ex (MATCH), 854 Dustox (MATCH), 1243 Perilous Jungle (MATCH)
- **Blockers:**
  - some opponent-side signals still unavailable: opponent_lost_turns
  - some core card ids are not a clean MATCH against the official card table (see status field)
  - REMAINING BUILD GATE: a legal 60-card decklist must be confirmed (no invented ids) and pass package verify + smoke before this seam can be evaluated
- **Remaining gate:** chaos_decklist_confirmed (legal 60-card list + smoke)
- **Minimum metric to unblock:** uncertain — opponent_lost_turns not observable to our seat.

## `chaos.vivillon_decidueye_four_card_lock`

- **Goal:** Use Vivillon / Judge to pin the opponent at exactly 4 cards, enabling Decidueye ex's reduced-cost attack.
- **Telemetry availability:** **available** (policy trigger observable: true)
- **Observable signals driving the policy:** opponent_hand_size, own_attack_enabled, candidate_won
- **Proxy-only / unrecorded signals:** —
- **Required telemetry:** opponent_hand_size (opponent, observable=true), own_attack_enabled (own, observable=true), candidate_won (own, observable=true)
- **Policy requirements:** official_card_csv, chaos_decklist_confirmed
- **Confirmed core card ids:** 1017 Scatterbug (MATCH), 1018 Spewpa (MATCH), 1019 Vivillon (MATCH), 1020 Rowlet (MATCH), 1021 Dartrix (MATCH), 1022 Decidueye ex (MATCH), 1213 Judge (MATCH), 1261 Forest of Vitality (MATCH), 1231 Dawn (MATCH), 1225 Hilda (MATCH)
- **Blockers:**
  - REMAINING BUILD GATE: a legal 60-card decklist must be confirmed (no invented ids) and pass package verify + smoke before this seam can be evaluated
- **Remaining gate:** chaos_decklist_confirmed (legal 60-card list + smoke)
- **Minimum metric to unblock:** trigger is observable: measure win rate vs v2 control while the policy fires on the observable opponent signal (opponent_hand_size). Direct payoff (e.g. damage dealt) is not recorded, so causation stays a win-rate proxy, not a proven mechanism.

