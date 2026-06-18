"""Compile a declarative playbook into a stdlib-only candidate run directory.

The generated ``main.py`` is the **root** runtime agent (self-contained,
standard-library only) with the *proven* Pass-8 effect-safety block injected,
parameterised by the playbook's rules. The generated file imports no ``src``
module: the safety block is rendered as inline source text. The compiler itself
(a build tool) may import ``src`` freely.

A candidate directory contains:
    main.py        -- root agent + injected playbook rules (stdlib-only)
    deck.csv       -- copied from the baseline (identical to the control deck)
    playbook.yaml  -- the source playbook (provenance)
    branch.yaml    -- the experiment Branch record
    report.md      -- human summary of the compiled strategy
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from ..experiments.branch import Branch, make_run_dir, write_branch_yaml
from ..experiments.generator import (
    inject_deck_safety,
    inject_override,
    render_p8_block,
)
from .loader import load_playbook
from .report import playbook_report_summary, render_summary_md
from .schema import RULE_MAP
from .validator import validate_playbook

ROOT_MAIN = "main.py"
DEFAULT_BASELINE = "data/baselines/v2_kaggle_479_1_deck_energy_trim_light"
DEFAULT_RUNS_ROOT = "experiments/runs_pass9"


def compile_rules(playbook: dict) -> dict:
    """Derive the Pass-8 effect-safety rule dict from a playbook.

    Only rules whose source section/key is present and truthy (or, for the
    integer threshold, a real int) are emitted, so an ablation that drops a
    section simply drops that guard.
    """
    rules: dict = {}
    for rule, (section, key) in RULE_MAP.items():
        sec = playbook.get(section)
        if not isinstance(sec, dict):
            continue
        val = sec.get(key)
        if rule == "deckout_decline_threshold":
            if isinstance(val, int) and not isinstance(val, bool):
                rules[rule] = val
        else:
            if val is True:
                rules[rule] = True
    return rules


def compile_playbook(playbook_path: str | Path,
                     candidate_id: str,
                     runs_root: str | Path = DEFAULT_RUNS_ROOT,
                     baseline_dir: str | Path = DEFAULT_BASELINE,
                     root_main: str | Path = ROOT_MAIN,
                     hypothesis: str | None = None,
                     seam_id: str = "policy.playbook_effect_safety",
                     ts: str | None = None) -> Path:
    """Validate + compile a playbook into a candidate run directory.

    Returns the run directory path. Raises ``ValueError`` if the playbook fails
    validation (so a broken playbook never produces a candidate).
    """
    playbook_path = Path(playbook_path)
    playbook = load_playbook(playbook_path)

    baseline_dir = Path(baseline_dir)
    baseline_deck = baseline_dir / "deck.csv"
    deck_ids = _load_deck_ids(baseline_deck)

    result = validate_playbook(playbook, deck_ids=deck_ids)
    if not result.valid:
        raise ValueError(
            f"playbook {playbook_path} failed validation: "
            + "; ".join(result.errors))

    rules = compile_rules(playbook)

    # Generated main.py = root agent + injected playbook rules (stdlib-only).
    baseline_src = Path(root_main).read_text(encoding="utf-8")
    block = render_p8_block(candidate_id, seam_id, rules)
    candidate_src = inject_override(baseline_src, block)
    # Hard packaging requirement: every generated candidate must return its own
    # 60-card deck on the cabt deck-selection step regardless of cwd/file I/O.
    candidate_src = inject_deck_safety(candidate_src, deck_ids)

    run_dir = make_run_dir(candidate_id, root=runs_root, ts=ts)
    (run_dir / "main.py").write_text(candidate_src, encoding="utf-8")
    shutil.copyfile(baseline_deck, run_dir / "deck.csv")
    shutil.copyfile(playbook_path, run_dir / "playbook.yaml")

    summary = playbook_report_summary(playbook, rules)
    (run_dir / "report.md").write_text(
        render_summary_md(summary)
        + f"\n## Candidate\n- id: `{candidate_id}`\n"
        + f"- baseline deck: `{baseline_dir}`\n"
        + f"- hypothesis: {hypothesis or playbook.get('gameplan', {})}\n",
        encoding="utf-8",
    )

    branch = Branch(
        branch_id=candidate_id,
        seam_id=seam_id,
        family="playbook",
        kind="policy",
        archetype="effect_safety",
        hypothesis=hypothesis or f"Playbook candidate compiled from "
        f"{playbook_path.name}",
        parent="v2_kaggle_479_1_deck_energy_trim_light",
        run_dir=str(run_dir),
        policy_overrides={"p8_rules": dict(rules),
                          "playbook": playbook.get("deck_id")},
        policy_diff={"p8_rules": dict(rules)},
        deck_diff={},
        deck_summary={
            "size": len(deck_ids),
            "unique": len(set(deck_ids)),
            "deck_ref": playbook.get("baseline_id"),
            "board_aware": True,
            "source": "playbook",
        },
        notes=[f"playbook {playbook_path.name} -> p8_rules {sorted(rules)}"],
    )
    write_branch_yaml(branch, run_dir)
    return run_dir


def _load_deck_ids(deck_csv: str | Path) -> list[int]:
    p = Path(deck_csv)
    ids: list[int] = []
    if not p.exists():
        return ids
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.lower().startswith("card") or line.lower() == "id":
            continue
        token = line.split(",")[0].strip()
        try:
            ids.append(int(token))
        except ValueError:
            continue
    return ids
