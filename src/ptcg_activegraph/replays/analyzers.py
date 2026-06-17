"""Turn a parsed :class:`KaggleReplay` into a structured analysis.

The analysis is intentionally *honest*: cabt's per-option schema is not fully
documented here, so wherever we cannot prove an interpretation we record an
``uncertain`` note instead of asserting a fabricated conclusion. The output is a
plain dict (JSON-serializable) plus a markdown renderer.

Known numeric option/select types (from the runner instrumentation):
    8  -> place / bench / setup choice
    13 -> attack
    14 -> pass / end turn
Other type ints are reported as-is under ``unknown``.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .kaggle_replay import KaggleReplay

# Option/select type ids we can name with confidence.
TYPE_NAMES = {
    8: "place_or_setup",
    13: "attack",
    14: "pass_or_end",
}

# Card ids that drive the replay-derived effect-resolution seams. Used only to
# flag *uncertainty* when these cards appear in a decision the replay can't prove
# was resolved optimally — never to invent an outcome.
EFFECT_CARDS = {
    1121: "Ultra Ball",
    1092: "Secret Box",
    1145: "Mega Signal",
    721: "Kyogre",
    722: "Snover",
    723: "Mega Abomasnow ex",
}


def _as_int_list(value: Any) -> list[int]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[int] = []
    for v in value:
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            out.append(v)
    return out


def _looks_like_deck(action: Any) -> bool:
    ids = _as_int_list(action)
    return len(ids) >= 40  # a cabt deck is 60 ids; >=40 is unambiguously a deck


def _extract_select(obs: Any) -> dict | None:
    if not isinstance(obs, dict):
        return None
    sel = obs.get("select")
    return sel if isinstance(sel, dict) else None


def _option_type(opt: Any) -> Any:
    if isinstance(opt, dict):
        return opt.get("type")
    return None


def _option_card_id(opt: Any) -> Any:
    if not isinstance(opt, dict):
        return None
    for key in ("cardId", "card_id", "id", "card"):
        if key in opt:
            v = opt[key]
            if isinstance(v, int) and not isinstance(v, bool):
                return v
    return None


def _analyze_decks(replay: KaggleReplay) -> dict:
    """Best-effort deck extraction from step 0 actions, compared to baselines."""
    decks: dict[str, Any] = {"per_seat": [], "uncertain": []}
    steps = replay.steps
    if not steps:
        decks["uncertain"].append("no steps present; cannot read submitted decks")
        return decks
    first = steps[0]
    if not isinstance(first, list):
        decks["uncertain"].append("step 0 is not a per-seat list")
        return decks
    for seat, rec in enumerate(first):
        action = rec.get("action") if isinstance(rec, dict) else None
        if _looks_like_deck(action):
            ids = _as_int_list(action)
            counts = Counter(ids)
            decks["per_seat"].append({
                "seat": seat,
                "card_count": len(ids),
                "unique_card_ids": sorted(counts),
                "counts": {str(k): v for k, v in sorted(counts.items())},
            })
        else:
            decks["per_seat"].append({"seat": seat, "card_count": None})
            decks["uncertain"].append(
                f"seat {seat}: step-0 action is not a recognizable 60-card deck"
            )
    return decks


def _analyze_actions(replay: KaggleReplay) -> dict:
    """Fold per-decision option/choice distributions across the whole episode."""
    select_context = Counter()
    select_type = Counter()
    option_type = Counter()
    chosen_type = Counter()
    decisions = 0
    attack_count = 0
    pass_end_count = 0
    attack_available = 0
    first_legal_picks = 0
    multi_option_decisions = 0
    effect_card_contexts: list[dict] = []

    for seat in range(max(2, 0)):
        for step_idx, rec in enumerate(replay.agent_steps(seat)):
            obs = rec.get("observation")
            sel = _extract_select(obs)
            if not sel:
                continue
            options = sel.get("options") or sel.get("option") or sel.get("choices")
            if not isinstance(options, list) or not options:
                continue
            decisions += 1
            ctx = sel.get("context")
            if ctx is not None:
                select_context[str(ctx)] += 1
            stype = sel.get("type")
            if stype is not None:
                select_type[str(stype)] += 1

            types = [_option_type(o) for o in options]
            for t in types:
                if t is not None:
                    option_type[str(t)] += 1
            if 13 in types:
                attack_available += 1

            # Flag effect-resolution cards that appear among the options.
            for o in options:
                cid = _option_card_id(o)
                if cid in EFFECT_CARDS:
                    effect_card_contexts.append({
                        "seat": seat,
                        "step": step_idx,
                        "card_id": cid,
                        "card": EFFECT_CARDS[cid],
                        "context": str(ctx) if ctx is not None else None,
                        "n_options": len(options),
                    })

            chosen = _as_int_list(rec.get("action"))
            if len(options) > 1:
                multi_option_decisions += 1
                if chosen and chosen[0] == 0:
                    first_legal_picks += 1
            for idx in chosen:
                if 0 <= idx < len(types):
                    t = types[idx]
                    if t is not None:
                        chosen_type[str(t)] += 1
                    if t == 13:
                        attack_count += 1
                    elif t == 14:
                        pass_end_count += 1

    first_legal_rate = (
        round(first_legal_picks / multi_option_decisions, 4)
        if multi_option_decisions else None
    )
    return {
        "decisions": decisions,
        "select_context_distribution": dict(select_context),
        "select_type_distribution": dict(select_type),
        "option_type_distribution": dict(option_type),
        "chosen_option_type_distribution": dict(chosen_type),
        "attack_count": attack_count,
        "pass_or_end_count": pass_end_count,
        "attack_available": attack_available,
        "multi_option_decisions": multi_option_decisions,
        "first_legal_pick_count": first_legal_picks,
        "first_legal_pick_rate": first_legal_rate,
        "effect_card_decision_contexts": effect_card_contexts,
        "type_name_legend": TYPE_NAMES,
    }


def _failure_tags(replay: KaggleReplay, actions: dict) -> list[dict]:
    """Conservative failure/lesson tagging. Each tag carries its evidence."""
    tags: list[dict] = []

    def add(tag: str, present: Any, evidence: str, confidence: str):
        tags.append({
            "tag": tag,
            "present": present,
            "confidence": confidence,
            "evidence": evidence,
        })

    # effect_resolution_first_legal: did the agent default to the first option
    # on multi-option prompts most of the time?
    flr = actions.get("first_legal_pick_rate")
    if flr is None:
        add("effect_resolution_first_legal", None,
            "no multi-option decisions observed", "uncertain")
    else:
        add("effect_resolution_first_legal", flr >= 0.7,
            f"first-legal pick rate = {flr} over "
            f"{actions.get('multi_option_decisions')} multi-option decisions",
            "high" if flr >= 0.85 else "medium")

    # *_targeting_uncertain: these cards appeared in a decision but the replay
    # cannot prove the chosen target was optimal.
    seen = {c["card_id"] for c in actions.get("effect_card_decision_contexts", [])}
    add("ultra_ball_targeting_uncertain", 1121 in seen,
        "Ultra Ball (1121) appeared in a decision context" if 1121 in seen
        else "Ultra Ball not observed in any decision", "uncertain")
    add("secret_box_targeting_uncertain", 1092 in seen,
        "Secret Box (1092) appeared in a decision context" if 1092 in seen
        else "Secret Box not observed in any decision", "uncertain")
    add("mega_signal_targeting_uncertain", 1145 in seen,
        "Mega Signal (1145) appeared in a decision context" if 1145 in seen
        else "Mega Signal not observed in any decision", "uncertain")

    # overdraw_or_deckout_pressure: did the episode run long relative to cap?
    n = replay.num_steps
    cap = replay.episode_steps
    if isinstance(cap, int) and cap > 0:
        ratio = round(n / cap, 4)
        add("overdraw_or_deckout_pressure", ratio >= 0.5,
            f"{n} steps / {cap} episodeSteps cap = {ratio}",
            "medium" if ratio >= 0.5 else "low")
    else:
        add("overdraw_or_deckout_pressure", None,
            "episodeSteps cap unknown", "uncertain")

    # setup biases — only assertable if we can see the opening active choice.
    add("kyogre_active_bias", None,
        "opening Active choice not resolvable from replay schema", "uncertain")
    add("snower_setup_bias", None,
        "opening setup choice not resolvable from replay schema", "uncertain")
    add("failed_to_evolve_if_detected", None,
        "evolution prompts not separable from generic place choices", "uncertain")

    # attack damage — rewards are terminal only; per-attack damage not in schema.
    add("attack_damage_low", None,
        "per-attack damage not present in episode rewards", "uncertain")

    # pass_or_end_too_early: did the agent pass/end while an attack was legal?
    attacks_avail = actions.get("attack_available", 0)
    passes = actions.get("pass_or_end_count", 0)
    if attacks_avail:
        add("pass_or_end_too_early", passes > 0 and passes >= attacks_avail,
            f"{passes} pass/end vs {attacks_avail} decisions with attack available",
            "low")
    else:
        add("pass_or_end_too_early", None,
            "no decisions with an attack option observed", "uncertain")

    # timeout_safe: no TIMEOUT/ERROR statuses anywhere.
    statuses = [str(s) for s in replay.statuses]
    timed_out = any(s in ("TIMEOUT", "ERROR") for s in statuses)
    add("timeout_safe", not timed_out,
        f"terminal statuses = {statuses or 'unknown'}",
        "high" if statuses else "uncertain")

    return tags


def analyze(replay: KaggleReplay) -> dict:
    """Produce the full structured analysis dict for a replay."""
    actions = _analyze_actions(replay)
    return {
        "episode": {
            "episode_id": replay.episode_id,
            "name": replay.name,
            "module_version": replay.module_version,
            "configuration": replay.configuration,
            "statuses": replay.statuses,
            "rewards": replay.rewards,
            "num_steps": replay.num_steps,
            "act_timeout": replay.act_timeout,
            "run_timeout": replay.run_timeout,
            "episode_steps": replay.episode_steps,
            "final_result": replay.final_result(),
        },
        "decks": _analyze_decks(replay),
        "actions": actions,
        "failure_tags": _failure_tags(replay, actions),
        "source_path": replay.source_path,
    }


def to_markdown(analysis: dict) -> str:
    ep = analysis.get("episode", {})
    decks = analysis.get("decks", {})
    actions = analysis.get("actions", {})
    tags = analysis.get("failure_tags", [])

    lines = [
        f"# Replay analysis — episode {ep.get('episode_id')}",
        "",
        "## Episode",
        f"- name: {ep.get('name')}",
        f"- module version: {ep.get('module_version')}",
        f"- statuses: {ep.get('statuses')}",
        f"- rewards: {ep.get('rewards')}",
        f"- steps: {ep.get('num_steps')}",
        f"- final result: {ep.get('final_result')}",
        f"- actTimeout: {ep.get('act_timeout')}",
        f"- runTimeout: {ep.get('run_timeout')}",
        f"- episodeSteps: {ep.get('episode_steps')}",
        "",
        "## Decks (step 0)",
    ]
    for d in decks.get("per_seat", []):
        lines.append(
            f"- seat {d.get('seat')}: card_count={d.get('card_count')} "
            f"unique={len(d.get('unique_card_ids', [])) if d.get('unique_card_ids') else '-'}"
        )
    for u in decks.get("uncertain", []):
        lines.append(f"- _uncertain:_ {u}")

    lines += [
        "",
        "## Actions",
        f"- decisions: {actions.get('decisions')}",
        f"- select.context distribution: {actions.get('select_context_distribution')}",
        f"- select.type distribution: {actions.get('select_type_distribution')}",
        f"- option.type distribution: {actions.get('option_type_distribution')}",
        f"- chosen option.type distribution: {actions.get('chosen_option_type_distribution')}",
        f"- attack count: {actions.get('attack_count')}",
        f"- pass/end count: {actions.get('pass_or_end_count')}",
        f"- decisions with attack available: {actions.get('attack_available')}",
        f"- first-legal pick rate (multi-option): {actions.get('first_legal_pick_rate')}",
        f"- effect-card decision contexts: {len(actions.get('effect_card_decision_contexts', []))}",
        "",
        "## Failure / lesson tags",
    ]
    for t in tags:
        lines.append(
            f"- **{t['tag']}**: present={t['present']} "
            f"(confidence={t['confidence']}) — {t['evidence']}"
        )
    lines.append("")
    return "\n".join(lines)
