"""Public Kaggle reference-agent registry (Pass 40).

Single source of truth for the *public* Kaggle agents we intake as **benchmark
opponents only**. These are NOT our candidates: they are never uploaded, never
submitted, never promoted, never mutated, never counted toward the active cap, the
submission queue, the mutation lineage, the family-champion set, or any "our best"
ranking. They exist solely so our own gameplay can be calibrated against known
public typed (cg-SDK) agents in the *local* cabt harness.

Everything here is descriptive metadata; importing this module performs no I/O and
touches no Kaggle endpoint.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# --- reference-agent status lane -------------------------------------------------
# The single status used to register reference agents in the tournament pool. It is
# deliberately NOT a member of pool.SCHEDULABLE_STATUSES (so it never counts toward
# the active cap / rankings / lifecycle), but the benchmark scheduler may pair it as
# an *opponent*. See src/ptcg_activegraph/tournament/pool.py.
EXTERNAL_REFERENCE_STATUS = "external_reference"

# --- competition context (read-only; both confirmed to exist & entered) ----------
COMPETITIONS = {
    "primary": "pokemon-tcg-ai-battle",
    "strategy_challenge": "pokemon-tcg-ai-battle-challenge-strategy",
}


@dataclass(frozen=True)
class ReferenceAgentSpec:
    """A public Kaggle agent intaken as a benchmark opponent."""

    agent_id: str          # canonical pool id, e.g. public_ref_kiyotah_mega_lucario
    label: str             # display label,    e.g. public_reference_mega_lucario
    kaggle_ref: str        # owner/kernel-slug
    author: str            # kaggle username (owner of the kernel)
    author_display: str    # display name as shown on Kaggle
    source_kind: str       # host_public_sample | public_competitor_notebook
    deck_archetype: str    # human archetype label
    title: str             # kernel title
    optional: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def owner(self) -> str:
        return self.kaggle_ref.split("/", 1)[0]

    @property
    def slug(self) -> str:
        return self.kaggle_ref.split("/", 1)[1]


# Order is stable & deterministic. The four kiyotah host samples are the canonical
# benchmark set; the ryotasueyoshi notebook is OPTIONAL (best-effort) public
# competitor context.
REFERENCE_AGENTS: tuple[ReferenceAgentSpec, ...] = (
    ReferenceAgentSpec(
        agent_id="public_ref_kiyotah_mega_lucario",
        label="public_reference_mega_lucario",
        kaggle_ref="kiyotah/a-sample-rule-based-agent-mega-lucario-ex-deck",
        author="kiyotah", author_display="Kiyota",
        source_kind="host_public_sample",
        deck_archetype="Mega Lucario ex",
        title="A Sample Rule-Based Agent Mega Lucario ex Deck",
        tags=("public_benchmark", "external_reference", "host_public_sample"),
    ),
    ReferenceAgentSpec(
        agent_id="public_ref_kiyotah_mega_abomasnow",
        label="public_reference_mega_abomasnow",
        kaggle_ref="kiyotah/a-sample-rule-based-agent-mega-abomasnow-ex-deck",
        author="kiyotah", author_display="Kiyota",
        source_kind="host_public_sample",
        deck_archetype="Mega Abomasnow ex",
        title="A Sample Rule-Based Agent Mega Abomasnow ex Deck",
        tags=("public_benchmark", "external_reference", "host_public_sample"),
    ),
    ReferenceAgentSpec(
        agent_id="public_ref_kiyotah_dragapult",
        label="public_reference_dragapult",
        kaggle_ref="kiyotah/a-sample-rule-based-agent-dragapult-ex-deck",
        author="kiyotah", author_display="Kiyota",
        source_kind="host_public_sample",
        deck_archetype="Dragapult ex",
        title="A Sample Rule-Based Agent Dragapult ex Deck",
        tags=("public_benchmark", "external_reference", "host_public_sample"),
    ),
    ReferenceAgentSpec(
        agent_id="public_ref_kiyotah_iono",
        label="public_reference_iono",
        kaggle_ref="kiyotah/a-sample-rule-based-agent-iono-s-deck",
        author="kiyotah", author_display="Kiyota",
        source_kind="host_public_sample",
        deck_archetype="Iono's deck",
        title="A Sample Rule-Based Agent Iono's Deck",
        tags=("public_benchmark", "external_reference", "host_public_sample"),
    ),
    ReferenceAgentSpec(
        agent_id="public_ref_ryotasueyoshi_alakazam",
        label="public_reference_alakazam",
        kaggle_ref="ryotasueyoshi/rule-based-not-psychic-alakazam-best-5th",
        author="ryotasueyoshi", author_display="sue124",
        source_kind="public_competitor_notebook",
        deck_archetype="Alakazam (rule-based)",
        title="Rule-based, not psychic: Alakazam (Best: 5th)",
        optional=True,
        tags=("public_benchmark", "external_reference",
              "public_competitor_notebook", "optional"),
    ),
)

REQUIRED_AGENTS: tuple[ReferenceAgentSpec, ...] = tuple(
    a for a in REFERENCE_AGENTS if not a.optional)
OPTIONAL_AGENTS: tuple[ReferenceAgentSpec, ...] = tuple(
    a for a in REFERENCE_AGENTS if a.optional)


def by_id(agent_id: str) -> ReferenceAgentSpec | None:
    for a in REFERENCE_AGENTS:
        if a.agent_id == agent_id:
            return a
    return None
