"""ptcg_activegraph: ActiveGraph-powered Pokémon TCG AI Battle lab.

Two-system architecture:

* ``runtime`` — the compact, fast, deterministic, self-contained policy that
  the Kaggle agent runs. Standard-library only, never crashes outward.
* everything else (``graph``, ``regimes``, ``cards``, ``decks``, ``sim``,
  ``reporting``, ``packaging``) — the *lab*: an event-sourced experiment
  factory that records matches, classifies failures, validates patches and
  promotes improvements back into the runtime.

See ``docs/ARCHITECTURE.md`` for the full rationale.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
