# Pass 5 — Chaos Telemetry Candidate Requirements

Local-only research artifact. For each chaos archetype seam this records the telemetry it would need to *prove* the disruption worked, whether our seat can supply it, the confirmed core card ids, the policy requirements, the blocker, and the minimum metric needed to unblock it.

**Key finding:** every chaos seam's decisive signal lives on the opponent's hidden side (their hand size, deck count, bench, or status). The Pass 5 harness records rich *own-side* telemetry (deck proximity, search/discard contexts, bench/hand high-water marks) but cannot observe the opponent's hidden state, so all five seams remain **blocked** and their unblock metric stays **uncertain**.

Own-side telemetry now recorded by the harness:

- `candidate_won`
- `context_counts`
- `deck_count_last`
- `discard_decisions`
- `low_deck_decisions`
- `max_bench_seen`
- `max_hand_seen`
- `min_deck_count`
- `search_decisions`
- `steps`

## `chaos.hand_avalanche_froslass`

- **Goal:** Keep the opponent's hand large, then scale Mega Froslass ex damage off that hand size.
- **Telemetry availability:** **blocked**
- **Required telemetry:** `opponent_hand_size` (opponent), `own_attack_damage_dealt` (own), `candidate_won` (own)
- **Hidden (opponent-side) signals:** `opponent_hand_size`
- **Own-side proxies available:** `candidate_won`, `steps`
- **Policy requirements:** official_card_csv, chaos_decklist_confirmed
- **Confirmed core card ids:** 861 Mega Froslass ex (MATCH), 103 Snorunt (MATCH), 860 Snorunt (MATCH), 1223 Harlequin (MATCH), 1237 Lucian (MATCH), 1213 Judge (MATCH), 1103 Meddling Memo (MATCH), 1087 Hand Trimmer (MATCH), 1197 Xerosic’s Machinations (MISMATCH)
- **Blockers:**
  - opponent hidden-state telemetry not exposed to our seat: opponent_hand_size
  - own-side signals not recorded by the harness: own_attack_damage_dealt
  - some core card ids are not a clean MATCH against the official card table (see status field)
  - no full legal 60-card chaos decklist confirmed without inventing card ids (chaos_decklist_confirmed gate)
- **Minimum metric to unblock:** uncertain — opponent hand size is hidden from our seat, so the damage-vs-hand-size relationship cannot be measured directly.

## `chaos.bench_bloat_punisher`

- **Goal:** Crowd the opponent's bench with Accompanying Flute, then punish with bench-count-scaling attackers.
- **Telemetry availability:** **blocked**
- **Required telemetry:** `opponent_bench_size` (opponent), `own_attack_damage_dealt` (own), `candidate_won` (own)
- **Hidden (opponent-side) signals:** `opponent_bench_size`
- **Own-side proxies available:** `candidate_won`, `steps`
- **Policy requirements:** official_card_csv, chaos_decklist_confirmed
- **Confirmed core card ids:** 1091 Accompanying Flute (MATCH), 615 Zoroark (MATCH), 430 Team Rocket's Hypno (MATCH), 79 Incineroar ex (MATCH), 95 Teal Mask Ogerpon (MATCH), 956 Zeraora (MATCH), 1059 Gengar (MATCH), 1187 Morty’s Conviction (MISMATCH), 1204 Lisia’s Appeal (MISMATCH)
- **Blockers:**
  - opponent hidden-state telemetry not exposed to our seat: opponent_bench_size
  - own-side signals not recorded by the harness: own_attack_damage_dealt
  - some core card ids are not a clean MATCH against the official card table (see status field)
  - no full legal 60-card chaos decklist confirmed without inventing card ids (chaos_decklist_confirmed gate)
- **Minimum metric to unblock:** uncertain — opponent bench size is hidden from our seat; only our own win/loss is observable.

## `chaos.mill_resource_destruction`

