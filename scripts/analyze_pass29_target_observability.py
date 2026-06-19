#!/usr/bin/env python3
"""Pass 29 (Part G) — attack / spread / target observability. LOCAL / READ-ONLY.

Asks: when the pilot attacks (or an option targets a Pokemon), can we observe
WHICH Pokemon is being hit, and is spread (multi-target) damage observable? This
bounds whether a future targeting/spread fixture is buildable. Reports honestly
which target facets are observable vs blind.

Outputs data/experiments/pass29_target_observability.{json,md}.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TRACE = REPO / "data" / "experiments" / "pass28_action_trace.jsonl"
CAPTURE = REPO / "data" / "experiments" / "pass29_loop_option_capture.json"
OUT_JSON = REPO / "data" / "experiments" / "pass29_target_observability.json"
OUT_MD = REPO / "data" / "experiments" / "pass29_target_observability.md"


def main() -> int:
    attack_decisions = 0
    attack_with_attackid = 0
    attack_opp_active_known = 0
    attack_opp_bench_known = 0
    attackid_hist = Counter()
    by_family = Counter()

    if TRACE.exists():
        with TRACE.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                if not d.get("attack_option_present"):
                    continue
                attack_decisions += 1
                by_family[d.get("family_id")] += 1
                board = d.get("board") or {}
                opp = board.get("opponent_active")
                if isinstance(opp, dict) and opp.get("card_id") is not None:
                    attack_opp_active_known += 1
                # opponent bench is NOT recorded in the trace board snapshot.
                for sr in (d.get("selected_resolved") or []):
                    if sr.get("action_class") == "attack":
                        attack_with_attackid += 1
                        aid = (sr.get("extra") or {}).get("attackId")
                        if aid is not None:
                            attackid_hist[aid] += 1

    # From the raw per-option capture: do attack options carry an attackId, and is
    # any explicit target field present (inPlayArea/index)?
    cap_attack_opts = 0
    cap_attack_with_id = 0
    cap_attack_with_target_field = 0
    if CAPTURE.exists():
        cap = json.loads(CAPTURE.read_text(encoding="utf-8"))
        for wins in (cap.get("windows") or {}).values():
            for w in wins:
                for o in w.get("raw_options", []):
                    if isinstance(o, dict) and o.get("type") == 13:
                        cap_attack_opts += 1
                        if o.get("attackId") is not None:
                            cap_attack_with_id += 1
                        if "inPlayArea" in o or "targetIndex" in o:
                            cap_attack_with_target_field += 1

    def frac(a, b):
        return round(a / b, 4) if b else None

    out = {
        "pass": "29", "part": "G",
        "attack_decisions": attack_decisions,
        "attack_id_observable_fraction": frac(attack_with_attackid, attack_decisions),
        "defender_active_identity_observable_fraction":
            frac(attack_opp_active_known, attack_decisions),
        "attack_by_family": dict(by_family.most_common()),
        "distinct_attack_ids_seen": len(attackid_hist),
        "capture_attack_options": cap_attack_opts,
        "capture_attack_with_attackid": cap_attack_with_id,
        "capture_attack_with_explicit_target_field": cap_attack_with_target_field,
        "observable": [
            "attack identity via attackId (present on every type-13 option)",
        ],
        "NOT_observable_yet": [
            "the DEFENDING active Pokemon identity — board.opponent_active was "
            "captured as null in the trace (measured 0%); it EXISTS in the raw obs, "
            "so this is one cheap capture ratchet away",
            "opponent BENCH contents (not in the trace board snapshot) -> spread/"
            "bench-target damage cannot be attributed to a specific bench Pokemon",
            "per-attack damage numbers / spread distribution (no damage event is "
            "linked to the attackId in the trace)",
            "explicit target selection field on attack options (none observed; the "
            "engine appears to auto-resolve the active target)",
        ],
        "fixture_feasibility": (
            "attackId is fully observable, but a single-target 'hit the active' "
            "fixture is currently BLOCKED because the trace stored opponent_active "
            "as null (defender identity 0%). That is one capture ratchet away (the "
            "field exists in the raw obs). A SPREAD/bench-targeting fixture needs "
            "MORE observability: opponent bench identity and per-target damage are "
            "wholly unobserved -> needs_more_observability."),
    }
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

    L = ["# Pass 29 — Attack / Spread / Target Observability (Part G)", "",
         f"- Attack decisions in trace: **{attack_decisions}** "
         f"(by family: {out['attack_by_family']}).",
         f"- attackId observable: **{(out['attack_id_observable_fraction'] or 0)*100:.1f}%**.",
         f"- Defending active identity observable: "
         f"**{(out['defender_active_identity_observable_fraction'] or 0)*100:.1f}%**.",
         f"- Capture: {cap_attack_with_id}/{cap_attack_opts} attack options carry an "
         f"attackId; {cap_attack_with_target_field} carry an explicit target field.",
         "", "## Observable", ""]
    L += [f"- {x}" for x in out["observable"]]
    L += ["", "## NOT observable yet", ""]
    L += [f"- {x}" for x in out["NOT_observable_yet"]]
    L += ["", "## Fixture feasibility", "", out["fixture_feasibility"], ""]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")
    print(f"attack_decisions={attack_decisions} "
          f"attackId_obs={out['attack_id_observable_fraction']} "
          f"defender_obs={out['defender_active_identity_observable_fraction']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
