"""Compile the typed strategy layer into a stdlib-only candidate ``main.py``.

The lab modules (``board``, ``metadata``, ``profiles``, ``tactics``,
``decisions``) are the source of truth. This compiler embeds their
standard-library-only source plus a deck's StrategyProfile literal and an inlined
per-card metadata table into a PASS35 override block appended to a base candidate
``main.py``. Because fixtures grade the very ``typed_decide`` this block emits, the
deterministic gate tests exactly what ships.

Runtime integration is conservative: it preserves the proven base policy untouched
and only refines decisions at the reliably-identifiable cabt contexts named in
``_TP_RUNTIME_CONTEXTS`` (0 main: emergency-bench + attach-target, 1 setup-active,
2 setup-bench, 7 ToHand-search, 8 discard, 38 draw-count), deferring to the base
policy everywhere else and on any error/mismatch.
"""
from __future__ import annotations

import csv
import json
import tarfile
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

_DIR = Path(__file__).resolve().parent
# Dependency order matters: later modules reference names from earlier ones.
_EMBED_MODULES = ("board.py", "metadata.py", "profiles.py", "tactics.py",
                  "decisions.py")
_STRIP_PREFIXES = ("from __future__", "from ptcg_activegraph",
                   "import ptcg_activegraph", "from typing import")
_DEFAULT_CONTEXTS = (0, 1, 2, 7, 8, 38)


def _strip_module_source(path: Path) -> str:
    lines = []
    skipping_paren = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.lstrip()
        if skipping_paren:
            if ")" in line:
                skipping_paren = False
            continue
        if any(stripped.startswith(p) for p in _STRIP_PREFIXES):
            if "(" in line and ")" not in line:
                skipping_paren = True
            continue
        lines.append(line)
    return "\n".join(lines).strip("\n")


def _embedded_layer_source() -> str:
    parts = []
    for name in _EMBED_MODULES:
        src = _strip_module_source(_DIR / name)
        parts.append("# ---- embedded: pilot_typed/%s ----\n%s" % (name, src))
    return "\n\n\n".join(parts)


def load_profile(profile_path: Any) -> dict:
    if yaml is None:
        raise RuntimeError("PyYAML required to load a profile yaml")
    return yaml.safe_load(Path(profile_path).read_text(encoding="utf-8")) or {}


def build_profile_literal(profile: dict) -> dict:
    """Reduce a profile to the minimal JSON-safe dict the typed layer consumes."""
    def ints(v):
        return [int(c) for c in (v or []) if isinstance(c, int)
                and not isinstance(c, bool)]
    roles = {}
    for role, ids in (profile.get("roles") or {}).items():
        roles[str(role)] = ints(ids)
    out = {
        "id": str(profile.get("id") or ""),
        "executable": bool(profile.get("executable", False)),
        "lane": profile.get("lane") or "stdlib_typed_lite",
        "implemented_contexts": ints(profile.get("implemented_contexts")),
        "unsupported_mechanics": [str(m) for m in
                                  (profile.get("unsupported_mechanics") or [])],
        "roles": roles,
        "priority": ints(profile.get("priority")),
        "energy_types": [str(t) for t in (profile.get("energy_types") or [])],
        "deckout_guard": profile.get("deckout_guard") or {},
        "discard_keep": ints(profile.get("discard_keep")),
        "discard_prefer": ints(profile.get("discard_prefer")),
    }
    return out


def _profile_card_ids(profile_literal: dict) -> list:
    ids = set()
    for v in (profile_literal.get("roles") or {}).values():
        ids.update(v)
    for key in ("priority", "discard_keep", "discard_prefer"):
        ids.update(profile_literal.get(key) or [])
    return sorted(ids)


