"""Reporting: metrics and the Strategy report generator."""

from .metrics import compute_metrics
from .report_generator import generate_strategy_report

__all__ = ["compute_metrics", "generate_strategy_report"]
