"""Declarative deck-specific *playbook* architecture (ActiveGraph Pass 9).

A playbook makes a deck's strategy explicit and reportable: roles, gameplan,
opening rules, main-phase priorities, effect-resolution rules, discard/search
safety, deckout guard and attachment targeting. The :mod:`compiler` turns a
playbook into a **stdlib-only, self-contained** candidate ``main.py`` (the proven
Pass-8 effect-safety block, parameterised by the playbook) plus a candidate run
directory, without the generated file importing any ``src`` module.

Public surface:
    load_playbook        -- read + normalise a playbook YAML file
    validate_playbook    -- honest validation (returns ValidationResult)
    compile_rules        -- playbook -> Pass-8 effect-safety rule dict
    compile_playbook     -- write a full candidate run directory
    playbook_report_summary -- human/JSON summary of a playbook
"""

from __future__ import annotations

from .loader import load_playbook
from .validator import ValidationResult, validate_playbook
from .compiler import compile_rules, compile_playbook
from .report import playbook_report_summary
from .schema import CONFIRMED_CARDS, REQUIRED_FIELDS, card_name

__all__ = [
    "load_playbook",
    "ValidationResult",
    "validate_playbook",
    "compile_rules",
    "compile_playbook",
    "playbook_report_summary",
    "CONFIRMED_CARDS",
    "REQUIRED_FIELDS",
    "card_name",
]
