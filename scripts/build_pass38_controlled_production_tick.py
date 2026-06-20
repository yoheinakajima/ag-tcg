#!/usr/bin/env python3
"""Pass 38 (Part E) — one controlled production tick (only if safe).

OPS / bounded soak. If NO active lease is held, run a single small bounded
production tick through the real deployment entrypoint:

    scripts/tournament_deployment_tick.py --max-games 3 --max-seconds 240 \
        --storage-backend replit_app_storage --production

then re-pull and verify the push landed: remote ledger advanced by the games
played, the manifest is internally consistent, the push self-verified, and NO
forbidden upload/submit event was introduced. If a lease IS held, we record an
honest lease-held skip and do nothing.

This tick plays INTERNAL self-play games and pushes a verified snapshot to
persistent storage. It performs NO Kaggle upload, NO submit, NO auto-submit, NO
candidate generation, NO root mutation, NO tarball mutation, NO GitHub push.

Writes data/experiments/pass38_controlled_production_tick.{json,md}.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament import sync  # noqa: E402
from ptcg_activegraph.tournament.lease import read_lease  # noqa: E402
from ptcg_activegraph.tournament.storage import get_storage_backend  # noqa: E402

EXP = REPO / "data" / "experiments"
TDIR = REPO / "data" / "tournament"
SMOKE = EXP / "pass37_deployment_tick_smoke.json"
MAX_GAMES = 3
MAX_SECONDS = 240
_FORBIDDEN = {"SubmissionUploaded", "KaggleScoreUpdated"}


def _ledger_state(backend) -> dict:
    """Read-only remote ledger summary (hash + counts)."""
    h = sync.remote_events_hash(backend)
    events = []
    if backend.exists("events.jsonl"):
        events = sync.parse_events_text(backend.read_text("events.jsonl"))
    finished = {(e.get("payload") or {}).get("game_id")
                for e in events if e.get("event_type") == "GameFinished"}
    finished.discard(None)
    return {"hash": h, "events": len(events), "finished": len(finished),
            "forbidden": sorted({e.get("event_type") for e in events} & _FORBIDDEN)}


def main() -> int:
    backend = get_storage_backend(env="production", backend="replit_app_storage")

    lease = read_lease(backend)
    now = time.time()
    lease_active = bool(lease and float(lease.get("expires_at", 0) or 0) > now)

    payload: dict = {
        "pass": "38", "part": "E", "no_upload": True, "upload_performed": False,
        "auto_submit": False, "github_push": False, "candidate_generation": False,
        "backend": backend.name, "max_games": MAX_GAMES, "max_seconds": MAX_SECONDS,
    }

    if lease_active:
        payload.update({
            "ran_tick": False, "skip_reason": "lease_held",
            "lease": {k: lease.get(k) for k in ("owner", "tick_id", "expires_at")},
            "verdict_ok": True,
        })
        _write(payload, skipped=True)
        print(f"controlled tick: SKIPPED (lease held by {lease.get('owner')})")
        return 0

    before = _ledger_state(backend)

    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "tournament_deployment_tick.py"),
         "--max-games", str(MAX_GAMES), "--max-seconds", str(MAX_SECONDS),
         "--storage-backend", "replit_app_storage", "--production"],
        capture_output=True, text=True, cwd=str(REPO), timeout=MAX_SECONDS + 300)

    smoke = json.loads(SMOKE.read_text(encoding="utf-8")) if SMOKE.is_file() else {}
    after = _ledger_state(backend)

    # Re-pull to make the local working dir mirror the post-tick backend and
    # independently confirm the snapshot is faithful.
    repull = sync.pull_state(backend, TDIR)
    ev_path = TDIR / "events.jsonl"
    local_events = sync.parse_events_text(ev_path.read_text(encoding="utf-8")) if ev_path.is_file() else []
    man = json.loads((TDIR / "storage_manifest.json").read_text(encoding="utf-8")) \
        if (TDIR / "storage_manifest.json").is_file() else {}

    games_played = (smoke.get("tick") or {}).get("games_played", smoke.get("games_played", 0)) or 0
    push = smoke.get("push") or {}
    push_verify_ok = (push.get("verify") or {}).get("ok")
    events_grew = after["events"] - before["events"]
    finished_grew = after["finished"] - before["finished"]

    checks = {
        "tick_exit_zero": proc.returncode == 0,
        "tick_status_ok": smoke.get("status") == "ok",
        "push_verify_ok": push_verify_ok is True,
        "no_upload": smoke.get("no_upload") is True,
        "auto_submit_false": smoke.get("auto_submit") is False,
        "root_unchanged": all((smoke.get("root_unchanged") or {}).values())
                          if isinstance(smoke.get("root_unchanged"), dict) else False,
        "ledger_advanced_consistently": (events_grew >= 0 and finished_grew == games_played),
        "no_forbidden_events": not after["forbidden"],
        "manifest_no_upload": man.get("no_upload") is True,
        "manifest_auto_submit_false": man.get("auto_submit") is False,
        "manifest_matches_ledger": man.get("event_count") == len(local_events),
        "repull_hash_matches": after["hash"] == sync.remote_events_hash(backend),
    }
    verdict_ok = all(checks.values())

    payload.update({
        "ran_tick": True,
        "tick_returncode": proc.returncode,
        "tick_status": smoke.get("status"),
        "tick_id": smoke.get("tick_id"),
        "games_played": games_played,
        "stop_reason": (smoke.get("tick") or {}).get("stop_reason"),
        "before": before, "after": after,
        "events_grew": events_grew, "finished_grew": finished_grew,
        "push": {"status": push.get("status"), "drift": push.get("drift"),
                 "verify_ok": push_verify_ok,
                 "uploaded_count": push.get("uploaded_count")},
        "repull": {"count": repull["count"], "bytes": repull["bytes"]},
        "manifest": {"event_count": man.get("event_count"),
                     "no_upload": man.get("no_upload"),
                     "auto_submit": man.get("auto_submit"),
                     "status": man.get("status")},
        "checks": checks,
        "verdict_ok": verdict_ok,
        "tick_stdout_tail": proc.stdout.strip().splitlines()[-6:],
    })
    _write(payload, skipped=False)
    print(f"controlled tick: ran status={smoke.get('status')} rc={proc.returncode} "
          f"games_played={games_played} events {before['events']}->{after['events']} "
          f"finished {before['finished']}->{after['finished']} verdict_ok={verdict_ok}")
    return 0 if verdict_ok else 1


def _write(payload: dict, *, skipped: bool) -> None:
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass38_controlled_production_tick.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    def yn(v):
        return "yes" if v is True else ("no" if v is False else "unverified")

    md = [
        "# Pass 38 — Controlled production tick (Part E)", "",
        "> OPS / bounded soak. Internal self-play only. NO Kaggle upload, NO "
        "submit, NO auto-submit, NO candidate generation, NO root/tarball "
        "mutation, NO GitHub push. Internal diagnostics; NOT a Kaggle leaderboard.",
        "",
        f"- backend: `{payload.get('backend')}`  bounds: max_games="
        f"{payload.get('max_games')}, max_seconds={payload.get('max_seconds')}",
    ]
    if skipped:
        md += [
            f"- ran tick: **no** — skip reason: **{payload.get('skip_reason')}**",
            f"- lease: `{payload.get('lease')}`",
            "- An active lease means another worker is ticking; refusing to start "
            "a second worker is the correct, safe behaviour.",
            f"- verdict ok: **{yn(payload.get('verdict_ok'))}**",
        ]
    else:
        c = payload["checks"]
        md += [
            f"- ran tick: **yes**  status: **{payload.get('tick_status')}**  "
            f"returncode: {payload.get('tick_returncode')}",
            f"- tick_id: `{payload.get('tick_id')}`  games_played: "
            f"**{payload.get('games_played')}**  stop_reason: "
            f"`{payload.get('stop_reason')}`",
            f"- ledger: events {payload['before']['events']} → "
            f"{payload['after']['events']} (+{payload['events_grew']}), "
            f"finished {payload['before']['finished']} → "
            f"{payload['after']['finished']} (+{payload['finished_grew']})",
            f"- push: status `{payload['push']['status']}` drift "
            f"{payload['push']['drift']} verify_ok **{yn(payload['push']['verify_ok'])}** "
            f"uploaded {payload['push']['uploaded_count']}",
            f"- re-pull mirrored {payload['repull']['count']} keys; manifest "
            f"event_count {payload['manifest']['event_count']}", "",
            "## Hard checks",
            f"- tick exit 0: **{yn(c['tick_exit_zero'])}**",
            f"- tick status ok: **{yn(c['tick_status_ok'])}**",
            f"- push self-verify ok: **{yn(c['push_verify_ok'])}**",
            f"- no_upload / auto_submit false: **{yn(c['no_upload'])}** / "
            f"**{yn(c['auto_submit_false'])}**",
            f"- root byte-identical during tick: **{yn(c['root_unchanged'])}**",
            f"- ledger advanced consistently (finished+={payload.get('games_played')}): "
            f"**{yn(c['ledger_advanced_consistently'])}**",
            f"- no forbidden upload/submit events: **{yn(c['no_forbidden_events'])}**",
            f"- manifest no_upload/auto_submit/matches-ledger: "
            f"**{yn(c['manifest_no_upload'])}** / **{yn(c['manifest_auto_submit_false'])}** "
            f"/ **{yn(c['manifest_matches_ledger'])}**",
            f"- re-pull remote hash stable: **{yn(c['repull_hash_matches'])}**", "",
            f"## Verdict: verdict_ok = **{yn(payload.get('verdict_ok'))}**",
        ]
    (EXP / "pass38_controlled_production_tick.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
