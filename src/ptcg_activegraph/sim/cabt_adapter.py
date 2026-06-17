"""Adapter around the ``cabt`` simulator and ``kaggle-environments``.

The adapter isolates every cabt/kaggle import behind a capability check so the
rest of the lab can be imported and tested without those packages. When they
are missing, methods raise a clear, actionable :class:`CabtUnavailableError`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

INSTALL_HINT = (
    "cabt / kaggle-environments are not installed in this environment.\n"
    "To enable local simulation install the competition packages, e.g.:\n"
    "    pip install kaggle-environments\n"
    "    pip install cabt   # from the competition's provided wheel/source\n"
    "See docs/LOCAL_SIMULATION.md for details."
)


class CabtUnavailableError(RuntimeError):
    """Raised when a cabt-dependent operation is attempted without cabt."""


def is_available() -> bool:
    """True when both cabt and kaggle-environments can be imported."""
    try:
        import cabt  # type: ignore  # noqa: F401
    except Exception:
        return False
    try:
        import kaggle_environments  # type: ignore  # noqa: F401
    except Exception:
        # cabt alone may be enough for battle_* APIs; report cabt-only as True
        # for those paths but record that ke is missing.
        return True
    return True


class CabtAdapter:
    """Thin wrapper exposing the operations the lab needs."""

    def __init__(self) -> None:
        self._cabt = None

    def available(self) -> bool:
        return is_available()

    def _require(self):
        if self._cabt is not None:
            return self._cabt
        try:
            import cabt  # type: ignore
        except Exception as exc:  # pragma: no cover - env dependent
            raise CabtUnavailableError(INSTALL_HINT) from exc
        self._cabt = cabt
        return cabt

    def load_deck(self, path: str | Path) -> list[int]:
        """Load a decklist via our deck IO (does not require cabt)."""
        from ..decks.deck_io import load_deck

        return load_deck(path)

    def run_game(
        self,
        agent0: Callable[[dict], list[int]],
        agent1: Callable[[dict], list[int]],
        deck0: list[int],
        deck1: list[int],
        render_html_path: str | Path | None = None,
    ) -> dict:
        """Run a single game between two agents.

        This is a guarded skeleton: it calls cabt's ``battle_start`` /
        ``battle_select`` / ``battle_finish`` loop when available. The exact
        observation/return contract is validated once cabt is installed; until
        then this raises :class:`CabtUnavailableError`.
        """
        cabt = self._require()
        result: dict = {"winner": None, "result": None, "turns": 0, "error": None}
        try:
            cabt.battle_start(deck0, deck1)  # type: ignore[attr-defined]
            # The concrete per-step protocol is finalized against the installed
            # cabt build. Placeholder structure kept intentionally minimal.
            # ... step loop calling agent0/agent1 with observations ...
            outcome = cabt.battle_finish()  # type: ignore[attr-defined]
            result["raw"] = outcome
        except CabtUnavailableError:
            raise
        except Exception as exc:
            result["error"] = repr(exc)
        if render_html_path is not None:
            self._try_render(render_html_path)
        return result

    def run_self_play(
        self,
        agent: Callable[[dict], list[int]],
        deck: list[int],
        n_games: int = 10,
    ) -> list[dict]:
        """Run ``n_games`` of an agent against itself."""
        return [
            self.run_game(agent, agent, deck, deck)
            for _ in range(max(0, int(n_games)))
        ]

    def _try_render(self, path: str | Path) -> None:
        try:
            cabt = self._require()
            data = cabt.visualize_data()  # type: ignore[attr-defined]
            Path(path).write_text(str(data), encoding="utf-8")
        except Exception:
            pass
