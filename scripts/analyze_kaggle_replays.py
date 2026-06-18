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
REGISTRY_JSON = REPO / "data" / "meta_replays" / "replay_registry.json"
OUT_ANALYSIS_JSON = REPO / "data" / "meta_replays" / "replay_analysis.json"
OUT_ANALYSIS_MD = REPO / "data" / "meta_replays" / "replay_analysis.md"

CONFIRMED_IDS = set(CONFIRMED_CARDS.values())

# A loss is "fast" if it ends in <= this many env steps; "long" if it runs at
# least LONG_STEPS or a seat decks out. Tuned to the observed corpus length.
FAST_LOSS_STEPS = 60
LONG_GAME_STEPS = 140

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


def _load_registry() -> dict:
    if REGISTRY_JSON.exists():
        return json.loads(REGISTRY_JSON.read_text(encoding="utf-8"))
    return {}


def build_replay_analysis(analysis_list: list[dict], registry: dict) -> dict:
    """Per-replay outcome + tempo metrics keyed off the registry perspective.

    Produces the Part E metrics: wins/losses/draws, fast losses, long
    attrition/deckout games, recurring failure tags, and opponent patterns.
    Outcome/perspective come from the registry (resolved by our seat); tempo
    flags come from the replay board metrics. No card id is invented.
    """
    persp_by_ep = {str(r.get("episode_id")): r for r in registry.get("records", [])}

    per_replay: list[dict] = []
    wins = losses = draws = mirrors = other = 0
    fast_losses: list[str] = []
    long_games: list[str] = []
    failure_tags: Counter = Counter()
    opponent_archetypes: Counter = Counter()

    for a in analysis_list:
        ep = str(a["episode"])
        reg = persp_by_ep.get(ep, {})
        perspective = reg.get("perspective", "opponent_only_or_unknown")
        our_seat = reg.get("our_seat")
        steps = a.get("num_steps") or 0

        if perspective == "our_win":
            wins += 1
        elif perspective == "our_loss":
            losses += 1
        elif perspective == "our_draw":
            draws += 1
        elif perspective == "self_mirror":
            mirrors += 1
        else:
            other += 1

        # Opponent archetype (from registry classification).
        opp = next((s for s in reg.get("seats", []) if not s.get("is_ours")), None)
        opp_arch = ((opp or {}).get("archetype") or {}).get("archetype_id")
        if opp_arch:
            opponent_archetypes[opp_arch] += 1

        # Our-seat tempo flags.
        our_metrics = {}
        if isinstance(our_seat, int):
            our_metrics = a["seats"].get(str(our_seat), {})
        any_decked = any(s.get("decked_out") for s in a["seats"].values())
        our_decked = bool(our_metrics.get("decked_out"))
        stuck = bool(our_metrics.get("stuck_on_basic_snover"))

        is_fast_loss = perspective == "our_loss" and steps <= FAST_LOSS_STEPS
        is_long = steps >= LONG_GAME_STEPS or any_decked
        if is_fast_loss:
            fast_losses.append(ep)
        if is_long:
            long_games.append(ep)

        tags: list[str] = []
        if is_fast_loss:
            tags.append("fast_loss")
            failure_tags["fast_loss"] += 1
        if our_decked:
            tags.append("our_deckout")
            failure_tags["our_deckout"] += 1
        if stuck:
            tags.append("stuck_on_basic_snover")
            failure_tags["stuck_on_basic_snover"] += 1
        if perspective == "our_loss" and not tags:
            tags.append("loss_no_specific_tempo_tag")
            failure_tags["loss_no_specific_tempo_tag"] += 1

        per_replay.append({
            "episode": a["episode"],
            "perspective": perspective,
            "our_seat": our_seat,
            "num_steps": steps,
            "opponent_archetype": opp_arch,
            "our_decked_out": our_decked,
            "stuck_on_basic_snover": stuck,
            "fast_loss": is_fast_loss,
            "long_game": is_long,
            "failure_tags": tags,
        })

    return {
        "schema": "activegraph.meta_replays.replay_analysis/v1",
        "pass": "11b",
        "replays_analyzed": len(per_replay),
        "record": {
            "wins": wins, "losses": losses, "draws": draws,
            "self_mirrors": mirrors, "opponent_only_or_unknown": other,
        },
        "fast_losses": fast_losses,
        "long_or_deckout_games": long_games,
        "recurring_failure_tags": dict(failure_tags.most_common()),
        "opponent_archetype_counts": dict(opponent_archetypes.most_common()),
        "thresholds": {"fast_loss_steps": FAST_LOSS_STEPS,
                       "long_game_steps": LONG_GAME_STEPS},
        "per_replay": per_replay,
    }


def analysis_to_markdown(an: dict) -> str:
    rec = an["record"]
    lines = ["# Replay analysis (Pass 11B)", ""]
    lines.append(f"- replays analyzed: **{an['replays_analyzed']}**")
    lines.append(f"- record (by our seat): **{rec['wins']}W / {rec['losses']}L / "
                 f"{rec['draws']}D**, self-mirrors: {rec['self_mirrors']}, "
                 f"other: {rec['opponent_only_or_unknown']}")
    lines.append(f"- fast losses (≤{an['thresholds']['fast_loss_steps']} steps): "
                 f"{', '.join(an['fast_losses']) or 'none'}")
    lines.append(f"- long/deckout games: {', '.join(an['long_or_deckout_games']) or 'none'}")
    lines.append("")
    lines.append("## Recurring failure tags")
    for tag, n in an["recurring_failure_tags"].items():
        lines.append(f"- {tag}: {n}")
    if not an["recurring_failure_tags"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Opponent archetype patterns")
    for arch, n in an["opponent_archetype_counts"].items():
        lines.append(f"- {arch}: {n}")
    if not an["opponent_archetype_counts"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Per-replay")
    lines.append("| episode | perspective | steps | opponent | tags |")
    lines.append("|---|---|---|---|---|")
    for r in an["per_replay"]:
        lines.append(
            f"| {r['episode']} | {r['perspective']} | {r['num_steps']} | "
            f"{r['opponent_archetype'] or '-'} | {', '.join(r['failure_tags']) or '-'} |"
        )
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

    # Pass 11B: per-replay outcome/tempo analysis keyed off the registry.
    registry = _load_registry()
    analysis = build_replay_analysis(analysis_list, registry)
    OUT_ANALYSIS_JSON.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
    OUT_ANALYSIS_MD.write_text(analysis_to_markdown(analysis), encoding="utf-8")

    print(f"analyzed {len(analysis_list)} replay(s)")
    print(f"  -> {OUT_JSON.relative_to(REPO)}")
    print(f"  -> {OUT_MD.relative_to(REPO)}")
    print(f"  -> {OUT_ANALYSIS_JSON.relative_to(REPO)}")
    print(f"  -> {OUT_ANALYSIS_MD.relative_to(REPO)}")
    rec = analysis["record"]
    print(f"  record: {rec['wins']}W/{rec['losses']}L/{rec['draws']}D "
          f"(mirrors {rec['self_mirrors']})")
    print(f"  tempo signals: {len(tempo_signals)}; blocked archetypes: {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
