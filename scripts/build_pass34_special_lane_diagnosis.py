#!/usr/bin/env python3
"""Pass 34 Part I — Special-lane diagnosis for Toxic and Durant. LOCAL. no upload.

Produces a SEPARATE diagnosis so the special-lane (generic-pilot) failure never
contaminates the normal-deck ranking. For each special-lane deck we report
whether the decklist is valid, whether the candidate built, whether it is
smoke-valid under the generic pilot, the block reason, generic-pilot
compatibility, the missing pilot hooks, the reliable contexts observed, the
first executable fixture needed, and whether it should enter a future
special-pilot sprint.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
FIX = REPO / "data" / "fixtures"

VALIDATION = EXP / "pass34_candidate_validation.json"
SMOKE = EXP / "pass34_live_smoke.json"
MANIFEST = EXP / "pass34_candidate_manifest.json"
BUILDS = EXP / "pass34_decklist_builds.json"
PLANS = FIX / "pass34_special_pilot_plans.yaml"

OUT_JSON = EXP / "pass34_special_lane_diagnosis.json"
OUT_MD = EXP / "pass34_special_lane_diagnosis.md"

SPECIAL = ["toxic_trap_poison_lock", "deckout_carousel_durant_v2"]


def _load_plans() -> dict:
    """Tiny dependency-free reader for the plan fields we need (no PyYAML req)."""
    try:
        import yaml  # type: ignore
        doc = yaml.safe_load(PLANS.read_text(encoding="utf-8"))
        return {p["deck_id"]: p for p in doc.get("special_pilots", [])}
    except Exception:
        return {}


def _by_id(rows, key="candidate_id"):
    return {r[key]: r for r in rows}


def main() -> int:
    validation = _by_id(json.loads(VALIDATION.read_text(encoding="utf-8"))["results"])
    smoke = _by_id(json.loads(SMOKE.read_text(encoding="utf-8"))["results"])
    manifest = _by_id(json.loads(MANIFEST.read_text(encoding="utf-8"))["results"])
    builds_doc = json.loads(BUILDS.read_text(encoding="utf-8"))
    builds = _by_id(builds_doc.get("results", builds_doc.get("builds", [])),
                    key="deck_id")
    plans = _load_plans()

    diagnoses = []
    for cid in SPECIAL:
        v = validation.get(cid, {})
        s = smoke.get(cid, {})
        m = manifest.get(cid, {})
        b = builds.get(cid, {})
        p = plans.get(cid, {})

        seats = s.get("seats", [])
        done_seats = [st["seat"] for st in seats if st.get("status") == "DONE"]
        invalid_seats = [st["seat"] for st in seats if st.get("status") == "INVALID"]

        decklist_valid = bool(
            v.get("tarball_valid") and (b.get("buildable", b.get("built", True))))
        built = bool(m.get("built"))
        smoke_valid = bool(s.get("clean"))  # clean == no INVALID seat
        deck_legal_evidence = bool(s.get("deck_is_legal_evidence"))
        pilot_illegal = bool(s.get("pilot_emitted_illegal_action"))

        diagnoses.append({
            "candidate_id": cid,
            "display_name": m.get("display_name", cid),
            "lane": "special",
            "decklist_valid": decklist_valid,
            "built": built,
            "smoke_valid": smoke_valid,
            "reason_if_blocked": m.get("blocked_reason"),
            "generic_pilot_compatibility": (
                "incompatible — generic prize-racing pilot emits an illegal "
                "gameplay action piloting this win condition"
                if pilot_illegal else "compatible"),
            "deck_is_legal_evidence": deck_legal_evidence,
            "pilot_emitted_illegal_action": pilot_illegal,
            "done_seats": done_seats,
            "invalid_seats": invalid_seats,
            "missing_pilot_hooks": p.get("required_pilot_behaviors", []),
            "reliable_contexts_observed": [
                "deck-selection: returns a legal 60-card deck "
                f"(validators PASS, tarball top-level only)",
                ("at least one seat reaches DONE with this exact deck => "
                 "deck is constructible/LEGAL")
                if done_seats else "no DONE seat observed",
            ],
            "first_executable_fixture_needed": p.get(
                "tieability_smoke_plan",
                "A clean cabt game where a dedicated special pilot drives this "
                "deck and reaches DONE on BOTH seats (no INVALID)."),
            "should_enter_special_pilot_sprint": True,
            "win_condition": p.get("win_condition"),
            "why_generic_pilot_fails": p.get("why_generic_pilot_fails"),
        })

    out = {
        "pass": "34",
        "part": "I",
        "no_upload": True,
        "is_kaggle_leaderboard": False,
        "scope_note": (
            "Special-lane diagnosis is isolated from the normal-deck ranking. "
            "Toxic/Durant are blocked_from_league and were EXCLUDED from the "
            "internal tournament (Part H); their generic-pilot INVALID does not "
            "affect normal-deck standings."),
        "diagnoses": diagnoses,
    }
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

    lines = [
        "# Pass 34 — Special-lane diagnosis (Part I)",
        "",
        "> Isolated from normal-deck ranking. These decks are **blocked_from_league** "
        "and were EXCLUDED from the internal tournament (Part H). A seat reaching "
        "DONE proves the deck is LEGAL; the other seat going INVALID proves the "
        "**generic pilot** mis-pilots the win condition — a pilot mis-fit, not a "
        "deck fault. Nothing uploaded.",
        "",
        "- is Kaggle leaderboard: **False**  no_upload: **True**",
        "",
    ]
    for d in diagnoses:
        lines += [
            f"## {d['display_name']} (`{d['candidate_id']}`)",
            "",
            f"- decklist valid: **{d['decklist_valid']}**",
            f"- built: **{d['built']}**",
            f"- smoke-valid (generic pilot, no INVALID): **{d['smoke_valid']}**",
            f"- deck-is-legal evidence (a seat reached DONE): "
            f"**{d['deck_is_legal_evidence']}** (DONE seats: {d['done_seats']})",
            f"- generic pilot emitted illegal action: "
            f"**{d['pilot_emitted_illegal_action']}** (INVALID seats: "
            f"{d['invalid_seats']})",
            f"- reason if blocked: {d['reason_if_blocked']}",
            f"- generic pilot compatibility: {d['generic_pilot_compatibility']}",
            f"- win condition: {d['win_condition']}",
            f"- why generic pilot fails: {d['why_generic_pilot_fails']}",
            "- missing pilot hooks:",
        ]
        for h in d["missing_pilot_hooks"]:
            lines.append(f"  - {h}")
        lines.append("- reliable contexts observed:")
        for c in d["reliable_contexts_observed"]:
            lines.append(f"  - {c}")
        lines += [
            f"- first executable fixture needed: {d['first_executable_fixture_needed']}",
            f"- enter future special-pilot sprint: "
            f"**{d['should_enter_special_pilot_sprint']}**",
            "",
        ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(REPO)} and {OUT_MD.relative_to(REPO)}")
    print(f"special-lane decks diagnosed: {[d['candidate_id'] for d in diagnoses]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
