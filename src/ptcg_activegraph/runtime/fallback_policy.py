"""Last-resort legal policy.

The fallback policy never inspects option semantics. Its only job is to return
a *valid* selection no matter how degenerate the input is. Every other policy
defers to this when it cannot decide.
"""

from __future__ import annotations


def fallback_select(num_options: int, max_count: int, min_count: int = 0) -> list[int]:
    """Return a guaranteed-legal list of option indices.

    Rules (see ``docs/RUNTIME_AGENT.md``):

    * ``max_count == 0`` (or no options) -> ``[]``.
    * ``max_count == 1`` -> the first legal option, ``[0]``.
    * ``max_count > 1`` -> the first ``max_count`` options, but never fewer than
      ``min_count`` and never more than the number of available options.

    The result is always a list of unique, in-range, ascending indices.
    """
    if num_options <= 0 or max_count <= 0:
        return []

    max_count = min(max_count, num_options)
    min_count = max(0, min(min_count, max_count))

    if max_count == 1:
        # If the engine demands at least one (min_count >= 1) or the common
        # "pick one" case, return a single index. If min_count is 0 we still
        # return one index because a no-op is usually represented as its own
        # explicit option rather than an empty selection.
        return [0]

    # Multi-select: be conservative. Take min_count if it is positive, else
    # take the full window. Conservative selection avoids over-committing in
    # discard/sacrifice style prompts where fewer is safer.
    take = min_count if min_count > 0 else max_count
    take = min(take, num_options)
    return list(range(take))


def clamp_selection(
    selection: list[int], num_options: int, max_count: int, min_count: int = 0
) -> list[int]:
    """Validate and repair a proposed selection so it is always legal.

    * Drops out-of-range and non-integer indices.
    * De-duplicates while preserving order.
    * Truncates to ``max_count``.
    * Pads from the lowest unused legal indices up to ``min_count``.
    * Falls back entirely if nothing valid remains but a choice is required.
    """
    if num_options <= 0 or max_count <= 0:
        return []

    seen: set[int] = set()
    cleaned: list[int] = []
    for item in selection or []:
        try:
            idx = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < num_options and idx not in seen:
            seen.add(idx)
            cleaned.append(idx)

    # Truncate to the maximum allowed.
    if len(cleaned) > max_count:
        cleaned = cleaned[:max_count]

    # Pad up to the minimum required from the lowest unused legal indices.
    if len(cleaned) < min_count:
        for idx in range(num_options):
            if len(cleaned) >= min_count:
                break
            if idx not in seen:
                seen.add(idx)
                cleaned.append(idx)

    if not cleaned and (min_count > 0 or max_count >= 1):
        # A choice is required but we ended up empty -> use the raw fallback.
        return fallback_select(num_options, max_count, min_count)

    return cleaned
