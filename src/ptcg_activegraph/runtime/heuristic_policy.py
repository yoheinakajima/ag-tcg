"""Heuristic option-ranking policy (v1).

The policy is intentionally crude but stable: it serializes each option to a
lower-cased text blob, scores it by keyword presence (and by recognized fields
when present), and prefers higher scores with a deterministic tie-break on the
lower option index.

It must be robust to *unknown* option schemas — never assume a field exists.
See ``docs/RUNTIME_AGENT.md`` for the weight rationale.
"""

from __future__ import annotations

from .action import OptionView, parse_select

# Positive signals -> we usually want to do these.
POSITIVE_WEIGHTS: dict[str, int] = {
    "knock": 100,
    "ko": 60,
    "prize": 80,
    "attack": 80,
    "damage": 50,
    "evolve": 45,
    "evolution": 40,
    "attach": 40,
    "energy": 40,
    "draw": 35,
    "search": 35,
    "supporter": 30,
    "ability": 30,
    "skill": 30,
    "item": 25,
    "bench": 20,
    "stadium": 18,
    "switch": 15,
    "active": 12,
}

# Cautious / negative signals -> avoid unless nothing better.
NEGATIVE_WEIGHTS: dict[str, int] = {
    "end": -100,
    "pass": -100,
    "discard": -20,
    "trash": -20,
    "retreat": -10,
}

# Keywords that, when co-present, cancel the discard penalty (e.g. a draw card
# that discards as a cost is still good).
DISCARD_REDEEMERS = ("draw", "search", "attack", "attach", "evolve")


def score_option(option: OptionView | object) -> int:
    """Score a single option. Accepts an :class:`OptionView` or a raw option."""
    if isinstance(option, OptionView):
        text = option.text
    else:  # tolerate being handed a raw option directly
        from .action import serialize_option

        text = serialize_option(option)

    score = 0

    for keyword, weight in POSITIVE_WEIGHTS.items():
        if keyword in text:
            score += weight

    for keyword, weight in NEGATIVE_WEIGHTS.items():
        if keyword in text:
            if keyword in ("discard", "trash") and any(
                r in text for r in DISCARD_REDEEMERS
            ):
                continue  # discard-as-cost on an otherwise good play
            score += weight

    return score


def rank_options(options: list) -> list[int]:
    """Return option indices ordered best-first.

    Deterministic: sorts by descending score then ascending index.
    """
    views = parse_select(options)
    scored = [(score_option(v), v.index) for v in views]
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [idx for _, idx in scored]


def heuristic_select(options: list, max_count: int, min_count: int = 0) -> list[int]:
    """Choose up to ``max_count`` options by heuristic rank.

    For single-select, returns the single best option. For multi-select, picks
    the top ``max_count`` *positively scored* options, returning indices in
    ascending order (engines generally accept any order, but ascending is
    deterministic and matches the fallback convention).
    """
    num = len(options) if isinstance(options, list) else 0
    if num == 0 or max_count <= 0:
        return []

    ranked = rank_options(options)
    if not ranked:
        return []

    if max_count == 1:
        return [ranked[0]]

    # Multi-select: take the best options. Prefer positively-scored ones, but
    # always satisfy min_count even if remaining options score <= 0.
    views = {v.index: v for v in parse_select(options)}
    chosen: list[int] = []
    for idx in ranked:
        if len(chosen) >= max_count:
            break
        s = score_option(views[idx])
        if s > 0 or len(chosen) < min_count:
            chosen.append(idx)

    if not chosen:
        chosen = [ranked[0]]

    return sorted(chosen)


# ---------------------------------------------------------------------------
# Debug / lab helper: explain why each option scored as it did.
# Not used by the Kaggle runtime (main.py is self-contained).
# ---------------------------------------------------------------------------

# Structured fields that, when present on a dict option, reinforce a signal.
_FIELD_HINTS = ("type", "context", "selectType", "select_type", "name", "card",
                "cardId", "card_id", "action", "player", "target", "description",
                "skill", "attack", "damage", "cost")


def _matched_keywords(text: str) -> list[tuple[str, int]]:
    hits: list[tuple[str, int]] = []
    for kw, w in POSITIVE_WEIGHTS.items():
        if kw in text:
            hits.append((kw, w))
    for kw, w in NEGATIVE_WEIGHTS.items():
        if kw in text:
            if kw in ("discard", "trash") and any(r in text for r in DISCARD_REDEEMERS):
                continue
            hits.append((kw, w))
    return hits


def rank_options_with_reasons(obs_dict: dict) -> list[dict]:
    """Return ranked options with score + matched-keyword reasons (debugging).

    Reads the observation defensively, scores each option, and surfaces any
    recognized structured fields so we can see how the real cabt schema maps to
    our keyword heuristic.
    """
    from .observation import parse_observation

    parsed = parse_observation(obs_dict)
    views = parse_select(parsed.options)
    rows: list[dict] = []
    for v in views:
        reasons = _matched_keywords(v.text)
        fields_present = {k: v.fields[k] for k in _FIELD_HINTS if k in v.fields}
        rows.append({
            "index": v.index,
            "score": score_option(v),
            "matched": reasons,
            "fields": fields_present,
            "text_preview": v.text[:160],
        })
    rows.sort(key=lambda r: (-r["score"], r["index"]))
    return rows