def build_metadata_table(card_csv: Any, card_ids: Any) -> dict:
    """Build a minimal metadata dict for ONLY ``card_ids`` from EN_Card_Data.csv.

    The CSV is read locally and never shipped/committed. Returns {} when the CSV
    is unavailable so compilation degrades to role-only behavior."""
    path = Path(card_csv)
    wanted = {int(c) for c in card_ids if isinstance(c, int)
              and not isinstance(c, bool)}
    table: dict = {}
    if not path.exists() or not wanted:
        return table
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                raw_id = row.get("Card ID") or row.get("card_id") or row.get("id")
                try:
                    cid = int(str(raw_id).strip())
                except (TypeError, ValueError):
                    continue
                if cid not in wanted:
                    continue
                table[cid] = _row_to_meta(row)
    except Exception:  # noqa: BLE001
        return {}
    return table


# Energy symbol -> color name (matches profile ``energy_types`` vocabulary).
_ENERGY_SYMBOL = {
    "{G}": "Grass", "{R}": "Fire", "{W}": "Water", "{L}": "Lightning",
    "{P}": "Psychic", "{F}": "Fighting", "{D}": "Darkness", "{M}": "Metal",
    "{N}": "Dragon", "{C}": "Colorless",
}
_STAGE_COL = "Stage (Pokémon)/Type (Energy and Trainer)"


def _row_to_meta(row: dict) -> dict:
    def g(*keys):
        for k in keys:
            v = row.get(k)
            if v not in (None, "", "n/a", "N/A"):
                return str(v).strip()
        return None
    name = g("Card Name", "Name", "name")
    # Card type is defined by the Stage/Type column, NOT "Category"
    # (Category holds Tera/Ancient/Trainer's-Pokemon labels).
    stage_type = (g(_STAGE_COL, "Stage", "Subtype") or "")
    st = stage_type.lower()
    card_type = None
    stage = None
    is_basic_pokemon = False
    is_basic_energy = False
    # Order matters: trainer markers are checked BEFORE the "pok" branch because
    # "Pokémon Tool" contains "pok" yet is a Trainer, not a Pokemon. Energy is
    # checked first ("Basic Energy" also contains neither a trainer marker nor
    # "pok"). Real Pokemon rows are exactly "Basic/Stage 1/Stage 2 Pokémon" and
    # carry no trainer marker, so they fall through to the pokemon branch.
    if "energy" in st:  # "Basic Energy" / "Special Energy"
        card_type = "energy"
        is_basic_energy = "basic" in st
    elif any(t in st for t in ("item", "supporter", "stadium", "tool",
                               "technical machine")):
        card_type = "trainer"
    elif "pok" in st:  # "Basic/Stage 1/Stage 2 Pokémon"
        card_type = "pokemon"
        if "basic" in st:
            stage, is_basic_pokemon = "basic", True
        elif "stage 2" in st:
            stage = "stage2"
        elif "stage 1" in st:
            stage = "stage1"
    meta: dict = {"name": name, "card_type": card_type}
    if stage:
        meta["stage"] = stage
    if is_basic_pokemon:
        meta["is_basic_pokemon"] = True
    if is_basic_energy:
        meta["is_basic_energy"] = True
    sym = g("Type")
    if sym:
        meta["energy_type"] = _ENERGY_SYMBOL.get(sym, sym)
    hp = g("HP")
    if hp is not None:
        try:
            meta["hp"] = int(hp)
        except ValueError:
            pass
    rc = g("Retreat")
    if rc is not None:
        try:
            meta["retreat_cost"] = int(rc)
        except ValueError:
            pass
    if (g("Rule") or "").lower() == "pokémon ex" or \
            (name or "").lower().endswith(" ex"):
        meta["ex"] = True
    return meta


