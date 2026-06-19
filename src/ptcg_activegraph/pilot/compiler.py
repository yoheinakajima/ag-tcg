"""Compile the core-pilot layers into a stdlib-only candidate ``main.py``.

The lab modules (``state``, ``roles``, ``scoring``, ``decisions``) are the source of
truth. This compiler embeds their **standard-library-only** source plus the deck
playbook's role maps (as Python literals) into a PASS14 override block appended to a
base candidate ``main.py``. Because the fixtures grade the very ``core_pilot_decide``
this block emits, the deterministic gate tests exactly what ships.

Runtime integration is intentionally conservative: it preserves the proven Pass-8
effect-safety policy untouched and only refines decisions at the *reliably
identifiable* cabt contexts named in ``state.py`` (``select.context == 7`` ToHand
search, and — when enabled for a candidate — ``select.context == 8`` discard),
deferring to the base policy everywhere else and on any error. Which contexts a
compiled candidate refines is recorded in the emitted ``_CP_RUNTIME_CONTEXTS`` set
so the coverage audit can verify wiring without guessing.
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


def _render_block(playbook_literal: dict, candidate_id: str,
                  runtime_contexts: tuple = (7,)) -> str:
    layer_src = _embedded_layer_source()
    return f'''

# === PASS14 CORE-PILOT OVERRIDE: {candidate_id} ===
# Embeds the Layer 1-3 core-pilot decision layer (stdlib-only) plus this deck's
# role playbook. Exposes ``core_pilot_decide(kind, board, options)`` (graded by the
# core-competency fixtures) and conservatively refines decisions at the reliably
# identifiable cabt contexts in ``_CP_RUNTIME_CONTEXTS`` while preserving the proven
# Pass-8 effect-safety policy beneath it.
from typing import Any as _CP_Any  # noqa: F401  (stdlib)

{layer_src}

_CP_PLAYBOOK = {playbook_literal!r}

# Reliably-identifiable cabt select.context integers this candidate refines at
# runtime (7=ToHand search, 8=discard). Empirically confirmed + named in state.py.
_CP_RUNTIME_CONTEXTS = {tuple(runtime_contexts)!r}


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
    """Run the proven base policy, then refine ONLY at the reliably identifiable
    cabt contexts in ``_CP_RUNTIME_CONTEXTS`` (7=ToHand search, 8=discard).

    Refinement never changes WHETHER or HOW MANY cards are acted on — the base
    policy already decided that (and owns all effect-safety). We only reorder
    WHICH card(s) of the base's committed action are chosen, and bail back to the
    base result on any mismatch or error."""
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
        # Only refine when the base policy committed to acting (non-empty list,
        # not a safety decline).
        if not (isinstance(base, list) and len(base) >= 1):
            return base
        # Emergency backup bench (Pass 22): at the Main action context, when the
        # bench is EMPTY and a backup benchable Basic can be played (a type-7
        # play-from-hand option whose hand card is a setup/primary basic), bench
        # it instead of passing/drawing/attaching -- but NEVER instead of an
        # attack. Still exactly ONE Main option selected; bails to base on any
        # mismatch, and only fires when the embedded playbook sets the flag.
        if ctx == 0 and 0 in _CP_RUNTIME_CONTEXTS and mn == 1 and mx == 1 and len(base) == 1:
            base_i = base[0]
            chosen = options[base_i] if 0 <= base_i < len(options) else None
            chosen_type = chosen.get("type") if isinstance(chosen, dict) else None
            if chosen_type != 13:  # never override an attack option
                board = build_board(obs)
                hand = board.get("hand") or [] if isinstance(board, dict) else []
                built = []
                for o in options:
                    cid = None
                    if isinstance(o, dict) and o.get("type") == 7:
                        ix = o.get("index")
                        if isinstance(ix, int) and not isinstance(ix, bool) and 0 <= ix < len(hand):
                            cid = card_id(hand[ix])
                    built.append({{"card_id": cid}})
                res = core_pilot_decide("emergency_backup_bench", board, built)
                cid = res.get("chosen_card_id")
                if cid is not None:
                    base_cid = built[base_i].get("card_id") if 0 <= base_i < len(built) else None
                    if base_cid != cid:
                        idxs = _cp_indices_for_ids(built, [cid])
                        if idxs:
                            refined = _validate_action(idxs, len(options), mn, mx)
                            if refined and len(refined) == 1:
                                return refined
        # Refine WHICH basic becomes the active Pokemon at setup (count is fixed
        # at exactly 1 by the engine -- only the choice changes; Kyogre > Snover).
        elif ctx == 1 and 1 in _CP_RUNTIME_CONTEXTS and mn == 1 and mx == 1 and len(base) == 1:
            built = [{{"card_id": resolve_option_card(obs, o)}} for o in options]
            board = build_board(obs)
            res = core_pilot_decide("setup_active", board, built)
            cid = res.get("chosen_card_id")
            if cid is not None:
                idxs = _cp_indices_for_ids(built, [cid])
                if idxs:
                    refined = _validate_action(idxs, len(options), mn, mx)
                    if refined and len(refined) == 1:
                        return refined
        # Refine WHICH basics go to the bench at setup, keeping exactly the COUNT
        # the base policy already committed to (never benches more/fewer).
        elif ctx == 2 and 2 in _CP_RUNTIME_CONTEXTS:
            need = len(base)
            if mn <= need <= mx and need >= 1:
                built = [{{"card_id": resolve_option_card(obs, o)}} for o in options]
                board = build_board(obs)
                if isinstance(board, dict):
                    board["bench_pick_count"] = need
                res = core_pilot_decide("setup_bench_multi", board, built)
                chosen_ids = res.get("chosen_card_ids") or []
                idxs = _cp_indices_for_ids(built, chosen_ids)
                if len(idxs) == need:
                    refined = _validate_action(idxs, len(options), mn, mx)
                    if refined and len(refined) == need:
                        return refined
        # Refine the search target at the ToHand-search context.
        elif ctx == 7 and 7 in _CP_RUNTIME_CONTEXTS and mx >= 1:
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
        # Refine WHICH cards to discard at the discard context, keeping exactly
        # the COUNT the base policy already committed to (only the choice changes).
        elif ctx == 8 and 8 in _CP_RUNTIME_CONTEXTS:
            need = len(base)
            if mn <= need <= mx:
                built = [{{"card_id": resolve_option_card(obs, o)}} for o in options]
                board = build_board(obs)
                if isinstance(board, dict):
                    board["discard_count"] = need
                res = core_pilot_decide("discard", board, built)
                chosen_ids = res.get("chosen_card_ids") or []
                idxs = _cp_indices_for_ids(built, chosen_ids)
                if len(idxs) == need:
                    refined = _validate_action(idxs, len(options), mn, mx)
                    if refined and len(refined) == need:
                        return refined
        # Refine a numeric 'choose a number' select (e.g. draw-count): pick the
        # quantity that avoids self-deckout. Still exactly ONE option selected --
        # only WHICH number changes; deck size comes from build_board (the select
        # itself carries no deck info).
        elif ctx == 38 and 38 in _CP_RUNTIME_CONTEXTS and mn == 1 and mx == 1:
            numbers = [o.get("number") if isinstance(o, dict) else None
                       for o in options]
            if all(isinstance(n, int) and not isinstance(n, bool) for n in numbers):
                board = build_board(obs)
                res = core_pilot_decide("draw_count", board, options)
                chosen_number = res.get("chosen_number")
                if isinstance(chosen_number, int) and not isinstance(chosen_number, bool):
                    pick = None
                    for i, o in enumerate(options):
                        if isinstance(o, dict) and o.get("number") == chosen_number:
                            pick = i
                            break
                    if pick is not None:
                        refined = _validate_action([pick], len(options), mn, mx)
                        if refined and len(refined) == 1:
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
                             candidate_id: str, flags: dict | None = None,
                             runtime_contexts: tuple = (7,)) -> str:
    literal = build_playbook_literal(playbook, flags=flags)
    return base_main_src.rstrip("\n") + "\n" + _render_block(
        literal, candidate_id, runtime_contexts=runtime_contexts)


def compile_to_dir(base_dir: Any, playbook_path: Any, out_dir: Any,
                   candidate_id: str, flags: dict | None = None,
                   runtime_contexts: tuple = (7,)) -> dict:
    """Write a compiled candidate (main.py + deck.csv) into ``out_dir``."""
    base = Path(base_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    base_main = (base / "main.py").read_text(encoding="utf-8")
    playbook = load_playbook(playbook_path)
    src = compile_candidate_source(base_main, playbook, candidate_id, flags=flags,
                                   runtime_contexts=runtime_contexts)
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
