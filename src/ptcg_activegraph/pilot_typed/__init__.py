"""Pass 35 typed board-aware strategy layer (lab source of truth).

These modules are standard-library only so the compiler can embed their source
verbatim into a stdlib-only candidate ``main.py`` (embed-not-import). The runtime
never imports ``src.ptcg_activegraph``; the lab package exists so fixtures grade the
exact code that ships.

Layer map:
  - board.py     : pure typed board view over a raw cabt ``obs_dict``
  - metadata.py  : lookups over an inlined per-card metadata table
  - tactics.py   : deterministic, never-raising decision primitives
  - profiles.py  : StrategyProfile access/validation
  - decisions.py : per-context decision routing (graded by fixtures)
  - compiler.py  : emit a PASS35 typed override block onto a base ``main.py``
"""
from __future__ import annotations

__all__ = ["board", "metadata", "tactics", "profiles", "decisions"]
