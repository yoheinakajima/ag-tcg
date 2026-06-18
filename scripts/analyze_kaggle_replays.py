#!/usr/bin/env python3
"""Analyze the raw Kaggle replay corpus into a meta summary + archetypes.

Pipeline (Pass 10):

    data/meta_replays/raw/*.json
        -> data/meta_replays/decks/<ep>_p{0,1}_deck.csv   (extract_replay_decks)
        -> data/meta_replays/meta_replay_summary.json
        -> data/meta_replays/meta_replay_summary.md
        -> data/meta_replays/archetypes.yaml

Honest about coverage: only the real self-mirror replay is present, so external
opponent archetypes stay blocked. No card id is ever invented.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.replays.kaggle_replay import load_replay  # noqa: E402
from ptcg_activegraph.meta import archetypes as arch_mod  # noqa: E402
from ptcg_activegraph.playbooks.schema import CARD_NAMES, CONFIRMED_CARDS  # noqa: E402

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

RAW_DIR = REPO / "data" / "meta_replays" / "raw"
DECKS_DIR = REPO / "data" / "meta_replays" / "decks"
OUT_JSON = REPO / "data" / "meta_replays" / "meta_replay_summary.json"
OUT_MD = REPO / "data" / "meta_replays" / "meta_replay_summary.md"
OUT_ARCH = REPO / "data" / "meta_replays" / "archetypes.yaml"

CONFIRMED_IDS = set(CONFIRMED_CARDS.values())

# Cards of interest for tempo signals (all confirmed).
KYOGRE, SNOVER, MEGA_ABOMASNOW = 721, 722, 723


def _name(cid: int) -> str:
    return CARD_NAMES.get(cid, f"card {cid}")


def _is_mirror(decks: dict[int, list[int]]) -> bool:
    if len(decks) < 2:
        return False
    seats = sorted(decks)
    return Counter(decks[seats[0]]) == Counter(decks[seats[1]])


def analyze_replay_file(path: Path) -> dict:
    replay = load_replay(path)
    episode = replay.episode_id
    info = replay.info
    agents = [a.get("Name") for a in info.get("Agents", []) if isinstance(a, dict)]
    decks = replay.submitted_decks()
    final = replay.final_result()

    seats_out: dict[str, dict] = {}
    for seat in sorted(decks):
        ids = decks[seat]
        metrics = replay.board_metrics(seat)
        board = set(metrics["board_card_ids"])
        all_in_confirmed = bool(ids) and all(c in CONFIRMED_IDS for c in set(ids))
        seats_out[str(seat)] = {
            "agent": agents[seat] if seat < len(agents) else None,
            "deck_count": len(ids),
            "deck_unique": len(set(ids)),
            "deck_counts": {str(k): v for k, v in sorted(Counter(ids).items())},
            "deck_all_ids_confirmed": all_in_confirmed,
            "final_reward": metrics["final_reward"],
            "won": metrics["won"],
            "first_attack_turn": metrics["first_attack_turn"],
            "evolved_mega_abomasnow": MEGA_ABOMASNOW in board,
            "used_kyogre": KYOGRE in board,
            "used_snover": SNOVER in board,
            "stuck_on_basic_snover": (SNOVER in board and MEGA_ABOMASNOW not in board),
            "max_bench_size": max(metrics["bench_size_by_turn"].values(), default=0),
            "benched_backup": max(metrics["bench_size_by_turn"].values(), default=0) > 0,
            "min_deck_count": metrics["min_deck_count"],
            "decked_out": metrics["min_deck_count"] == 0,
            "turns_observed": metrics["turns_observed"],
            "deckcount_trajectory": metrics["deckcount_trajectory"],
        }

    return {
        "episode": episode,
        "source": str(path.relative_to(REPO) if path.is_relative_to(REPO) else path),
        "agents": agents,
        "is_self_mirror": _is_mirror(decks),
        "num_steps": replay.num_steps,
        "rewards": final["rewards"],
        "statuses": final["statuses"],
        "winner_seat": final["winner_seat"],
        "seats": seats_out,
    }


def _write_decks(analysis_list: list[dict]) -> None:
    DECKS_DIR.mkdir(parents=True, exist_ok=True)
    for a in analysis_list:
        replay = load_replay(RAW_DIR / Path(a["source"]).name) if (RAW_DIR / Path(a["source"]).name).exists() else None
        if replay is None:
            continue
        for seat, ids in replay.submitted_decks().items():
            out = DECKS_DIR / f"{a['episode']}_p{seat}_deck.csv"
            out.write_text("\n".join(str(i) for i in ids) + "\n", encoding="utf-8")


def _build_archetypes(analysis_list: list[dict]) -> dict:
    # Upgrade the mirror archetype from the real self-mirror replay if present.
    for a in analysis_list:
        if a["is_self_mirror"] and a["seats"]:
            seat0 = sorted(a["seats"])[0]
            replay = load_replay(RAW_DIR / Path(a["source"]).name)
            decks = replay.submitted_decks()
            ids = decks[int(seat0)]
            deck_path = f"data/meta_replays/decks/{a['episode']}_p{seat0}_deck.csv"
            arch_mod.attach_mirror_deck(ids, a["episode"], deck_path)
            break
    return arch_mod.build_archetypes_yaml_obj()


def to_markdown(summary: dict) -> str:
    lines = ["# Meta replay summary (Pass 10)", ""]
    lines.append(f"- raw replays analyzed: **{summary['replays_analyzed']}**")
    lines.append(f"- missing external replays: **{', '.join(summary['missing_replays']) or 'none'}**")
    lines.append("")
    for a in summary["replays"]:
        lines.append(f"## Episode {a['episode']}")
        lines.append(f"- source: `{a['source']}`")
        lines.append(f"- agents: {a['agents']}")
        lines.append(f"- self-mirror: **{a['is_self_mirror']}**")
        lines.append(f"- steps: {a['num_steps']}, rewards: {a['rewards']}, winner seat: {a['winner_seat']}")
        for seat, s in sorted(a["seats"].items()):
            lines.append(f"  - **seat {seat}** ({s['agent']}): "
                         f"won={s['won']}, first_attack_turn={s['first_attack_turn']}, "
                         f"evolved_mega_abomasnow={s['evolved_mega_abomasnow']}, "
                         f"stuck_on_basic_snover={s['stuck_on_basic_snover']}, "
                         f"max_bench={s['max_bench_size']}, decked_out={s['decked_out']} "
                         f"(min_deck={s['min_deck_count']})")
        lines.append("")
    lines.append("## Tempo failure signals (from real replay)")
    for sig in summary["tempo_signals"]:
        lines.append(f"- {sig}")
    lines.append("")
    lines.append("## Archetypes")
    for arch in summary["archetypes"]["archetypes"]:
        lines.append(f"- **{arch['key']}** — {arch['status']} "
                     f"(card_ids: {arch['card_ids_status']})")
    return "\n".join(lines) + "\n"


def main() -> int:
    raw = []
    if RAW_DIR.exists():
        raw = sorted(p for p in RAW_DIR.glob("*.json") if not p.name.startswith("_"))

    analysis_list = [analyze_replay_file(p) for p in raw]
    _write_decks(analysis_list)
    archetypes_obj = _build_archetypes(analysis_list)

    # Tempo signals are reported only from real data.
    tempo_signals: list[str] = []
    for a in analysis_list:
        for seat, s in sorted(a["seats"].items()):
            if s["stuck_on_basic_snover"]:
                tempo_signals.append(
                    f"episode {a['episode']} seat {seat}: stuck on basic Snover "
                    f"(never evolved Mega Abomasnow ex)")
            if s["decked_out"]:
                tempo_signals.append(
                    f"episode {a['episode']} seat {seat}: decked out "
                    f"(deckCount reached 0) — over-thinning / passive long game")
    if not tempo_signals:
        tempo_signals.append("no tempo failure signals detected in available replays")

    missing = [k for k, v in arch_mod.ARCHETYPES.items()
               if v.status == arch_mod.ArchetypeStatus.BLOCKED]

    summary = {
        "schema": "activegraph.meta.replay_summary/v1",
        "replays_analyzed": len(analysis_list),
        "missing_replays": missing,
        "replays": analysis_list,
        "tempo_signals": tempo_signals,
        "archetypes": archetypes_obj,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    OUT_MD.write_text(to_markdown(summary), encoding="utf-8")
    if yaml is not None:
        OUT_ARCH.write_text(yaml.safe_dump(archetypes_obj, sort_keys=False), encoding="utf-8")
    else:
        OUT_ARCH.write_text(json.dumps(archetypes_obj, indent=2), encoding="utf-8")

    print(f"analyzed {len(analysis_list)} replay(s)")
    print(f"  -> {OUT_JSON.relative_to(REPO)}")
    print(f"  -> {OUT_MD.relative_to(REPO)}")
    print(f"  -> {OUT_ARCH.relative_to(REPO)}")
    print(f"  tempo signals: {len(tempo_signals)}")
    print(f"  blocked archetypes: {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