def _render_block(profile_literal: dict, meta_literal: dict, candidate_id: str,
                  runtime_contexts: tuple) -> str:
    layer_src = _embedded_layer_source()
    return f'''

# === PASS35 TYPED STRATEGY OVERRIDE: {candidate_id} ===
# Embeds the typed board-aware strategy layer (stdlib-only) plus this deck's
# StrategyProfile and a minimal per-card metadata table. Exposes
# ``typed_decide(kind, board, options)`` (graded by the typed-strategy fixtures)
# and conservatively refines decisions at the reliably-identifiable cabt contexts
# in ``_TP_RUNTIME_CONTEXTS`` while preserving the proven base policy beneath it.
from typing import Any as _TP_Any  # noqa: F401  (stdlib)

{layer_src}

_TP_PROFILE = {profile_literal!r}
_TP_META = {meta_literal!r}
_TP_RUNTIME_CONTEXTS = {tuple(runtime_contexts)!r}


def typed_decide(kind, board, options, profile=None, meta=None):
    """Public typed decision entry; defaults to this deck's profile + metadata."""
    return decide(kind, board, options,
                  profile if profile is not None else _TP_PROFILE,
                  meta if meta is not None else _TP_META)


_TP_ORIG_EMBEDDED = _embedded_agent


def _tp_indices_for_ids(built, chosen_ids):
    idxs, used = [], set()
    for cid in chosen_ids:
        for i, b in enumerate(built):
            if i in used:
                continue
            if b.get("card_id") == cid:
                idxs.append(i)
                used.add(i)
                break
    return idxs


def _tp_type8_target_options(obs, options):
    """[(index, target_card_id)] for attach-like (type 8) options with a
    resolvable distinct in-play target."""
    out = []
    for i, o in enumerate(options):
        if isinstance(o, dict) and o.get("type") == 8:
            tgt = resolve_option_target(obs, o)
            if tgt is not None:
                out.append((i, tgt))
    return out


def _tp_embedded(obs):
    """Run the proven base policy, then refine ONLY at reliably-identifiable
    contexts. Refinement never changes WHETHER or HOW MANY options are acted on;
    it only reorders WHICH option(s) of the base's committed action are chosen,
    and bails back to base on any mismatch or error."""
    base = _TP_ORIG_EMBEDDED(obs)
    try:
        sel = _get_select(obs)
        if not isinstance(sel, dict):
            return base
        options = _get_options(sel)
        if not options:
            return base
        mn, mx = _get_min_max_count(sel, len(options))
        ctx = sel.get("context")
        if not (isinstance(base, list) and len(base) >= 1):
            return base
        board = build_board(obs)

        if ctx == 0 and 0 in _TP_RUNTIME_CONTEXTS and len(base) == 1:
            base_i = base[0]
            chosen = options[base_i] if 0 <= base_i < len(options) else None
            chosen_type = chosen.get("type") if isinstance(chosen, dict) else None
            # (a) Emergency backup bench: empty bench, base picked a non-attack
            # play-from-hand; bench the best Basic instead.
            bench_empty = not (board.get("bench") if isinstance(board, dict) else None)
            if mn == 1 and mx == 1 and chosen_type != 13 and bench_empty:
                hand = board.get("hand") or []
                built = []
                for o in options:
                    cid = None
                    if isinstance(o, dict) and o.get("type") == 7:
                        ix = o.get("index")
                        if isinstance(ix, int) and not isinstance(ix, bool) \\
                                and 0 <= ix < len(hand):
                            cid = card_id(hand[ix])
                    built.append({{"card_id": cid}})
                res = typed_decide("emergency_backup_bench", board, built)
                cid = res.get("chosen_card_id")
                if cid is not None and 0 <= base_i < len(built):
                    if built[base_i].get("card_id") != cid:
                        idxs = _tp_indices_for_ids(built, [cid])
                        if idxs:
                            refined = _validate_action(idxs, len(options), mn, mx)
                            if refined and len(refined) == 1:
                                return refined
            # (b) Attach-target: base picked a type-8 attach with a resolvable
            # target and there are >=2 distinct targets; choose the intended
            # attacker. Count/type unchanged (still exactly the one option).
            if mn == 1 and mx == 1 and chosen_type == 8:
                pairs = _tp_type8_target_options(obs, options)
                targets = [t for _, t in pairs]
                if len(set(targets)) >= 2:
                    built = [{{"card_id": t}} for _, t in pairs]
                    res = typed_decide("attach_energy", board, built)
                    tgt = res.get("chosen_target_id")
                    if tgt is not None:
                        for i, t in pairs:
                            if t == tgt:
                                refined = _validate_action([i], len(options), mn, mx)
                                if refined and len(refined) == 1:
                                    return refined
                                break
        elif ctx == 1 and 1 in _TP_RUNTIME_CONTEXTS and mn == 1 and mx == 1 \\
                and len(base) == 1:
            built = [{{"card_id": resolve_option_card(obs, o)}} for o in options]
            res = typed_decide("setup_active", board, built)
            cid = res.get("chosen_card_id")
            if cid is not None:
                idxs = _tp_indices_for_ids(built, [cid])
                if idxs:
                    refined = _validate_action(idxs, len(options), mn, mx)
                    if refined and len(refined) == 1:
                        return refined
        elif ctx == 2 and 2 in _TP_RUNTIME_CONTEXTS:
            need = len(base)
            if mn <= need <= mx and need >= 1:
                built = [{{"card_id": resolve_option_card(obs, o)}} for o in options]
                if isinstance(board, dict):
                    board["bench_pick_count"] = need
                res = typed_decide("setup_bench_multi", board, built)
                idxs = _tp_indices_for_ids(built, res.get("chosen_card_ids") or [])
                if len(idxs) == need:
                    refined = _validate_action(idxs, len(options), mn, mx)
                    if refined and len(refined) == need:
                        return refined
        elif ctx == 7 and 7 in _TP_RUNTIME_CONTEXTS and mx >= 1:
            built = [{{"card_id": resolve_option_card(obs, o)}} for o in options]
            res = typed_decide("search_to_hand", board, built)
            cid = res.get("chosen_card_id")
            if cid is not None:
                idxs = _tp_indices_for_ids(built, [cid])
                if idxs:
                    refined = _validate_action(idxs, len(options), mn, mx)
                    if refined:
                        return refined
        elif ctx == 8 and 8 in _TP_RUNTIME_CONTEXTS:
            need = len(base)
            if mn <= need <= mx:
                built = [{{"card_id": resolve_option_card(obs, o)}} for o in options]
                if isinstance(board, dict):
                    board["discard_count"] = need
                res = typed_decide("discard", board, built)
                idxs = _tp_indices_for_ids(built, res.get("chosen_card_ids") or [])
                if len(idxs) == need:
                    refined = _validate_action(idxs, len(options), mn, mx)
                    if refined and len(refined) == need:
                        return refined
        elif ctx == 38 and 38 in _TP_RUNTIME_CONTEXTS and mn == 1 and mx == 1:
            numbers = [o.get("number") if isinstance(o, dict) else None
                       for o in options]
            if all(isinstance(n, int) and not isinstance(n, bool) for n in numbers):
                res = typed_decide("draw_count", board, options)
                chosen_number = res.get("chosen_number")
                if isinstance(chosen_number, int) and not isinstance(chosen_number, bool):
                    for i, o in enumerate(options):
                        if isinstance(o, dict) and o.get("number") == chosen_number:
                            refined = _validate_action([i], len(options), mn, mx)
                            if refined and len(refined) == 1:
                                return refined
                            break
    except Exception:
        pass
    return base


_embedded_agent = _tp_embedded


def _tp_obs_get(obs, key, default=None):
    """Read ``key`` from a dict OR a Struct-like obs (cabt sends both)."""
    if isinstance(obs, dict):
        return obs.get(key, default)
    getter = getattr(obs, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except Exception:
            return default
    return getattr(obs, key, default)


def _tp_is_deck_selection(obs):
    """True on the deck-submission step (select is None OR absent), across the
    dict and Struct-like obs shapes cabt uses. A present ``select`` dict (even
    with no options) is gameplay/malformed, NOT deck-selection."""
    if obs is None:
        return False
    sel = _tp_obs_get(obs, "select", "__tp_absent__")
    if isinstance(sel, dict):
        return False
    return True


def _tp_deck_ids():
    try:
        ids = _load_deck_ids()
        return ids if isinstance(ids, list) else []
    except Exception:
        return []


# Robust module-level agent: return the 60-card deck on EVERY deck-selection
# shape (the proven base only handled literal ``select=None``), else delegate to
# the base policy (which uses the refined ``_embedded_agent`` for gameplay).
_tp_base_agent = agent


def _tp_robust_agent(obs_dict):
    try:
        if _tp_is_deck_selection(obs_dict):
            ids = _tp_deck_ids()
            if len(ids) == 60:
                return ids
    except Exception:
        pass
    return _tp_base_agent(obs_dict)


agent = _tp_robust_agent


# Kaggle/cabt selects the LAST top-level callable as the agent. The real
# entrypoint must be last and use a FRESH name (re-binding ``agent`` does not
# change dict insertion order). ``typed_pilot_agent`` delegates to the robust
# deck-safe ``agent`` above.
_tp_deck_safe_agent = agent


def typed_pilot_agent(obs_dict):
    return _tp_deck_safe_agent(obs_dict)
# === END PASS35 TYPED STRATEGY OVERRIDE ===
'''


