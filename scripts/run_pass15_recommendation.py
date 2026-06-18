#!/usr/bin/env python3
"""ActiveGraph Pass 15 — metrics + dry-run recommendation (NO upload).

Reads only the lab's own Pass 15 artifacts:
  * ``data/reports/pass15_core_focused_eval.json`` (weighted directional eval)
  * ``data/reports/pass15_live_smoke.json``        (validity smoke)

and derives, per candidate role:
  * aggregate games / W-L-D, crash / timeout / skip counts (validity),
  * weighted directional win rate (copied from the eval ranking),
  * a promotion-gate verdict and a human label.

It then writes a dry-run recommendation queue with ``upload_performed: false``.
This is DIRECTIONAL ONLY: opponents are generic surrogates, not the real Kaggle
opponent policy, and live Kaggle scores were not refreshed (CLI absent). The
queue NEVER uploads — Pass 15 is local-only by mandate.

Outputs:
  * ``data/experiments/pass15_candidate_metrics.json``
  * ``data/experiments/pass15_dry_run_queue.json``

Usage:
    python scripts/run_pass15_recommendation.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FOCUSED = REPO / "data" / "reports" / "pass15_core_focused_eval.json"
SMOKE = REPO / "data" / "reports" / "pass15_live_smoke.json"
METRICS_OUT = REPO / "data" / "experiments" / "pass15_candidate_metrics.json"
QUEUE_OUT = REPO / "data" / "experiments" / "pass15_dry_run_queue.json"
ENTRYPOINT_VALIDATOR = REPO / "scripts" / "validate_candidate_entrypoint.py"
CAND14 = REPO / "data" / "submissions" / "candidates_pass14"
CAND = REPO / "data" / "submissions" / "candidates"

# Promotion gate: a candidate may only be QUEUED for (hypothetical, never
# executed) upload if it clears a real-sample bar AND beats the active control on
# the directional eval. Pass 15's focused eval is intentionally tiny (a
# no-regression signal, not a promotion proof), so this gate is expected to
# reject everything — by design.
MIN_GAMES_FOR_PROMOTION = 20
MAX_DRY_RUN_QUEUE = 1

DISCLAIMER = (
    "Surrogate-based and DIRECTIONAL ONLY. Opponent decks are piloted by a "
    "generic surrogate policy, not the real opponent policy. These results never "
    "equal Kaggle results and are not sufficient to promote or upload a "
    "candidate. Live Kaggle scores could not be refreshed this pass (kaggle CLI "
    "unavailable)."
)


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _entrypoint_ok(tarball: Path) -> bool | None:
    """Run the entrypoint-invariant validator; True/False, or None if unknown."""
    if not (ENTRYPOINT_VALIDATOR.exists() and tarball.exists()):
        return None
    try:
        proc = subprocess.run([sys.executable, str(ENTRYPOINT_VALIDATOR),
                               str(tarball)],
                              capture_output=True, text=True, timeout=180)
        return proc.returncode == 0
    except Exception:  # noqa: BLE001
        return None


def _candidate_tarball(role: str, active_control: str | None) -> Path:
    """Resolve a role name back to its candidate tarball path."""
    if role == "active_control" and active_control:
        return CAND / f"{active_control}.tar.gz"
    return CAND14 / f"{role}.tar.gz"


def _smoke_valid_for(role: str, smoke_rows: list[dict]) -> bool | None:
    """A candidate is smoke-valid iff every smoke matchup mentioning its short
    name has 0 crash / 0 timeout / 0 skip. None when no row mentions it."""
    short = role.replace("core_pilot_water_", "")
    key = "active_control" if role == "active_control" else short
    rows = [m for m in smoke_rows if key in str(m.get("matchup", ""))]
    if not rows:
        return None
    return all(
        int(m.get("crashes") or 0) == 0 and int(m.get("timeouts") or 0) == 0
        and int(m.get("skipped") or 0) == 0
        for m in rows
    )


def _aggregate(matchups: list[dict], role: str) -> dict:
    """Sum W-L-D + validity counts across every subfamily for one role."""
    rows = [m for m in matchups if m.get("role") == role]
    wins = sum(int(m.get("wins") or 0) for m in rows)
    losses = sum(int(m.get("losses") or 0) for m in rows)
    draws = sum(int(m.get("draws") or 0) for m in rows)
    crashes = sum(int(m.get("crashes") or 0) for m in rows)
    timeouts = sum(int(m.get("timeouts") or 0) for m in rows)
    skipped = sum(int(m.get("skipped") or 0) for m in rows)
    games = wins + losses + draws
    return {
        "subfamilies": len(rows),
        "games": games,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "crashes": crashes,
        "timeouts": timeouts,
        "skipped": skipped,
        "raw_win_rate": round(wins / games, 4) if games else None,
    }


def build_metrics(focused: dict, smoke: dict) -> dict:
    matchups = focused.get("matchups") or []
    ranking = {r["role"]: r for r in (focused.get("ranking") or [])}
    active = focused.get("active_control")

    # Validity from the smoke run (0 crash / 0 timeout / 0 skip per matchup).
    smoke_rows = smoke.get("smoke") or []
    smoke_valid = all(
        int(m.get("crashes") or m.get("crash") or 0) == 0
        and int(m.get("timeouts") or m.get("timeout") or 0) == 0
        and int(m.get("skipped") or m.get("skip") or 0) == 0
        for m in smoke_rows
    ) if smoke_rows else None

    ac_weighted = (ranking.get("active_control") or {}).get(
        "weighted_directional_win_rate")

    rows = []
    for role in sorted({m.get("role") for m in matchups if m.get("role")}):
        agg = _aggregate(matchups, role)
        weighted = (ranking.get(role) or {}).get("weighted_directional_win_rate")
        is_control = role == "active_control"
        focused_valid = (agg["crashes"] == 0 and agg["timeouts"] == 0
                         and agg["skipped"] == 0)
        smoke_valid = _smoke_valid_for(role, smoke_rows)
        # A candidate is "valid_live" only if BOTH its focused matchups AND its
        # live-smoke matchups are clean (smoke unknown is treated as not-clean
        # for promotion purposes, but does not by itself flip validity to False).
        valid = focused_valid and (smoke_valid is not False)
        validator = _entrypoint_ok(_candidate_tarball(role, active))
        beats_ac = (weighted is not None and ac_weighted is not None
                    and weighted > ac_weighted) if not is_control else None

        if is_control:
            label = "anchor"
            interp = ("Active control / anchor — the candidate the pilots must "
                      "beat, never itself a promotion target.")
            gate = "n/a"
        elif validator is not True:
            # Fail-closed: a candidate may only be promotable if the entrypoint
            # validator explicitly PASSED. An outright FAIL or an unverifiable
            # result (tarball/validator missing -> None) both block promotion.
            label = "invalid_entrypoint"
            interp = ("Did not PASS the entrypoint-invariant validator "
                      f"(result={validator!r}) — cannot be a promotion target "
                      "regardless of win rate.")
            gate = "fail_validator"
        elif not focused_valid:
            label = "invalid"
            interp = "Failed focused validity (crash/timeout/skip) — cannot promote."
            gate = "fail_validity"
        elif smoke_valid is False:
            label = "invalid_smoke"
            interp = ("Failed live-smoke validity (crash/timeout/skip) — cannot "
                      "promote.")
            gate = "fail_smoke_validity"
        elif agg["games"] < MIN_GAMES_FOR_PROMOTION:
            label = "directional_no_regression"
            interp = (f"Directional no-regression signal only "
                      f"({agg['games']} games < {MIN_GAMES_FOR_PROMOTION} "
                      f"required); not a promotion proof.")
            gate = "insufficient_games"
        elif beats_ac:
            label = "confirmation_promising"
            interp = ("Beats the active control on directional eval at sufficient "
                      "sample, valid entrypoint + clean smoke — candidate for a "
                      "real-sample confirmation pass.")
            gate = "pass"
        else:
            label = "no_edge"
            interp = "Does not beat the active control directionally."
            gate = "fail_no_edge"

        rows.append({
            "candidate": role,
            "role": "active_control" if is_control else "core_pilot",
            "weighted_directional_win_rate": weighted,
            "beats_active_control": beats_ac,
            "promotion_gate": gate,
            "label": label,
            "interpretation": interp,
            "valid_live": valid,
            "focused_valid": focused_valid,
            "smoke_valid": smoke_valid,
            "entrypoint_validator_pass": validator,
            **agg,
        })

    # Promotable rows first, then by weighted WR.
    rows.sort(key=lambda r: (r["promotion_gate"] != "pass",
                             -(r["weighted_directional_win_rate"] or 0)))
    return {
        "pass": "15",
        "disclaimer": DISCLAIMER,
        "generated": datetime.now(timezone.utc).isoformat(),
        "active_control": active,
        "active_control_weighted_directional_win_rate": ac_weighted,
        "smoke_validity_clean": smoke_valid,
        "min_games_for_promotion": MIN_GAMES_FOR_PROMOTION,
        "rows": rows,
    }


def build_queue(metrics: dict) -> dict:
    promotable = [r for r in metrics["rows"]
                  if r["promotion_gate"] == "pass"][:MAX_DRY_RUN_QUEUE]
    if promotable:
        reason = (f"{len(promotable)} candidate(s) cleared the directional "
                  f"promotion gate; queued for a REAL-sample confirmation pass "
                  f"(never auto-uploaded).")
    else:
        reason = (f"No candidate met the promotion gate (>= "
                  f"{MIN_GAMES_FOR_PROMOTION} games, beats the active control, "
                  f"valid live play). Pass 15's focused eval is a small "
                  f"no-regression signal by design, not a promotion proof.")
    return {
        "pass": "15",
        "disclaimer": DISCLAIMER,
        "upload_performed": False,
        "max_dry_run_queue": MAX_DRY_RUN_QUEUE,
        "queued": [
            {"candidate": r["candidate"],
             "weighted_directional_win_rate": r["weighted_directional_win_rate"],
             "games": r["games"], "label": r["label"]}
            for r in promotable
        ],
        "queued_count": len(promotable),
        "reason": reason,
        "note": ("Surrogate eval is directional only; queueing never uploads. "
                 "Pass 15 is LOCAL-ONLY by mandate — NO Kaggle upload, NO GitHub "
                 "push. The dynamic active control remains the best known "
                 "submission."),
    }


def main() -> int:
    focused = _load(FOCUSED)
    smoke = _load(SMOKE)
    if not focused:
        print(f"FAIL: missing {FOCUSED} — run the focused eval first.")
        return 1

    metrics = build_metrics(focused, smoke)
    queue = build_queue(metrics)

    METRICS_OUT.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_OUT.parent.mkdir(parents=True, exist_ok=True)
    METRICS_OUT.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    QUEUE_OUT.write_text(json.dumps(queue, indent=2), encoding="utf-8")

    print("Pass 15 metrics + recommendation written:")
    print(f"  {METRICS_OUT}")
    print(f"  {QUEUE_OUT}")
    print(f"\nupload_performed: {queue['upload_performed']}  "
          f"queued: {queue['queued_count']}")
    for r in metrics["rows"]:
        print(f"  - {r['candidate']:32s} wWR={r['weighted_directional_win_rate']} "
              f"games={r['games']} valid={r['valid_live']} "
              f"gate={r['promotion_gate']} [{r['label']}]")
    print(f"\nReason: {queue['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
