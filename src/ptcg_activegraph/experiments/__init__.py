"""ActiveGraph strategy lab: the experiment factory around the v1 baseline.

This subpackage turns the immutable Kaggle control baseline into a transparent
experiment loop:

    Idea -> Hypothesis -> Branch -> Deck/Policy Variant -> Local Evaluation ->
    Metrics -> Regime Classification -> Promotion Candidate -> Submission Queue
    -> Kaggle Result -> Report

Every step emits ActiveGraph events (see ``..graph.events``). The submitted
runtime (root ``main.py``/``deck.csv``) is never mutated; candidates are
generated into isolated run directories under ``experiments/runs/``.
"""

from .config import ExperimentConfig, Seam, load_config, load_plan, load_seams
from .branch import Branch

__all__ = [
    "ExperimentConfig",
    "Seam",
    "Branch",
    "load_config",
    "load_plan",
    "load_seams",
]