def compile_candidate_source(base_main_src: str, profile: dict,
                             meta_table: dict, candidate_id: str,
                             runtime_contexts: tuple = _DEFAULT_CONTEXTS) -> str:
    literal = build_profile_literal(profile)
    contexts = tuple(c for c in runtime_contexts
                     if c in (literal.get("implemented_contexts") or list(runtime_contexts)))
    if not contexts:
        contexts = tuple(runtime_contexts)
    return base_main_src.rstrip("\n") + "\n" + _render_block(
        literal, meta_table or {}, candidate_id, contexts)


def compile_to_dir(base_dir: Any, profile_path: Any, out_dir: Any,
                   candidate_id: str, card_csv: Any = None,
                   runtime_contexts: tuple = _DEFAULT_CONTEXTS) -> dict:
    base = Path(base_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    base_main = (base / "main.py").read_text(encoding="utf-8")
    profile = load_profile(profile_path)
    literal = build_profile_literal(profile)
    meta_table = {}
    if card_csv is not None:
        meta_table = build_metadata_table(card_csv, _profile_card_ids(literal))
    src = compile_candidate_source(base_main, profile, meta_table, candidate_id,
                                   runtime_contexts=runtime_contexts)
    (out / "main.py").write_text(src, encoding="utf-8")
    (out / "deck.csv").write_text((base / "deck.csv").read_text(encoding="utf-8"),
                                  encoding="utf-8")
    return {"main_py": str(out / "main.py"), "deck_csv": str(out / "deck.csv"),
            "candidate_id": candidate_id, "meta_card_count": len(meta_table),
            "runtime_contexts": list(literal.get("implemented_contexts")
                                     or runtime_contexts)}


def write_metadata_audit(card_csv: Any, card_ids: Any, out_path: Any) -> dict:
    """Write the derived metadata table (our card ids only) for audit. The raw
    CSV is never copied; only derived fields keyed by our own ids."""
    table = build_metadata_table(card_csv, card_ids)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({str(k): v for k, v in table.items()}, indent=2,
                              sort_keys=True), encoding="utf-8")
    return table


def make_tarball(src_dir: Any, tar_path: Any) -> str:
    src = Path(src_dir)
    tar_path = Path(tar_path)
    tar_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "w:gz") as tar:
        for name in ("main.py", "deck.csv"):
            tar.add(src / name, arcname=name)
    return str(tar_path)
