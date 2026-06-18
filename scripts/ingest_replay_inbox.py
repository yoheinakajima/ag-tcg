#!/usr/bin/env python3
"""Ingest the raw replay inbox into the canonical replay registry (Pass 11B).

Pipeline::

    data/meta_replays/raw/*.json
      -> scan (inbox) -> dedup + attribute + classify (registry)
      -> data/meta_replays/decks/<ep>_p{0,1}_deck.csv      (extracted decks)
      -> data/meta_replays/replay_registry.json
      -> data/meta_replays/replay_registry.md
      -> data/meta_replays/replay_inbox_errors.json
      -> data/meta_replays/replay_processing_state.json

Hard rules: never invents a card id; never modifies the raw files; the official
card CSV is read locally (for opponent card *names* only) and never copied into
an output.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.replays import inbox as inbox_mod  # noqa: E402
from ptcg_activegraph.replays import registry as reg_mod  # noqa: E402
from ptcg_activegraph.replays.kaggle_replay import load_replay  # noqa: E402

RAW_DIR = REPO / "data" / "meta_replays" / "raw"
DECKS_DIR = REPO / "data" / "meta_replays" / "decks"
OUT_REG_JSON = REPO / "data" / "meta_replays" / "replay_registry.json"
OUT_REG_MD = REPO / "data" / "meta_replays" / "replay_registry.md"
OUT_ERRORS = REPO / "data" / "meta_replays" / "replay_inbox_errors.json"
OUT_STATE = REPO / "data" / "meta_replays" / "replay_processing_state.json"


def _load_card_names() -> dict[int, str]:
    """Best-effort load of card_id -> name from the local official metadata.

    Used only to label opponent cards in the registry/archetypes. Missing file
    is fine; the classifier falls back to the curated signature names.
    """
    try:
        from ptcg_activegraph.cards.csv_loader import (
            find_card_csv, load_cards_from_csv,
        )
    except Exception:
        return {}
    path = find_card_csv()
    if not path:
        return {}
    names: dict[int, str] = {}
    for rec in load_cards_from_csv(path):
        cid = rec.get("card_id")
        try:
            cid = int(str(cid).strip())
        except (TypeError, ValueError):
            continue
        nm = rec.get("name")
        if nm:
            names[cid] = str(nm).strip()
    return names


def _write_decks(entries: list[dict]) -> list[str]:
    DECKS_DIR.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for entry in entries:
        if entry.get("status") == "failed_parse":
            continue
        episode = entry.get("episode_id")
        for seat, ids in entry.get("decks", {}).items():
            out = DECKS_DIR / f"{episode}_p{seat}_deck.csv"
            out.write_text("\n".join(str(i) for i in ids) + "\n", encoding="utf-8")
            written.append(str(out.relative_to(REPO)))
    return written


def to_markdown(reg: dict) -> str:
    lines = ["# Replay registry (Pass 11B)", ""]
    lines.append(f"- replays in inbox: **{reg['replays_total']}**")
    lines.append(f"- registered (deduplicated): **{reg['replays_registered']}**")
    lines.append(f"- duplicates skipped: **{len(reg['duplicates_skipped'])}**")
    lines.append(f"- parse errors: **{len(reg['errors'])}**")
    lines.append(f"- known own decks: {', '.join(reg['known_own_decks']) or 'none'}")
    lines.append("")
    lines.append("| episode | perspective | our_seat | reward | opponent archetype | confidence |")
    lines.append("|---|---|---|---|---|---|")
    for r in reg["records"]:
        opp = next((s for s in r["seats"] if not s["is_ours"]), None)
        arch = (opp or {}).get("archetype") or {}
        lines.append(
            f"| {r['episode_id']} | {r['perspective']} | {r['our_seat']} | "
            f"{r['our_reward']} | {arch.get('archetype_id', '-')} | "
            f"{arch.get('confidence', '-')} |"
        )
    lines.append("")
    lines.append("## Per-episode detail")
    for r in reg["records"]:
        lines.append(f"### Episode {r['episode_id']} — {r['perspective']}")
        lines.append(f"- file: `{r['filename']}` (sha256 `{(r['file_sha256'] or '')[:12]}…`)")
        lines.append(f"- agents: {r['agents']}, rewards: {r['rewards']}, steps: {r['num_steps']}")
        if r["warnings"]:
            lines.append(f"- warnings: {r['warnings']}")
        for s in r["seats"]:
            fpr = s.get("fingerprint") or {}
            arch = s.get("archetype") or {}
            ours = "ours" if s["is_ours"] else "opponent"
            lines.append(
                f"  - seat {s['seat']} ({ours}, {s['agent']}): deck=`{s['deck_label']}` "
                f"uniq={fpr.get('unique_card_count')} "
                f"archetype={arch.get('archetype_id', '-')}/{arch.get('confidence', '-')}"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    entries = inbox_mod.scan_inbox(RAW_DIR)
    card_names = _load_card_names()
    known_own = reg_mod.load_known_own_decks(REPO)
    written = _write_decks(entries)
    registry = reg_mod.build_registry(entries, known_own, card_names)

    OUT_REG_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_REG_JSON.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    OUT_REG_MD.write_text(to_markdown(registry), encoding="utf-8")
    OUT_ERRORS.write_text(json.dumps({
        "schema": "activegraph.replays.inbox_errors/v1",
        "errors": registry["errors"],
        "duplicates_skipped": registry["duplicates_skipped"],
    }, indent=2), encoding="utf-8")

    # Processing state: an append-only record of which episodes/files have been
    # ingested, so a future run can tell new replays from already-seen ones.
    state = {
        "schema": "activegraph.replays.processing_state/v1",
        "pass": "11b",
        "processed_episodes": sorted(
            {str(r["episode_id"]) for r in registry["records"]}
        ),
        "processed_file_sha256": sorted(
            {r["file_sha256"] for r in registry["records"] if r["file_sha256"]}
        ),
        "decks_written": written,
        "counts": {
            "in_inbox": registry["replays_total"],
            "registered": registry["replays_registered"],
            "duplicates": len(registry["duplicates_skipped"]),
            "errors": len(registry["errors"]),
        },
    }
    OUT_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")

    print(f"ingested {registry['replays_total']} inbox file(s); "
          f"registered {registry['replays_registered']}")
    print(f"  duplicates skipped: {len(registry['duplicates_skipped'])}, "
          f"errors: {len(registry['errors'])}")
    print(f"  decks written: {len(written)}")
    for out in (OUT_REG_JSON, OUT_REG_MD, OUT_ERRORS, OUT_STATE):
        print(f"  -> {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
