"""Produce a human/JSON report summary of a playbook."""

from __future__ import annotations

from .schema import ROLE_SECTIONS, RULE_MAP, card_name


def playbook_report_summary(playbook: dict, rules: dict | None = None) -> dict:
    """Return a serializable summary of a playbook (and its compiled rules).

    Pure and defensive: tolerates missing sections so it can run during
    validation before a playbook is known-good.
    """
    if rules is None:
        from .compiler import compile_rules
        try:
            rules = compile_rules(playbook)
        except Exception:
            rules = {}

    roles = playbook.get("roles") or {}
    role_summary: dict[str, list[str]] = {}
    if isinstance(roles, dict):
        for sec in ROLE_SECTIONS:
            vals = roles.get(sec)
            if isinstance(vals, list):
                role_summary[sec] = [
                    f"{card_name(v)} ({v})" if isinstance(v, int)
                    and not isinstance(v, bool) else str(v)
                    for v in vals
                ]

    gameplan = playbook.get("gameplan") or {}
    return {
        "deck_id": playbook.get("deck_id"),
        "baseline_id": playbook.get("baseline_id"),
        "gameplan": {
            "primary": gameplan.get("primary") if isinstance(gameplan, dict) else None,
            "secondary": gameplan.get("secondary") if isinstance(gameplan, dict) else None,
            "avoid": gameplan.get("avoid") if isinstance(gameplan, dict) else None,
        },
        "roles": role_summary,
        "compiled_rules": dict(rules),
        "active_rule_count": len(rules),
        "fixture_requirements": playbook.get("fixture_requirements") or {},
        "report_notes": list(playbook.get("report_notes") or []),
    }


def render_summary_md(summary: dict) -> str:
    """Render the summary dict as a compact markdown block."""
    lines: list[str] = []
    lines.append(f"# Playbook: {summary.get('deck_id')}")
    lines.append("")
    lines.append(f"- baseline: `{summary.get('baseline_id')}`")
    gp = summary.get("gameplan", {})
    lines.append(f"- primary: {gp.get('primary')}")
    lines.append(f"- secondary: {gp.get('secondary')}")
    lines.append(f"- avoid: {gp.get('avoid')}")
    lines.append("")
    lines.append("## Roles")
    for sec, vals in (summary.get("roles") or {}).items():
        lines.append(f"- **{sec}**: {', '.join(vals)}")
    lines.append("")
    lines.append("## Compiled effect-safety rules")
    rules = summary.get("compiled_rules") or {}
    if not rules:
        lines.append("- (none)")
    for k, v in rules.items():
        lines.append(f"- `{k}` = {v}")
    notes = summary.get("report_notes") or []
    if notes:
        lines.append("")
        lines.append("## Report notes")
        for n in notes:
            lines.append(f"- {n}")
    return "\n".join(lines) + "\n"
