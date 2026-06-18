"""Surrogate opponent agents for replay-informed local evaluation (Pass 11B).

Opponent replays give us the opponent's *deck list*, not their *policy*. So local
evaluation is surrogate-based: we let a stable, deliberately-generic heuristic pilot
the replay-derived deck. The surrogate is not meant to be strong — only a consistent
proxy so candidate-vs-archetype comparisons are apples-to-apples.

Two surfaces are provided:

* :func:`make_surrogate_agent` — an in-process ``agent(obs) -> list[int]`` callable.
  It honours the documented lab contract: on a deck-selection step (``select`` is
  ``None``/empty) it returns the supplied 60-card deck; otherwise it defers to the
  shared safe heuristic policy. Useful for unit tests and non-cabt harnesses.

* :func:`materialize_surrogate_agent` — writes a runnable cabt agent *directory*
  (``main.py`` + ``deck.csv``) so the surrogate can be passed to
  ``kaggle_environments.make("cabt")`` as a file-path agent. cabt binds each
  agent's sibling ``deck.csv``, which is how the opponent ends up piloting the
  replay-derived deck. The ``main.py`` brain is copied from a self-contained,
  stdlib-only baseline so the surrogate never imports lab code at runtime.

Hard rule: decks pass through verbatim. No card id is invented or mutated here.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[3]
# Self-contained, stdlib-only safe-heuristic brain reused as the surrogate policy.
DEFAULT_BRAIN = REPO / "data" / "baselines" / "v1_kaggle_349_8" / "main.py"


def _coerce_deck(deck: list[int] | str | Path) -> list[int]:
    """Return a validated 60-int decklist from a list or a deck.csv path."""
    if isinstance(deck, (str, Path)):
        from ..decks.deck_io import load_deck

        ids = load_deck(deck)
    else:
        ids = list(deck)
    if len(ids) != 60 or not all(isinstance(c, int) for c in ids):
        raise ValueError(
            f"surrogate deck must be 60 integer card ids, got {len(ids)} entries"
        )
    return ids


def _is_deck_selection_step(obs: Any) -> bool:
    """True when the observation is a deck/setup step with no concrete options.

    The cabt runtime presents real in-game choices via ``select.options``; the
    deck/mulligan setup phases arrive with ``select`` missing or empty.
    """
    if not isinstance(obs, dict):
        return obs is None
    select = obs.get("select")
    if select is None:
        return True
    if isinstance(select, dict):
        opts = select.get("options", select.get("option"))
        return not opts
    return False


def make_surrogate_agent(
    deck: list[int] | str | Path,
    *,
    use_heuristic: bool = True,
) -> Callable[[Any], list[int]]:
    """Build an in-process surrogate ``agent(obs) -> list[int]``.

    On a deck-selection step the supplied deck is returned; otherwise the shared
    safe heuristic policy decides. Never raises outward.
    """
    ids = _coerce_deck(deck)
    from ..runtime.agent_core import make_agent

    inner = make_agent(use_heuristic=use_heuristic, enable_search=False)

    def agent(obs: Any) -> list[int]:
        try:
            if _is_deck_selection_step(obs):
                return list(ids)
            return inner(obs)
        except Exception:
            return []

    return agent


def materialize_surrogate_agent(
    deck: list[int] | str | Path,
    dest_dir: str | Path,
    *,
    brain: str | Path | None = None,
) -> Path:
    """Write a runnable cabt agent directory and return its ``main.py`` path.

    ``dest_dir`` receives a ``deck.csv`` (the surrogate's 60-card deck, one id per
    line) and a ``main.py`` copied from ``brain`` (a self-contained, stdlib-only
    heuristic). cabt reads ``deck.csv`` from the agent's own directory at startup.
    """
    ids = _coerce_deck(deck)
    brain_path = Path(brain) if brain else DEFAULT_BRAIN
    if not brain_path.exists():
        raise FileNotFoundError(f"surrogate brain template not found: {brain_path}")

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(brain_path, dest / "main.py")
    (dest / "deck.csv").write_text(
        "\n".join(str(c) for c in ids) + "\n", encoding="utf-8"
    )
    return dest / "main.py"
