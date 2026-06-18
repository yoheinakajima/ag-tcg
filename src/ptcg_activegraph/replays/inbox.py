"""Append-only replay inbox scanner.

Treats ``data/meta_replays/raw/*.json`` as an inbox of raw Kaggle episode JSONs
whose filenames may be arbitrary numeric names (e.g. ``80503687.json``). The real
``EpisodeId`` is always read from the JSON ``info`` block, never from the
filename. Parsing is defensive: a malformed file yields a ``failed_parse`` entry
rather than crashing the whole ingest.

This module does not move, rename, or rewrite the raw files.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .kaggle_replay import KaggleReplay, _coerce_json

# Team/agent name tokens that identify *our* seat.
OUR_NAME_TOKENS = ("yohei nakajima", "yohei", "theyohei")


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def name_is_ours(name) -> bool:
    if not isinstance(name, str):
        return False
    low = name.strip().lower()
    return any(tok in low for tok in OUR_NAME_TOKENS)


def parse_inbox_file(path: str | Path) -> dict:
    """Parse one raw replay file into a flat metadata entry (no card payloads
    beyond the per-seat submitted deck id lists, which are the meta signal)."""
    path = Path(path)
    entry: dict = {
        "path": str(path),
        "filename": path.name,
        "file_sha256": None,
        "status": "parsed",
        "warnings": [],
        "error": None,
    }
    try:
        entry["file_sha256"] = file_sha256(path)
        raw = _coerce_json(path.read_text(encoding="utf-8"))
        if not raw:
            entry["status"] = "failed_parse"
            entry["error"] = "empty_or_unparseable_json"
            return entry
        r = KaggleReplay(raw=raw, source_path=str(path))
        info = r.info
        agents = [a.get("Name") for a in info.get("Agents", []) if isinstance(a, dict)]
        team_names = info.get("TeamNames") if isinstance(info.get("TeamNames"), list) else []
        decks = r.submitted_decks()
        final = r.final_result()
        statuses = r.statuses
        entry.update({
            "episode_id": r.episode_id,
            "module_version": r.module_version,
            "schema_version": r.schema_version,
            "agents": agents,
            "team_names": team_names,
            "rewards": final["rewards"],
            "statuses": statuses,
            "num_steps": r.num_steps,
            "winner_seat": final["winner_seat"],
            "draw": final["draw"],
            "configuration": {
                "actTimeout": r.act_timeout,
                "episodeSteps": r.episode_steps,
                "runTimeout": r.run_timeout,
            },
            "decks": {str(s): list(ids) for s, ids in decks.items()},
            "our_seats_by_name": [s for s, n in enumerate(agents) if name_is_ours(n)],
        })
        if not decks:
            entry["status"] = "parsed_with_warnings"
            entry["warnings"].append("no submitted decks found in steps")
        elif any(len(v) != 60 for v in decks.values()):
            entry["status"] = "parsed_with_warnings"
            entry["warnings"].append("a submitted deck is not exactly 60 cards")
        if statuses and any(s not in ("DONE", "ACTIVE", "INACTIVE") for s in statuses):
            entry["warnings"].append(f"non-terminal/abnormal status present: {statuses}")
        if not final["rewards"]:
            entry["warnings"].append("no rewards recorded")
    except Exception as exc:  # defensive: one bad file must not kill the inbox
        entry["status"] = "failed_parse"
        entry["error"] = f"{type(exc).__name__}: {exc}"
    return entry


def scan_inbox(raw_dir: str | Path) -> list[dict]:
    """Parse every ``*.json`` in the inbox (skipping ``_`` prefixed helpers)."""
    raw_dir = Path(raw_dir)
    if not raw_dir.exists():
        return []
    return [
        parse_inbox_file(p)
        for p in sorted(raw_dir.glob("*.json"))
        if not p.name.startswith("_")
    ]
