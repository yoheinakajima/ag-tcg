"""Kaggle/cabt smoke test: run one real self-play game end-to-end.

The goal of the first Replit/Kaggle run is *not* a strong bot — it is to confirm
that `kaggle_environments.make("cabt", ...)` builds, the deck loads, `main.agent`
is callable, and `env.run([agent, agent])` completes without crashing or timing
out. This module degrades with a specific, non-generic status when anything is
missing.

It emits ActiveGraph events (SmokeTestStarted/DeckResolved/SmokeGameStarted/
SmokeGameFinished/SmokeTestFailed) when an event store is provided, for lineage.
"""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# Status codes (stable strings for scripting/CI).
PASS = "PASS"
FAIL_KE_MISSING = "FAIL: kaggle_environments unavailable"
FAIL_CABT_MISSING = "FAIL: cabt environment unavailable"
FAIL_DECK_INVALID = "FAIL: deck invalid"
FAIL_IMPORT = "FAIL: agent import error"
FAIL_RUNTIME = "FAIL: runtime exception"


@dataclass
class SmokeResult:
    status: str
    detail: str = ""
    deck_size: int = 0
    games: int = 0
    artifacts: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.status == PASS

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "detail": self.detail,
            "deck_size": self.deck_size,
            "games": self.games,
            "artifacts": self.artifacts,
            "error": self.error,
        }


def kaggle_environments_available() -> bool:
    try:
        import kaggle_environments  # type: ignore  # noqa: F401
        return True
    except Exception:
        return False


def _emit(store, event_type, **kw):
    if store is None:
        return
    try:
        from ..graph.events import new_event
        store.append(new_event(event_type, **kw))
    except Exception:
        pass


def run_smoke_test(
    agent: Callable[[dict], list],
    deck: list[int],
    games: int = 1,
    out_dir: str | Path = "data/matches",
    event_store: Any = None,
    match_id: str = "smoke",
) -> SmokeResult:
    """Run ``games`` self-play game(s) in the cabt env. Never raises."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    _emit(event_store, "SmokeTestStarted", match_id=match_id,
          payload={"games": games, "deck_size": len(deck)})

    # Deck sanity (cheap local check before involving the engine).
    if not deck or len(deck) != 60 or not all(isinstance(c, int) for c in deck):
        res = SmokeResult(FAIL_DECK_INVALID, detail=f"deck has {len(deck)} entries",
                          deck_size=len(deck))
        _emit(event_store, "SmokeTestFailed", match_id=match_id, payload=res.to_dict())
        return res
    _emit(event_store, "DeckResolved", match_id=match_id,
          payload={"deck_size": len(deck)})

    if not kaggle_environments_available():
        res = SmokeResult(
            FAIL_KE_MISSING,
            detail="pip install kaggle-environments (see docs/REPLIT_FIRST_RUN.md)",
            deck_size=len(deck),
        )
        _emit(event_store, "SmokeTestFailed", match_id=match_id, payload=res.to_dict())
        return res

    try:
        from kaggle_environments import make  # type: ignore
    except Exception as exc:  # noqa: BLE001
        res = SmokeResult(FAIL_KE_MISSING, detail=repr(exc), deck_size=len(deck))
        _emit(event_store, "SmokeTestFailed", match_id=match_id, payload=res.to_dict())
        return res

    # Build the cabt environment. The exact configuration key may evolve; try a
    # few shapes before giving up.
    env = None
    config_attempts = (
        {"decks": [deck, deck]},
        {"deck": deck},
        {},
    )
    last_err = None
    for cfg in config_attempts:
        try:
            env = make("cabt", configuration=cfg)
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            continue
    if env is None:
        res = SmokeResult(
            FAIL_CABT_MISSING,
            detail=f"make('cabt', ...) failed: {last_err!r}",
            deck_size=len(deck),
        )
        _emit(event_store, "SmokeTestFailed", match_id=match_id, payload=res.to_dict())
        return res

    _emit(event_store, "SmokeGameStarted", match_id=match_id,
          payload={"games": games})

    completed = 0
    try:
        for _ in range(max(1, games)):
            env.run([agent, agent])
            completed += 1
    except Exception as exc:  # noqa: BLE001
        res = SmokeResult(
            FAIL_RUNTIME,
            detail=repr(exc),
            deck_size=len(deck),
            games=completed,
            error=traceback.format_exc(),
        )
        _emit(event_store, "SmokeTestFailed", match_id=match_id, payload=res.to_dict())
        return res

    artifacts: dict = {}
    # Save a JSON summary.
    summary_path = out_dir / "smoke_result.json"
    try:
        summary = {"status": PASS, "games": completed, "deck_size": len(deck)}
        try:
            summary["steps"] = len(getattr(env, "steps", []) or [])
        except Exception:
            pass
        summary_path.write_text(json.dumps(summary, indent=2, default=str),
                                encoding="utf-8")
        artifacts["summary"] = str(summary_path)
    except Exception:
        pass

    # Save an HTML render if the env supports it.
    try:
        html = env.render(mode="html")  # type: ignore[call-arg]
        if html:
            html_path = out_dir / "smoke_result.html"
            html_path.write_text(str(html), encoding="utf-8")
            artifacts["html"] = str(html_path)
    except Exception:
        pass

    res = SmokeResult(PASS, detail=f"completed {completed} game(s)",
                      deck_size=len(deck), games=completed, artifacts=artifacts)
    _emit(event_store, "SmokeGameFinished", match_id=match_id, payload=res.to_dict())
    return res
