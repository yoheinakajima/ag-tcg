"""Core pilot competency layer (Pass 14).

Layered Pokémon-TCG pilot (see docs/CORE_PILOT_ARCHITECTURE.md):
  * Layer 1 — :mod:`.state`     normalized board readers over a cabt observation.
  * Layer 2 — :mod:`.scoring`   deck-agnostic, role/mechanics based option scoring.
  * Layer 2 — :mod:`.decisions` turn scores into legal, deterministic selections.
  * Layer 3 — :mod:`.roles`     card-role index built from a deck playbook.
  * tooling — :mod:`.fixtures`  reduced-model fixture loading + grading.
  * tooling — :mod:`.compiler`  embed the layers into a stdlib-only candidate main.py.
"""
from __future__ import annotations

from ptcg_activegraph.pilot import (  # noqa: F401
    compiler,
    decisions,
    fixtures,
    roles,
    scoring,
    state,
)
from ptcg_activegraph.pilot.decisions import core_pilot_decide, decide  # noqa: F401
from ptcg_activegraph.pilot.roles import load_playbook_roles  # noqa: F401
from ptcg_activegraph.pilot.state import build_board  # noqa: F401

__all__ = [
    "state",
    "roles",
    "scoring",
    "decisions",
    "fixtures",
    "compiler",
    "decide",
    "core_pilot_decide",
    "load_playbook_roles",
    "build_board",
]
