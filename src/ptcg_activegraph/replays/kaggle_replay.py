"""Parse a Kaggle cabt episode replay JSON into a queryable structure.

A Kaggle episode JSON for the ``cabt`` environment looks roughly like::

    {
      "id": 80374966,
      "name": "cabt",
      "version": "...",
      "configuration": {"actTimeout": 1, "runTimeout": ..., "episodeSteps": 10000, ...},
      "rewards": [-1, 1],
      "statuses": ["DONE", "DONE"],
      "steps": [
        [ {"observation": {...}, "action": [...], "status": "ACTIVE", "reward": 0}, {...} ],
        ...
      ],
      "info": {...}
    }

The parser is defensive: every field is optional and missing pieces become
``None`` rather than raising, because partial / future replay shapes must still
yield a best-effort analysis instead of a crash.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ReplayNotFound(FileNotFoundError):
    """Raised when the requested replay file does not exist."""


@dataclass
class KaggleReplay:
    """A thin, defensive view over a raw Kaggle episode JSON."""

    raw: dict = field(default_factory=dict)
    source_path: str | None = None

    # -- episode-level accessors ------------------------------------------
    @property
    def info(self) -> dict:
        i = self.raw.get("info")
        return i if isinstance(i, dict) else {}

    @property
    def episode_id(self) -> Any:
        # The numeric Kaggle EpisodeId lives under info; the top-level ``id`` is
        # an opaque uuid. Prefer the EpisodeId, fall back to the uuid.
        eid = self.info.get("EpisodeId")
        return eid if eid is not None else self.raw.get("id")

    @property
    def name(self) -> Any:
        return self.raw.get("name")

    @property
    def module_version(self) -> Any:
        # cabt episodes carry the engine build under ``module_version``; the
        # plain ``version`` field is the replay-schema version (e.g. "1.0.0").
        mv = self.raw.get("module_version")
        return mv if mv is not None else self.raw.get("version")

    @property
    def schema_version(self) -> Any:
        return self.raw.get("schema_version")

    @property
    def configuration(self) -> dict:
        cfg = self.raw.get("configuration")
        return cfg if isinstance(cfg, dict) else {}

    @property
    def rewards(self) -> list:
        r = self.raw.get("rewards")
        return list(r) if isinstance(r, list) else []

    @property
    def statuses(self) -> list:
        s = self.raw.get("statuses")
        return list(s) if isinstance(s, list) else []

    @property
    def steps(self) -> list:
        s = self.raw.get("steps")
        return s if isinstance(s, list) else []

    @property
    def num_steps(self) -> int:
        return len(self.steps)

    @property
    def act_timeout(self) -> Any:
        return self.configuration.get("actTimeout")

    @property
    def run_timeout(self) -> Any:
        return self.configuration.get("runTimeout")

    @property
    def episode_steps(self) -> Any:
        return self.configuration.get("episodeSteps")

    def final_result(self) -> dict:
        """Best-effort winner determination from rewards/statuses."""
        rewards = self.rewards
        winner = None
        if len(rewards) == 2 and all(isinstance(x, (int, float)) for x in rewards):
            if rewards[0] > rewards[1]:
                winner = 0
            elif rewards[1] > rewards[0]:
                winner = 1
            else:
                winner = None  # tie / both equal
        return {
            "rewards": rewards,
            "statuses": self.statuses,
            "winner_seat": winner,
            "draw": (len(rewards) == 2 and rewards[0] == rewards[1]),
        }

    def agent_steps(self, seat: int) -> list[dict]:
        """All per-step records for one seat (defensive over ragged steps)."""
        out: list[dict] = []
        for step in self.steps:
            if isinstance(step, list) and len(step) > seat and isinstance(step[seat], dict):
                out.append(step[seat])
        return out

    def submitted_decks(self) -> dict[int, list[int]]:
        """Per-seat submitted deck lists.

        In cabt the deck is submitted as a >=40-length integer ``action`` (the
        full 60-card id list) on the first step where the seat acts. Returns a
        ``{seat: [card_id, ...]}`` map; seats with no recognizable deck action
        are omitted rather than guessed.
        """
        decks: dict[int, list[int]] = {}
        for step in self.steps:
            if not isinstance(step, list):
                continue
            for seat, rec in enumerate(step):
                if seat in decks or not isinstance(rec, dict):
                    continue
                action = rec.get("action")
                if isinstance(action, list) and len(action) >= 40:
                    ids = [a for a in action if isinstance(a, int) and not isinstance(a, bool)]
                    if len(ids) >= 40:
                        decks[seat] = ids
        return decks

    def final_observation(self, seat: int) -> dict | None:
        """Last non-empty observation dict for a seat (for final-state reads)."""
        for rec in reversed(self.agent_steps(seat)):
            obs = rec.get("observation")
            if isinstance(obs, dict) and obs.get("current"):
                return obs
        return None


def _coerce_json(text: str) -> dict:
    """Parse a replay payload that may be a dict, a list, or JSON-lines."""
    text = text.strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try JSON-lines: take the first object-looking line.
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}
    if isinstance(data, list):
        # Some exporters wrap the episode in a single-element list.
        for item in data:
            if isinstance(item, dict):
                return item
        return {}
    return data if isinstance(data, dict) else {}


def load_replay(path: str | Path) -> KaggleReplay:
    """Load + parse a replay file. Raises ``ReplayNotFound`` if absent."""
    p = Path(path)
    if not p.exists():
        raise ReplayNotFound(str(p))
    raw = _coerce_json(p.read_text(encoding="utf-8"))
    return KaggleReplay(raw=raw, source_path=str(p))


def parse_replay(raw: dict, source_path: str | None = None) -> KaggleReplay:
    """Wrap an already-loaded raw dict (useful for tests/fixtures)."""
    return KaggleReplay(raw=raw if isinstance(raw, dict) else {}, source_path=source_path)