- **Goal:** Disrupt the opponent's deck / hand / energy so a brittle bot loses pieces or decks out.
- **Telemetry availability:** **blocked**
- **Required telemetry:** `opponent_deck_count` (opponent), `opponent_hand_size` (opponent), `candidate_won` (own), `steps` (own)
- **Hidden (opponent-side) signals:** `opponent_deck_count`, `opponent_hand_size`
- **Own-side proxies available:** `candidate_won`, `steps`, `min_deck_count`
- **Policy requirements:** official_card_csv, chaos_decklist_confirmed
- **Confirmed core card ids:** 198 Durant ex (MATCH), 58 Great Tusk (MATCH), 896 Mega Scrafty ex (MATCH), 881 Team Rocket's Diglett (MATCH), 440 Team Rocket's Larvitar (MATCH), 290 Tyranitar (MATCH), 1120 Crushing Hammer (MATCH), 1149 Energy Swatter (MATCH), 1087 Hand Trimmer (MATCH)
- **Blockers:**
  - opponent hidden-state telemetry not exposed to our seat: opponent_deck_count, opponent_hand_size
  - no full legal 60-card chaos decklist confirmed without inventing card ids (chaos_decklist_confirmed gate)
- **Minimum metric to unblock:** uncertain — opponent deck count is hidden; opponent deckout can only be inferred weakly from a long game that we win, not measured directly.

## `chaos.status_confusion_lock`

- **Goal:** Stack Confusion / Burn / Sleep + forced switching so the bot mis-sequences and loses turns.
- **Telemetry availability:** **blocked**
- **Required telemetry:** `opponent_status_flags` (opponent), `opponent_lost_turns` (opponent), `candidate_won` (own)
- **Hidden (opponent-side) signals:** `opponent_status_flags`, `opponent_lost_turns`
- **Own-side proxies available:** `candidate_won`, `steps`
- **Policy requirements:** official_card_csv, chaos_decklist_confirmed
- **Confirmed core card ids:** 1095 Dangerous Laser (MATCH), 1265 Dizzying Valley (MATCH), 813 Mismagius ex (MATCH), 1204 Lisia’s Appeal (MISMATCH), 861 Mega Froslass ex (MATCH), 968 Dachsbun ex (MATCH), 854 Dustox (MATCH), 1243 Perilous Jungle (MATCH)
- **Blockers:**
  - opponent hidden-state telemetry not exposed to our seat: opponent_lost_turns, opponent_status_flags
  - some core card ids are not a clean MATCH against the official card table (see status field)
  - no full legal 60-card chaos decklist confirmed without inventing card ids (chaos_decklist_confirmed gate)
- **Minimum metric to unblock:** uncertain — opponent status conditions and lost turns are hidden from our seat.

## `chaos.vivillon_decidueye_four_card_lock`

- **Goal:** Use Vivillon / Judge to pin the opponent at exactly 4 cards, enabling Decidueye ex's reduced-cost attack.
- **Telemetry availability:** **blocked**
- **Required telemetry:** `opponent_hand_size` (opponent), `own_attack_enabled` (own), `candidate_won` (own)
- **Hidden (opponent-side) signals:** `opponent_hand_size`
- **Own-side proxies available:** `candidate_won`, `steps`, `context_counts`
- **Policy requirements:** official_card_csv, chaos_decklist_confirmed
- **Confirmed core card ids:** 1017 Scatterbug (MATCH), 1018 Spewpa (MATCH), 1019 Vivillon (MATCH), 1020 Rowlet (MATCH), 1021 Dartrix (MATCH), 1022 Decidueye ex (MATCH), 1213 Judge (MATCH), 1261 Forest of Vitality (MATCH), 1231 Dawn (MATCH), 1225 Hilda (MATCH)
- **Blockers:**
  - opponent hidden-state telemetry not exposed to our seat: opponent_hand_size
  - own-side signals not recorded by the harness: own_attack_enabled
  - no full legal 60-card chaos decklist confirmed without inventing card ids (chaos_decklist_confirmed gate)
- **Minimum metric to unblock:** uncertain — the exact-4 opponent hand condition is hidden from our seat, so the lock cannot be confirmed from telemetry.

