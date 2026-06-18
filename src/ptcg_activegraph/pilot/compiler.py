"""Compile the core-pilot layers into a stdlib-only candidate ``main.py``.

The lab modules (``state``, ``roles``, ``scoring``, ``decisions``) are the source of
truth. This compiler embeds their **standard-library-only** source plus the deck
playbook's role maps (as Python literals) into a PASS14 override block appended to a
base candidate ``main.py``. Because the fixtures grade the very ``core_pilot_decide``
this block emits, the deterministic gate tests exactly what ships.

Runtime integration is intentionally conservative: it preserves the proven Pass-8
effect-safety policy untouched and only *refines the search target* at the reliably
identifiable ToHand-search context (cabt ``select.context == 7``), deferring to the
base policy everywhere else and on any error.
"""
from __future__ import annotations

import tarfile
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

_PILOT_DIR = Path(__file__).resolve().parent
# Dependency order matters: later modules reference names from earlier ones.
_EMBED_MODULES = ("state.py", "roles.py", "scoring.py", "decisions.py")

_STRIP_PREFIXES = ("from __future__", "from ptcg_activegraph", "import ptcg_activegraph")


def _strip_module_source(path: Path) -> str:
    lines = []
    skipping_paren = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.lstrip()
        if skipping_paren:
            # Inside a stripped multi-line ``import (...)`` continuation.
            if ")" in line:
                skipping_paren = False
            continue
        if any(stripped.startswith(p) for p in _STRIP_PREFIXES):
            # Drop the import; if it opened a paren that isn't closed on this
            # line, keep dropping continuation lines until the closing paren.
            if "(" in line and ")" not in line:
                skipping_paren = True
            continue
        lines.append(line)
    return "\n".join(lines).strip("\n")


def _embedded_layer_source() -> str:
    parts = []
    for name in _EMBED_MODULES:
        src = _strip_module_source(_PILOT_DIR / name)
        parts.append("# ---- embedded: ptcg_activegraph/pilot/%s ----\n%s" % (name, src))
    return "\n\n\n".join(parts)


def load_playbook(playbook_path: Any) -> dict:
    if yaml is None:
        raise RuntimeError("PyYAML required to load a playbook")
    return yaml.safe_load(Path(playbook_path).read_text(encoding="utf-8")) or {}


def build_playbook_literal(playbook: dict, flags: dict | None = None) -> dict:
    """Reduce a loaded playbook to the minimal, JSON-safe dict the pilot consumes."""
    roles = {}
    for role, ids in (playbook.get("roles") or {}).items():
        roles[str(role)] = [int(c) for c in (ids or []) if isinstance(c, int)
                            and not isinstance(c, bool)]
    out = {
        "roles": roles,
        "plan": playbook.get("plan") or {},
        "deckout_guard_thresholds": playbook.get("deckout_guard_thresholds") or {},
        "role_weights": playbook.get("role_weights") or {},
        "exceptions": playbook.get("exceptions") or {},
    }
    merged_flags = dict(playbook.get("flags") or {})
    if flags:
        merged_flags.update(flags)
    if merged_flags:
        out["flags"] = merged_flags
    return out


