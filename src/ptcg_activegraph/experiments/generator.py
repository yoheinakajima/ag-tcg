"""Candidate generation: policy variants and deck variants.

Two tracks:

* **Policy candidates** — take the baseline ``main.py`` source and inject a
  small, append-only override block that reassigns scoring constants
  (``_OPTION_TYPE_SCORES``, ``_ATTACK_ID_BONUS``, ``_POSITIVE``, ``_NEGATIVE``).
  These helpers are read at call time via module globals, so the injected block
  (placed just before ``if __name__ == "__main__":``) changes behaviour without
  editing any existing line. The result stays standard-library-only,
  self-contained, and keeps the ``select=None`` deck-return behaviour.

* **Deck candidates** — start from the baseline 60-card list and apply signed
  per-card-id deltas grounded in ``data/cards/EN_Card_Data.csv``. We never
  invent card ids: every id used already appears in the baseline deck. Basic
  energy (the only card allowed > 4 copies) is the trim source; non-energy
  cards are only bumped from an existing count of 2 up to at most 4, so deck
  legality holds. Every generated deck is still re-validated and smoke-tested
  before it can be ranked.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ..decks.deck_io import load_deck, save_deck
from .branch import Branch, make_run_dir, write_branch_yaml
from .config import ExperimentConfig

_INJECT_ANCHOR = 'if __name__ == "__main__":'

# Baseline card identities (confirmed from data/cards/EN_Card_Data.csv). Used
# only for human-readable hypotheses and to pick which counts to adjust; the
# generator never relies on these for legality (the validator + smoke do).
CARD_NAMES = {
    3: "Basic {W} Energy",
    721: "Kyogre",
    722: "Snover",
    723: "Mega Abomasnow ex",
    1092: "Secret Box",
    1121: "Ultra Ball",
    1145: "Mega Signal",
    1163: "Powerglass",
    1219: "Team Rocket's Petrel",
    1227: "Lillie's Determination",
    1262: "Surfing Beach",
}
ENERGY_ID = 3


# ---------------------------------------------------------------------------
# Policy candidate specs
# ---------------------------------------------------------------------------
# Each override key maps to an injected statement:
#   option_type_scores -> _OPTION_TYPE_SCORES.update({...})
#   attack_id_bonus    -> _ATTACK_ID_BONUS = <int>
#   positive           -> _POSITIVE.update({...})
#   negative           -> _NEGATIVE.update({...})

POLICY_SPECS: list[dict] = [
    {
        "branch_id": "policy_attack_heavy",
        "seam_id": "policy.attack_priority",
        "archetype": "linear_aggro",
        "hypothesis": "Strongly preferring confirmed attacks (type 13) and "
        "knockouts should raise attack rate and shorten games without crashing.",
        "overrides": {
            "option_type_scores": {13: 220, 14: -90},
            "attack_id_bonus": 70,
            "positive": {"attack": 140, "knockout": 170, "knock": 150},
        },
    },
    {
        "branch_id": "policy_pass_avoidant",
        "seam_id": "policy.pass_avoidance",
        "archetype": "linear_aggro",
        "hypothesis": "Heavier penalties on pass/end (type 14) options should "
        "cut the pass rate and keep the agent acting when real plays exist.",
        "overrides": {
            "option_type_scores": {14: -160},
            "negative": {"pass": -260, "end": -260, "done": -220},
        },
    },
    {
        "branch_id": "policy_evolution_bias",
        "seam_id": "policy.evolution_priority",
        "archetype": "setup_evolution",
        "hypothesis": "Biasing toward evolve/evolution options should help the "
        "Snover -> Mega Abomasnow ex line set up before attacking.",
        "overrides": {
            "positive": {"evolve": 95, "evolution": 90},
        },
    },
    {
        "branch_id": "policy_energy_bias",
        "seam_id": "policy.energy_priority",
        "archetype": "setup_evolution",
        "hypothesis": "Prioritising attach/energy (and placement type 8) when no "
        "attack is available should accelerate powering up attackers.",
        "overrides": {
            "option_type_scores": {8: 28},
            "positive": {"attach": 85, "energy": 85},
        },
    },
    {
        "branch_id": "policy_draw_search_bias",
        "seam_id": "policy.search_targeting",
        "archetype": "consistency_engine",
        "hypothesis": "Boosting draw/search/supporter/item preference should "
        "improve setup consistency turn over turn.",
        "overrides": {
            "positive": {"draw": 85, "search": 85, "supporter": 70, "item": 60},
        },
    },
    {
        "branch_id": "policy_bench_pressure",
        "seam_id": "policy.bench_pressure",
        "archetype": "linear_aggro",
        "hypothesis": "Favouring placement (type 8) builds a wider bench earlier, "
        "giving more attackers to promote after a knockout.",
        "overrides": {
            "option_type_scores": {8: 45},
            "positive": {"bench": 60},
        },
    },
    {
        "branch_id": "policy_setup_evolution",
        "seam_id": "archetype.setup_evolution",
        "archetype": "setup_evolution",
        "hypothesis": "A combined evolution + energy setup tilt should reach the "
        "Mega Abomasnow ex line faster, trading early tempo for ceiling.",
        "overrides": {
            "option_type_scores": {8: 24},
            "positive": {"evolve": 90, "evolution": 85, "attach": 75, "energy": 75},
        },
    },
    {
        "branch_id": "policy_conservative_baseline",
        "seam_id": "archetype.baseline_exploit",
        "archetype": "baseline_exploit",
        "hypothesis": "An exact copy of the v1 control (no overrides) anchors the "
        "batch and confirms the harness reproduces the baseline.",
        "overrides": {},
    },
]


# ---------------------------------------------------------------------------
# Deck candidate specs (deltas are signed per-card-id; sum must be 0)
# ---------------------------------------------------------------------------

DECK_SPECS: list[dict] = [
    {
        "branch_id": "deck_energy_trim_light",
        "seam_id": "deck.energy_trim",
        "archetype": "consistency_engine",
        "hypothesis": "Trimming 4 Basic {W} Energy for +2 Kyogre and +2 Ultra "
        "Ball keeps power online while adding an attacker and a search item.",
        "deltas": {ENERGY_ID: -4, 721: +2, 1121: +2},
    },
    {
        "branch_id": "deck_energy_trim_medium",
        "seam_id": "deck.energy_trim",
        "archetype": "consistency_engine",
        "hypothesis": "A larger 10-energy trim maxing Kyogre, Ultra Ball, Mega "
        "Signal, Powerglass and Surfing Beach to 4 should sharply raise "
        "consistency; watch for energy droughts.",
        "deltas": {ENERGY_ID: -10, 721: +2, 1121: +2, 1145: +2, 1163: +2, 1262: +2},
    },
    {
        "branch_id": "deck_baseline_consistency",
        "seam_id": "deck.consistency_engine",
        "archetype": "consistency_engine",
        "hypothesis": "Trimming 4 energy for +2 Ultra Ball and +2 Mega Signal "
        "maximises draw/search density for steadier setups.",
        "deltas": {ENERGY_ID: -4, 1121: +2, 1145: +2},
    },
    {
        "branch_id": "deck_attacker_focus",
        "seam_id": "deck.attacker_focus",
        "archetype": "linear_aggro",
        "hypothesis": "Trimming 2 energy for +2 Kyogre adds a second Basic "
        "attacker line (Snover/Mega Abomasnow ex already max at 4).",
        "deltas": {ENERGY_ID: -2, 721: +2},
    },
]

# Deck experiments confirmed-or-blocked but not generated this pass, with a
# transparent reason (no invented cards, no unconfirmed strategy).
DECK_BLOCKED: list[dict] = [
    {
        "branch_id": "deck_abomasnow_line_focus",
        "seam_id": "deck.abomasnow_line_focus",
        "archetype": "setup_evolution",
        "hypothesis": "Lean further into Snover -> Mega Abomasnow ex.",
        "blocked_reason": "card ids confirmed (Snover 722, Mega Abomasnow ex 723) "
        "but both are already at the 4-copy maximum in the baseline; nothing to add.",
    },
    {
        "branch_id": "deck_anti_baseline",
        "seam_id": "deck.anti_baseline",
        "archetype": "anti_meta",
        "hypothesis": "Tech specific counters against the mirror.",
        "blocked_reason": "no clear counter cards identified in metadata yet; "
        "would require inventing card ids.",
    },
]


# ---------------------------------------------------------------------------
# Override rendering / injection
# ---------------------------------------------------------------------------

def render_override_block(branch_id: str, seam_id: str, overrides: dict) -> str:
    """Render the append-only override block for a policy candidate."""
    lines = [f"\n# === EXPERIMENT OVERRIDE: {branch_id} (seam={seam_id}) ==="]
    if not overrides:
        lines.append("# (no overrides: exact v1 control copy)")
    if overrides.get("option_type_scores"):
        lines.append(f"_OPTION_TYPE_SCORES.update({_fmt(overrides['option_type_scores'])})")
    if overrides.get("attack_id_bonus") is not None:
        lines.append(f"_ATTACK_ID_BONUS = {int(overrides['attack_id_bonus'])}")
    if overrides.get("positive"):
        lines.append(f"_POSITIVE.update({_fmt(overrides['positive'])})")
    if overrides.get("negative"):
        lines.append(f"_NEGATIVE.update({_fmt(overrides['negative'])})")
    lines.append("# === END OVERRIDE ===\n")
    return "\n".join(lines)


def _fmt(d: dict) -> str:
    # Deterministic, valid-Python dict literal with int keys preserved.
    items = ", ".join(f"{k!r}: {v!r}" for k, v in d.items())
    return "{" + items + "}"


def inject_override(baseline_src: str, block: str) -> str:
    """Insert ``block`` just before the ``if __name__`` guard (or at EOF)."""
    idx = baseline_src.find(_INJECT_ANCHOR)
    if idx == -1:
        return baseline_src.rstrip() + "\n" + block + "\n"
    return baseline_src[:idx] + block + "\n\n" + baseline_src[idx:]


# ---------------------------------------------------------------------------
# Deck delta application
# ---------------------------------------------------------------------------

def apply_deck_deltas(baseline_ids: list[int], deltas: dict) -> list[int]:
    """Apply signed per-id deltas to a 60-card list; return a new sorted list."""
    counts = Counter(baseline_ids)
    for cid, delta in deltas.items():
        counts[int(cid)] = counts.get(int(cid), 0) + int(delta)
    out: list[int] = []
    for cid in sorted(counts):
        n = counts[cid]
        if n < 0:
            raise ValueError(f"delta drove card {cid} below zero ({n})")
        out.extend([cid] * n)
    return out


def _illegal_copy_counts(card_ids: list[int], card_db=None, max_copies: int = 4) -> dict:
    """Return {card_id: count} for non-basic-energy cards exceeding max_copies."""
    over: dict[int, int] = {}
    for cid, n in Counter(card_ids).items():
        if n <= max_copies:
            continue
        is_energy = cid == ENERGY_ID
        if not is_energy and card_db is not None:
            try:
                is_energy = bool(card_db.basic_features(cid).get("is_energy", False))
            except Exception:
                is_energy = False
        if not is_energy:
            over[cid] = n
    return over


def deck_diff(baseline_ids: list[int], new_ids: list[int]) -> dict:
    base, new = Counter(baseline_ids), Counter(new_ids)
    diff = {}
    for cid in sorted(set(base) | set(new)):
        d = new.get(cid, 0) - base.get(cid, 0)
        if d:
            diff[str(cid)] = {
                "name": CARD_NAMES.get(cid, f"card {cid}"),
                "from": base.get(cid, 0),
                "to": new.get(cid, 0),
                "delta": d,
            }
    return diff


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------

def generate_policy_candidate(
    spec: dict,
    baseline_main: str | Path,
    baseline_deck: str | Path,
    runs_root: str | Path,
    ts: str | None = None,
) -> Branch:
    """Write a policy candidate (baseline + override) into a fresh run dir."""
    baseline_src = Path(baseline_main).read_text(encoding="utf-8")
    block = render_override_block(spec["branch_id"], spec["seam_id"], spec["overrides"])
    candidate_src = inject_override(baseline_src, block)

    run_dir = make_run_dir(spec["branch_id"], root=runs_root, ts=ts)
    (run_dir / "main.py").write_text(candidate_src, encoding="utf-8")
    # Policy candidates reuse the exact baseline deck.
    deck_ids = load_deck(baseline_deck)
    save_deck(run_dir / "deck.csv", deck_ids)

    branch = Branch(
        branch_id=spec["branch_id"],
        seam_id=spec["seam_id"],
        family="policy" if spec["seam_id"].startswith("policy") else "archetype",
        kind="control" if not spec["overrides"] else "policy",
        archetype=spec.get("archetype", ""),
        hypothesis=spec["hypothesis"],
        run_dir=str(run_dir),
        policy_overrides=spec["overrides"],
        policy_diff=spec["overrides"],
        deck_summary={"source": "baseline", "size": len(deck_ids)},
    )
    write_branch_yaml(branch, run_dir)
    return branch


def generate_deck_candidate(
    spec: dict,
    baseline_main: str | Path,
    baseline_deck: str | Path,
    runs_root: str | Path,
    card_db=None,
    ts: str | None = None,
) -> Branch:
    """Write a deck candidate (baseline main + mutated deck) into a run dir."""
    from ..decks.validator import validate_deck

    baseline_ids = load_deck(baseline_deck)
    new_ids = apply_deck_deltas(baseline_ids, spec["deltas"])

    result = validate_deck(new_ids, card_db=card_db)
    if not result.valid:
        raise ValueError(
            f"generated deck for {spec['branch_id']} is invalid: "
            + "; ".join(result.errors)
        )
    # Strict copy-limit enforcement for candidates: the shared validator treats
    # "non-energy card > 4 copies" as a warning (so the baseline's many basic
    # energy never fail), but a generated candidate must NEVER exceed 4 copies of
    # any non-basic-energy card. Hard-fail here so an illegal deck can never be
    # packaged or queued.
    over = _illegal_copy_counts(new_ids, card_db)
    if over:
        raise ValueError(
            f"generated deck for {spec['branch_id']} exceeds 4 copies of "
            "non-energy card(s): "
            + ", ".join(f"{cid}x{n}" for cid, n in over.items())
        )

    run_dir = make_run_dir(spec["branch_id"], root=runs_root, ts=ts)
    # Deck candidates reuse the exact baseline runtime policy.
    Path(run_dir / "main.py").write_text(
        Path(baseline_main).read_text(encoding="utf-8"), encoding="utf-8"
    )
    save_deck(run_dir / "deck.csv", new_ids)

    diff = deck_diff(baseline_ids, new_ids)
    branch = Branch(
        branch_id=spec["branch_id"],
        seam_id=spec["seam_id"],
        family="deck_construction",
        kind="deck",
        archetype=spec.get("archetype", ""),
        hypothesis=spec["hypothesis"],
        run_dir=str(run_dir),
        deck_diff=diff,
        deck_summary={
            "size": len(new_ids),
            "unique": len(set(new_ids)),
            "warnings": result.warnings,
        },
    )
    write_branch_yaml(branch, run_dir)
    return branch


# ---------------------------------------------------------------------------
# Planning: which candidates are testable now, ordered by priority
# ---------------------------------------------------------------------------

def plan_candidates(config: ExperimentConfig) -> list[dict]:
    """Return all candidate specs annotated with testability and priority.

    Sorted by priority (desc). Each item: ``{spec, track, seam_id, priority,
    testable, reason}``. Blocked deck experiments are included with
    ``testable=False`` so the report can show them honestly.
    """
    plan: list[dict] = []

    def _annotate(spec: dict, track: str) -> dict:
        seam = config.seam(spec["seam_id"])
        testable, reason = (True, "")
        if seam is None:
            testable, reason = False, f"unknown seam {spec['seam_id']}"
        else:
            testable, reason = config.is_testable(seam)
        return {
            "spec": spec,
            "track": track,
            "seam_id": spec["seam_id"],
            "branch_id": spec["branch_id"],
            "priority": config.priority_for(spec["seam_id"]),
            "testable": testable,
            "reason": reason,
        }

    for spec in POLICY_SPECS:
        plan.append(_annotate(spec, "policy"))
    for spec in DECK_SPECS:
        plan.append(_annotate(spec, "deck"))
    for spec in DECK_BLOCKED:
        item = _annotate(spec, "deck")
        item["testable"] = False
        item["reason"] = spec.get("blocked_reason", item["reason"])
        plan.append(item)

    plan.sort(key=lambda x: (-x["priority"], x["branch_id"]))
    return plan