def _render_block(playbook_literal: dict, candidate_id: str) -> str:
    layer_src = _embedded_layer_source()
    return f'''

# === PASS14 CORE-PILOT OVERRIDE: {candidate_id} ===
# Embeds the Layer 1-3 core-pilot decision layer (stdlib-only) plus this deck's
# role playbook. Exposes ``core_pilot_decide(kind, board, options)`` (graded by the
# core-competency fixtures) and conservatively refines the ToHand-search target at
# runtime while preserving the proven Pass-8 effect-safety policy beneath it.
from typing import Any as _CP_Any  # noqa: F401  (stdlib)

{layer_src}

_CP_PLAYBOOK = {playbook_literal!r}


def core_pilot_decide(kind, board, options, playbook=None):
    """Public decision entry; defaults to this deck's embedded playbook."""
    return decide(kind, board, options, playbook if playbook is not None else _CP_PLAYBOOK)


_CP_ORIG_EMBEDDED = _embedded_agent


def _cp_indices_for_ids(built, chosen_ids):
    idxs = []
    used = set()
    for cid in chosen_ids:
        for i, b in enumerate(built):
            if i in used:
                continue
            if b.get("card_id") == cid:
                idxs.append(i)
                used.add(i)
                break
    return idxs


def _cp_embedded(obs):
    """Run the proven base policy, then refine the ToHand-search target only."""
    base = _CP_ORIG_EMBEDDED(obs)
    try:
        sel = _get_select(obs)
        if not isinstance(sel, dict):
            return base
        options = _get_options(sel)
        if not options:
            return base
        mn, mx = _get_min_max_count(sel, len(options))
        ctx = sel.get("context")
        # Only refine when the base policy chose to search (non-empty, not a
        # safety decline) at the reliably identifiable ToHand-search context.
        if ctx == 7 and mx >= 1 and isinstance(base, list) and len(base) >= 1:
            built = [{{"card_id": resolve_option_card(obs, o)}} for o in options]
            board = build_board(obs)
            res = core_pilot_decide("search_to_hand", board, built)
            cid = res.get("chosen_card_id")
            if cid is not None:
                idxs = _cp_indices_for_ids(built, [cid])
                if idxs:
                    refined = _validate_action(idxs, len(options), mn, mx)
                    if refined:
                        return refined
    except Exception:
        pass
    return base


_embedded_agent = _cp_embedded


# Kaggle/cabt selects the LAST top-level callable in this module as the agent
# (see kaggle_environments.agent.get_last_callable). The override above appended
# new callables AFTER the deck-safety ``agent`` entrypoint, which would silently
# hijack the entrypoint and bypass deck-selection handling (the agent would
# return [] on the deck-selection step -> INVALID). The real entrypoint must be
# the last callable, and it MUST use a FRESH name: re-binding an existing global
# (e.g. ``agent = ...``) does not change dict insertion order, so it would not
# become last. ``core_pilot_agent`` simply delegates to the deck-safe ``agent``
# (which uses the refined ``_embedded_agent`` for gameplay). ``agent`` itself is
# left untouched so callers that invoke it by name still work.
_cp_deck_safe_agent = agent


def core_pilot_agent(obs_dict):
    return _cp_deck_safe_agent(obs_dict)
# === END PASS14 CORE-PILOT OVERRIDE ===
'''


def compile_candidate_source(base_main_src: str, playbook: dict,
                             candidate_id: str, flags: dict | None = None) -> str:
    literal = build_playbook_literal(playbook, flags=flags)
    return base_main_src.rstrip("\n") + "\n" + _render_block(literal, candidate_id)


def compile_to_dir(base_dir: Any, playbook_path: Any, out_dir: Any,
                   candidate_id: str, flags: dict | None = None) -> dict:
    """Write a compiled candidate (main.py + deck.csv) into ``out_dir``."""
    base = Path(base_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    base_main = (base / "main.py").read_text(encoding="utf-8")
    playbook = load_playbook(playbook_path)
    src = compile_candidate_source(base_main, playbook, candidate_id, flags=flags)
    (out / "main.py").write_text(src, encoding="utf-8")
    deck_src = (base / "deck.csv").read_text(encoding="utf-8")
    (out / "deck.csv").write_text(deck_src, encoding="utf-8")
    return {"main_py": str(out / "main.py"), "deck_csv": str(out / "deck.csv"),
            "candidate_id": candidate_id}


def make_tarball(src_dir: Any, tar_path: Any) -> str:
    """Tar exactly top-level main.py + deck.csv from ``src_dir``."""
    src = Path(src_dir)
    tar_path = Path(tar_path)
    tar_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "w:gz") as tar:
        for name in ("main.py", "deck.csv"):
            tar.add(src / name, arcname=name)
    return str(tar_path)
