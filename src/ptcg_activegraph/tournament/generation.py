"""Pass 42 — Candidate Generation v0 library (deterministic probation factory).

A LOCAL-only, deterministic, stdlib-safe candidate *factory*. It selects eligible
internal source candidates, applies deterministic mutation operators that
redistribute copy counts among IDs ALREADY in the source deck (no invented ids),
rewrites BOTH ``deck.csv`` and the ``_EMBEDDED_DECK`` fallback so the artifact is
internally consistent, and writes byte-deterministic tarballs.

This module materializes NOTHING on Kaggle and never promotes. See
``docs/CANDIDATE_GENERATION_V0.md`` for the full contract. The builder
(``scripts/run_candidate_generation_v0.py``), the validation gates, and the
probation admission all sit on top of these primitives.
"""

from __future__ import annotations

import ast
import gzip
import hashlib
import io
import re
import tarfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SUBMISSIONS_DIR = REPO_ROOT / "data" / "submissions"
GENERATED_DIR = SUBMISSIONS_DIR / "generated_pass42"

PASS_ID = "pass42"
CATALOG_VERSION = "candgen_v0"

DECK_SIZE = 60
MAX_COPIES = 4
ENERGY_FLOOR = 1  # never reduce a basic-energy id below this many copies

# Authoritative card-type column in EN_Card_Data.csv. Matched by EXACT value
# (never substring: "Pokémon Tool" contains "pok").
STAGE_TYPE_COL = "Stage (Pokémon)/Type (Energy and Trainer)"
TRAINER_STAGE_TYPES = {"Item", "Pokémon Tool", "Supporter", "Stadium"}
EFFECT_COL = "Effect Explanation"

# Statuses that may be used as a generation SOURCE. Deliberately excludes
# ``probation`` and ``generated_*`` candidates so the eligible-source set (and
# therefore the deterministic seed) is stable across reruns even after admission.
ELIGIBLE_SOURCE_STATUSES = {"active", "held_probe", "family_champion",
                            "portfolio_anchor"}
SOURCE_STATUS_PRIORITY = {"portfolio_anchor": 0, "family_champion": 1,
                          "active": 2, "held_probe": 3}

# Statuses/markers that must never be a source.
INELIGIBLE_SOURCE_STATUSES = {"special_pilot_only", "retired", "quarantined",
                              "invalid", "probation", "external_reference"}

OPERATOR_SHORT = {
    "basic_density_adjustment": "bdens",
    "energy_ratio_adjustment": "eratio",
    "draw_search_ratio_adjustment": "dsratio",
    "conservative_policy_weight_delta": "pweight",
    "noop_sentinel": "noop",
}
# Only these three deck operators are eligible for admission in v0.
DECK_OPERATOR_ORDER = ["energy_ratio_adjustment", "basic_density_adjustment",
                       "draw_search_ratio_adjustment"]


# ---------------------------------------------------------------------------
# Hashing helpers
# ---------------------------------------------------------------------------
def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: str | Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Card classification (honest; authoritative CSV column)
# ---------------------------------------------------------------------------
_DRAW_RE = re.compile(r"draw \d+ card|draw a card|draw cards|draw until", re.I)
_SEARCH_RE = re.compile(r"search your deck", re.I)


def classify_card(card_db, cid: int, count: int) -> str:
    """Bucket a card id: energy / basic_pokemon / evolution_pokemon / trainer /
    unknown. ``count > 4`` corroborates basic energy (the only copy-exempt type).
    """
    if count > MAX_COPIES:
        return "energy"
    rec = card_db.get(cid) if card_db is not None else None
    st = ((rec or {}).get(STAGE_TYPE_COL) or "").strip()
    if st == "Basic Energy":
        return "energy"
    if st == "Basic Pokémon":
        return "basic_pokemon"
    if st in TRAINER_STAGE_TYPES:
        return "trainer"
    if st.startswith("Stage") or st.startswith("Mega"):
        return "evolution_pokemon"
    return "unknown"


def _trainer_text(card_db, cid: int) -> str:
    rec = card_db.get(cid) if card_db is not None else None
    if not rec:
        return ""
    name = rec.get("name") or rec.get("Card Name") or ""
    effect = rec.get(EFFECT_COL) or ""
    return f"{name} {effect}"


def classify_deck(card_db, deck_ids) -> dict:
    """Structured classification of a 60-card deck (honest, source-derived)."""
    counts = Counter(int(c) for c in deck_ids)
    buckets = {cid: classify_card(card_db, cid, counts[cid]) for cid in counts}
    energy = sorted(c for c in counts if buckets[c] == "energy")
    basic_pokemon = sorted(c for c in counts if buckets[c] == "basic_pokemon")
    evolution = sorted(c for c in counts if buckets[c] == "evolution_pokemon")
    trainer = sorted(c for c in counts if buckets[c] == "trainer")
    draw, search = [], []
    for c in trainer:
        txt = _trainer_text(card_db, c)
        if _DRAW_RE.search(txt):
            draw.append(c)
        if _SEARCH_RE.search(txt):
            search.append(c)
    return {
        "counts": dict(counts),
        "buckets": {str(k): v for k, v in buckets.items()},
        "energy": energy, "basic_pokemon": basic_pokemon,
        "evolution_pokemon": evolution, "trainer": trainer,
        "draw": sorted(draw), "search": sorted(search),
    }


# ---------------------------------------------------------------------------
# Embedded-deck parse / render / rewrite
# ---------------------------------------------------------------------------
_EMBEDDED_RE = re.compile(r"_EMBEDDED_DECK\s*=\s*\[(.*?)\]", re.DOTALL)


def extract_embedded_deck(main_src: str) -> list[int]:
    m = _EMBEDDED_RE.search(main_src)
    if not m:
        return []
    return [int(x) for x in re.findall(r"-?\d+", m.group(1))]


def render_embedded_deck(ids) -> str:
    ids = list(ids)
    lines = ["_EMBEDDED_DECK = ["]
    for i in range(0, len(ids), 10):
        chunk = ids[i:i + 10]
        lines.append("    " + ", ".join(str(c) for c in chunk) + ",")
    lines.append("]")
    return "\n".join(lines)


def rewrite_embedded_deck(main_src: str, new_ids) -> str:
    """Replace ONLY the ``_EMBEDDED_DECK = [...]`` block; rest byte-identical.

    Re-parses the result and asserts the embedded multiset == ``new_ids``.
    """
    if not _EMBEDDED_RE.search(main_src):
        raise ValueError("source main.py has no _EMBEDDED_DECK block to rewrite")
    new_block = render_embedded_deck(new_ids)
    out = _EMBEDDED_RE.sub(lambda _m: new_block, main_src, count=1)
    ast.parse(out)  # must still parse
    if sorted(extract_embedded_deck(out)) != sorted(int(c) for c in new_ids):
        raise ValueError("embedded-deck rewrite multiset mismatch")
    return out


def render_deck_csv(ids) -> str:
    return "\n".join(str(int(c)) for c in ids) + "\n"


# ---------------------------------------------------------------------------
# Policy-weight parse / rewrite (conservative_policy_weight_delta operator)
# ---------------------------------------------------------------------------
def extract_policy_weights(main_src: str, which: str) -> dict:
    """Return the int weights of the top-level ``which`` dict (``_POSITIVE`` /
    ``_NEGATIVE``), parsed via AST. Empty dict if absent."""
    tree = ast.parse(main_src)
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == which
                and isinstance(node.value, ast.Dict)):
            out = {}
            for k, v in zip(node.value.keys, node.value.values):
                try:
                    key = ast.literal_eval(k)
                    val = ast.literal_eval(v)
                except Exception:  # noqa: BLE001
                    continue
                if isinstance(key, str) and isinstance(val, (int, float)):
                    out[key] = val
            return out
    return {}


def rewrite_policy_weight(main_src: str, which: str, key: str,
                          new_value: int) -> str:
    """Set ``which[key] = new_value`` via a targeted regex inside the dict block.

    Re-parses the result and asserts the new value took effect.
    """
    block_re = re.compile(re.escape(which) + r"\s*=\s*\{(.*?)\}", re.DOTALL)
    m = block_re.search(main_src)
    if not m:
        raise ValueError(f"source main.py has no {which} dict to rewrite")
    block = m.group(0)
    kv_re = re.compile(r"(['\"]" + re.escape(key) + r"['\"]\s*:\s*)(-?\d+)")
    if not kv_re.search(block):
        raise ValueError(f"{which} has no integer key {key!r} to rewrite")
    new_block = kv_re.sub(lambda mm: f"{mm.group(1)}{int(new_value)}", block,
                          count=1)
    out = main_src[:m.start()] + new_block + main_src[m.end():]
    ast.parse(out)
    if extract_policy_weights(out, which).get(key) != new_value:
        raise ValueError("policy-weight rewrite did not take effect")
    return out


# ---------------------------------------------------------------------------
# Operator results
# ---------------------------------------------------------------------------
@dataclass
class OperatorResult:
    operator: str
    applicable: bool
    reason: str
    new_deck_ids: list[int] | None = None   # None => deck unchanged
    deck_delta: dict | None = None
    policy_delta: dict | None = None
    params: dict = field(default_factory=dict)


def _shift(counts: dict, take_id: int, give_id: int, k: int) -> list[int]:
    """Return a new 60-card deck (sorted asc) with k copies moved take->give."""
    new = dict(counts)
    new[take_id] = new.get(take_id, 0) - k
    new[give_id] = new.get(give_id, 0) + k
    if new[take_id] <= 0:
        new.pop(take_id, None)
    out: list[int] = []
    for cid in sorted(new):
        out.extend([cid] * new[cid])
    return out


def _delta(take_id: int, give_id: int, k: int) -> dict:
    return {"removed": {str(take_id): k}, "added": {str(give_id): k}}


def op_energy_ratio_adjustment(deck_ids, classified, params) -> OperatorResult:
    k = int(params.get("k", 1))
    counts = classified["counts"]
    energy = classified["energy"]
    name = "energy_ratio_adjustment"
    if not energy:
        return OperatorResult(name, False, "no basic energy in deck")
    givers = sorted((e for e in energy if counts[e] - k >= ENERGY_FLOOR),
                    key=lambda e: (-counts[e], e))
    nonenergy = [c for c in counts if c not in set(energy)]
    recv = sorted((c for c in nonenergy if counts[c] + k <= MAX_COPIES),
                  key=lambda c: (counts[c], c))
    if not givers or not recv or givers[0] == recv[0]:
        return OperatorResult(name, False, "no legal energy giver / non-energy receiver")
    g, r = givers[0], recv[0]
    return OperatorResult(name, True,
                          f"-{k} energy #{g} (->{counts[g]-k}), +{k} #{r} (->{counts[r]+k})",
                          new_deck_ids=_shift(counts, g, r, k),
                          deck_delta=_delta(g, r, k), params={"k": k})


def op_basic_density_adjustment(deck_ids, classified, params) -> OperatorResult:
    k = int(params.get("k", 1))
    counts = classified["counts"]
    energy = classified["energy"]
    basics = classified["basic_pokemon"]
    name = "basic_density_adjustment"
    if not basics:
        return OperatorResult(name, False, "no basic Pokémon in deck")
    recv = sorted((b for b in basics if counts[b] + k <= MAX_COPIES),
                  key=lambda b: (counts[b], b))
    givers = sorted((e for e in energy if counts[e] - k >= ENERGY_FLOOR),
                    key=lambda e: (-counts[e], e))
    if not recv or not givers or recv[0] == givers[0]:
        return OperatorResult(name, False, "no basic receiver / energy giver")
    r, g = recv[0], givers[0]
    return OperatorResult(name, True,
                          f"+{k} basic #{r} (->{counts[r]+k}), -{k} energy #{g} (->{counts[g]-k})",
                          new_deck_ids=_shift(counts, g, r, k),
                          deck_delta=_delta(g, r, k), params={"k": k})


def op_draw_search_ratio_adjustment(deck_ids, classified, params) -> OperatorResult:
    k = int(params.get("k", 1))
    counts = classified["counts"]
    draw = classified["draw"]
    search = classified["search"]
    name = "draw_search_ratio_adjustment"
    if not draw or not search:
        return OperatorResult(name, False, "deck lacks both a draw and a search trainer")
    # Direction 1: take from a search trainer, give to a draw trainer.
    s_give = sorted((s for s in search if counts[s] - k >= 1),
                    key=lambda s: (-counts[s], s))
    d_recv = sorted((d for d in draw if counts[d] + k <= MAX_COPIES),
                    key=lambda d: (counts[d], d))
    if s_give and d_recv and s_give[0] != d_recv[0]:
        g, r = s_give[0], d_recv[0]
        return OperatorResult(name, True,
                              f"-{k} search #{g} (->{counts[g]-k}), +{k} draw #{r} (->{counts[r]+k})",
                              new_deck_ids=_shift(counts, g, r, k),
                              deck_delta=_delta(g, r, k), params={"k": k})
    # Direction 2 (reverse): take from a draw trainer, give to a search trainer.
    d_give = sorted((d for d in draw if counts[d] - k >= 1),
                    key=lambda d: (-counts[d], d))
    s_recv = sorted((s for s in search if counts[s] + k <= MAX_COPIES),
                    key=lambda s: (counts[s], s))
    if d_give and s_recv and d_give[0] != s_recv[0]:
        g, r = d_give[0], s_recv[0]
        return OperatorResult(name, True,
                              f"-{k} draw #{g} (->{counts[g]-k}), +{k} search #{r} (->{counts[r]+k})",
                              new_deck_ids=_shift(counts, g, r, k),
                              deck_delta=_delta(g, r, k), params={"k": k})
    return OperatorResult(name, False, "no legal draw/search giver+receiver pair")


def op_noop_sentinel(deck_ids, classified, params) -> OperatorResult:
    """Identity: returns the source deck unchanged. EXPECTED to be REJECTED by the
    duplicate/inert gate; it exists to prove the gate works."""
    counts = classified["counts"]
    out = []
    for cid in sorted(counts):
        out.extend([cid] * counts[cid])
    return OperatorResult("noop_sentinel", True,
                          "identity (no change) — must be rejected as inert/duplicate",
                          new_deck_ids=out, deck_delta={"removed": {}, "added": {}},
                          params={})


DECK_OPERATORS = {
    "energy_ratio_adjustment": op_energy_ratio_adjustment,
    "basic_density_adjustment": op_basic_density_adjustment,
    "draw_search_ratio_adjustment": op_draw_search_ratio_adjustment,
}


def policy_weight_delta(main_src: str, params: dict | None = None) -> OperatorResult:
    """conservative_policy_weight_delta — deck UNCHANGED; nudge one ``_POSITIVE``
    keyword weight by a small conservative delta. NON-admitted regression example.
    """
    params = params or {}
    delta = int(params.get("delta", 1))
    pos = extract_policy_weights(main_src, "_POSITIVE")
    name = "conservative_policy_weight_delta"
    if not pos:
        return OperatorResult(name, False, "no _POSITIVE weights to adjust")
    key = params.get("key") or sorted(pos)[0]
    if key not in pos:
        return OperatorResult(name, False, f"key {key!r} not in _POSITIVE")
    old = pos[key]
    new = int(old) + delta
    return OperatorResult(name, True,
                          f"_POSITIVE[{key!r}] {old} -> {new} (deck unchanged)",
                          new_deck_ids=None,
                          policy_delta={"which": "_POSITIVE", "key": key,
                                        "old": old, "new": new, "delta": delta},
                          params={"key": key, "delta": delta})


# ---------------------------------------------------------------------------
# Deterministic tarball writer (idempotent; never overwrites a differing file)
# ---------------------------------------------------------------------------
def build_tarball_bytes(main_bytes: bytes, deck_bytes: bytes) -> bytes:
    """Byte-deterministic gzip tarball with exactly top-level main.py + deck.csv."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for fname, data in sorted([("main.py", main_bytes), ("deck.csv", deck_bytes)]):
            info = tarfile.TarInfo(name=fname)
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.type = tarfile.REGTYPE
            tar.addfile(info, io.BytesIO(data))
    gz = io.BytesIO()
    with gzip.GzipFile(fileobj=gz, mode="wb", mtime=0) as g:
        g.write(raw.getvalue())
    return gz.getvalue()


def write_tarball_idempotent(out_path: str | Path, payload: bytes) -> dict:
    """Write ``payload`` only if absent or byte-identical. Never overwrites a
    differing tarball, never deletes. Returns {sha256, status}."""
    out_path = Path(out_path)
    sha = sha256_bytes(payload)
    if out_path.exists():
        existing_sha = sha256_file(out_path)
        if existing_sha == sha:
            return {"sha256": sha, "status": "identical_exists", "path": str(out_path)}
        return {"sha256": sha, "status": "differs_exists_refused",
                "existing_sha256": existing_sha, "path": str(out_path)}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(payload)
    return {"sha256": sha, "status": "written", "path": str(out_path)}


# ---------------------------------------------------------------------------
# Source eligibility + deterministic seed + plan
# ---------------------------------------------------------------------------
@dataclass
class Source:
    candidate_id: str
    family_id: str
    status: str
    tarball_path: str
    deck_ids: list[int]
    main_src: str
    tarball_sha256: str
    main_sha256: str
    deck_sha256: str


def resolve_tarball(tarball_path: str) -> Path | None:
    """Resolve a pool ``tarball_path`` to an existing file. Pool paths are stored
    relative to ``data/submissions/`` (matching runner.py / the pass4x scripts);
    also accept an absolute path or a repo-root-relative path."""
    if not tarball_path:
        return None
    for cand in (Path(tarball_path), SUBMISSIONS_DIR / tarball_path,
                 REPO_ROOT / tarball_path):
        if cand.is_file():
            return cand
    return None


def _read_tarball_members(tarball: Path) -> tuple[bytes | None, bytes | None, list[str]]:
    main_b = deck_b = None
    names: list[str] = []
    with tarfile.open(tarball, "r:gz") as t:
        for m in t.getmembers():
            if not m.isfile():
                continue
            base = Path(m.name).name
            names.append(m.name)
            if base == "main.py" and len(Path(m.name).parts) == 1:
                main_b = t.extractfile(m).read()
            elif base == "deck.csv" and len(Path(m.name).parts) == 1:
                deck_b = t.extractfile(m).read()
    return main_b, deck_b, names


def is_stdlib_lane_tarball(tarball: Path) -> bool:
    """True iff the tarball is exactly top-level main.py + deck.csv (no cg/ SDK)."""
    try:
        with tarfile.open(tarball, "r:gz") as t:
            files = [m for m in t.getmembers() if m.isfile()]
        names = sorted(Path(m.name).name for m in files)
        depths = {len(Path(m.name).parts) for m in files}
        return names == ["deck.csv", "main.py"] and depths == {1}
    except Exception:  # noqa: BLE001
        return False


def eligible_sources(pool) -> list[Source]:
    """Deterministically filter the pool down to eligible generation sources."""
    out: list[Source] = []
    for c in pool.candidates:
        if c.status in INELIGIBLE_SOURCE_STATUSES:
            continue
        if c.status not in ELIGIBLE_SOURCE_STATUSES:
            continue
        if not c.family_id:
            continue
        if str(c.candidate_id).startswith("generated_"):
            continue
        if not c.tarball_path:
            continue
        tb = resolve_tarball(c.tarball_path)
        if tb is None or not is_stdlib_lane_tarball(tb):
            continue
        main_b, deck_b, _names = _read_tarball_members(tb)
        if main_b is None or deck_b is None:
            continue
        try:
            deck_ids = [int(x) for x in deck_b.decode("utf-8").split() if x.strip()]
        except ValueError:
            continue
        if len(deck_ids) != DECK_SIZE:
            continue
        out.append(Source(
            candidate_id=c.candidate_id, family_id=c.family_id, status=c.status,
            tarball_path=c.tarball_path, deck_ids=deck_ids,
            main_src=main_b.decode("utf-8"),
            tarball_sha256=sha256_file(tb),
            main_sha256=sha256_bytes(main_b), deck_sha256=sha256_bytes(deck_b)))
    return sorted(out, key=lambda s: s.candidate_id)


def best_source_per_family(sources: list[Source]) -> dict[str, Source]:
    """Pick one source per family by status priority, then candidate_id."""
    by_fam: dict[str, list[Source]] = {}
    for s in sources:
        by_fam.setdefault(s.family_id, []).append(s)
    out: dict[str, Source] = {}
    for fam, lst in by_fam.items():
        out[fam] = sorted(
            lst, key=lambda s: (SOURCE_STATUS_PRIORITY.get(s.status, 9),
                                s.candidate_id))[0]
    return out


def generation_seed(sources: list[Source], pass_id: str = PASS_ID,
                    catalog_version: str = CATALOG_VERSION) -> str:
    parts = [pass_id, catalog_version]
    for s in sorted(sources, key=lambda x: x.candidate_id):
        parts += [s.candidate_id, s.tarball_sha256, s.main_sha256, s.deck_sha256]
    return sha256_bytes("\n".join(parts).encode("utf-8"))


def _source_short(candidate_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", candidate_id.lower())[:14]


@dataclass
class PlannedCandidate:
    family_id: str
    source_candidate_id: str
    operator: str
    params: dict
    generated_candidate_id: str
    deck_delta: dict
    new_deck_ids: list[int]
    reason: str


def build_plan(pool, card_db, budgets: dict | None = None,
               pass_id: str = PASS_ID,
               catalog_version: str = CATALOG_VERSION) -> dict:
    """Deterministic admission plan: <=budget deck-operator candidates from
    distinct families, maximizing operator diversity. Pure function of the inputs.
    """
    budgets = budgets or {"max_new_candidates_per_run": 3, "max_per_family": 1}
    max_new = int(budgets.get("max_new_candidates_per_run", 3))

    sources = eligible_sources(pool)
    seed = generation_seed(sources, pass_id, catalog_version)
    best = best_source_per_family(sources)
    families_sorted = sorted(best)

    # Pre-compute each family's applicable deck operators.
    applicable: dict[str, dict[str, OperatorResult]] = {}
    for fam in families_sorted:
        src = best[fam]
        classified = classify_deck(card_db, src.deck_ids)
        ops: dict[str, OperatorResult] = {}
        for op in DECK_OPERATOR_ORDER:
            res = DECK_OPERATORS[op](src.deck_ids, classified, {"k": 1})
            if res.applicable:
                ops[op] = res
        if ops:
            applicable[fam] = ops

    rotation = int(seed[:8], 16) % len(DECK_OPERATOR_ORDER)
    op_order = DECK_OPERATOR_ORDER[rotation:] + DECK_OPERATOR_ORDER[:rotation]

    chosen: list[tuple[str, str]] = []
    used_fam: set[str] = set()
    # Pass 1 (operator-major): cover distinct operators across distinct families.
    for op in op_order:
        if len(chosen) >= max_new:
            break
        for fam in families_sorted:
            if fam in used_fam:
                continue
            if op in applicable.get(fam, {}):
                chosen.append((fam, op))
                used_fam.add(fam)
                break
    # Pass 2 (family-major): fill remaining budget with any applicable operator.
    if len(chosen) < max_new:
        for fam in families_sorted:
            if len(chosen) >= max_new:
                break
            if fam in used_fam or fam not in applicable:
                continue
            for op in op_order:
                if op in applicable[fam]:
                    chosen.append((fam, op))
                    used_fam.add(fam)
                    break

    chosen.sort(key=lambda x: x[0])
    planned: list[PlannedCandidate] = []
    for fam, op in chosen:
        src = best[fam]
        res = applicable[fam][op]
        gid = (f"generated_{fam}_{_source_short(src.candidate_id)}_"
               f"{OPERATOR_SHORT[op]}_v1")
        planned.append(PlannedCandidate(
            family_id=fam, source_candidate_id=src.candidate_id, operator=op,
            params=res.params, generated_candidate_id=gid,
            deck_delta=res.deck_delta or {}, new_deck_ids=res.new_deck_ids or [],
            reason=res.reason))

    return {
        "pass_id": pass_id, "catalog_version": catalog_version, "seed": seed,
        "rotation": rotation, "operator_order": op_order,
        "budgets": budgets,
        "eligible_source_ids": [s.candidate_id for s in sources],
        "eligible_families": families_sorted,
        "applicable_operators": {f: sorted(o) for f, o in applicable.items()},
        "planned": planned,
    }


# ---------------------------------------------------------------------------
# LLM proposal-only stub (materializes NOTHING)
# ---------------------------------------------------------------------------
def llm_candidate_proposals(pool, card_db, max_proposals: int = 0) -> dict:
    """Proposal-only stub. Returns an inert, empty proposal set; it never calls a
    model and never materializes a candidate. Present so the v1 hook exists while
    v0 guarantees NO LLM-materialized candidates."""
    return {
        "enabled": False,
        "materialized": False,
        "note": "LLM proposals are disabled in v0; this stub materializes nothing.",
        "proposals": [],
    }


# ---------------------------------------------------------------------------
# Operator catalog metadata (single source of truth for the catalog artifact)
# ---------------------------------------------------------------------------
OPERATOR_CATALOG = [
    {
        "name": "energy_ratio_adjustment", "short": "eratio",
        "admits": True, "deck_changing": True,
        "summary": "Shift the energy:non-energy ratio by moving 1 copy from a "
                   "basic-energy id to a non-energy id already in the deck.",
        "applicability": "deck has basic energy with count > ENERGY_FLOOR and a "
                         "non-energy id with count < 4.",
        "determinism": "giver = energy id with highest count (tie: lowest id); "
                       "receiver = non-energy id with lowest count < 4 (tie: "
                       "lowest id); k = 1.",
    },
    {
        "name": "basic_density_adjustment", "short": "bdens",
        "admits": True, "deck_changing": True,
        "summary": "Increase Basic-Pokémon density: +1 to a Basic Pokémon with "
                   "room, -1 from a basic-energy id with slack.",
        "applicability": "deck has a Basic Pokémon with count < 4 and basic "
                         "energy with count > ENERGY_FLOOR.",
        "determinism": "receiver = Basic Pokémon with lowest count < 4 (tie: low "
                       "id); giver = energy id with highest count (tie: low id); "
                       "k = 1.",
    },
    {
        "name": "draw_search_ratio_adjustment", "short": "dsratio",
        "admits": True, "deck_changing": True,
        "summary": "Shift the trainer draw:search ratio by moving 1 copy between "
                   "a draw trainer and a search trainer already in the deck.",
        "applicability": "deck has both a draw trainer and a search trainer "
                         "(classified from card text) with the needed slack.",
        "determinism": "direction 1 (search->draw) preferred, else reverse; giver "
                       "= highest count with >=1 remaining (tie: low id); receiver "
                       "= lowest count < 4 (tie: low id); k = 1.",
    },
    {
        "name": "conservative_policy_weight_delta", "short": "pweight",
        "admits": False, "deck_changing": False,
        "summary": "Deck UNCHANGED; nudge one stdlib _POSITIVE keyword weight by a "
                   "small conservative integer delta.",
        "applicability": "source main.py exposes an integer-valued _POSITIVE dict.",
        "determinism": "key = first sorted _POSITIVE key (overridable); "
                       "new = old + delta (delta = 1).",
        "non_admitted_reason": "policy effect may be inert because the live last "
                               "callable is the core-pilot playbook override; "
                               "proving non-inertness is deferred to v1.",
    },
    {
        "name": "noop_sentinel", "short": "noop",
        "admits": False, "deck_changing": False,
        "summary": "Identity operator: returns the source deck unchanged.",
        "applicability": "always; exists only to prove the duplicate/inert gate "
                         "rejects it.",
        "determinism": "n/a (identity).",
        "non_admitted_reason": "rejected by the duplicate/inert validation gate.",
    },
]


def operator_catalog_payload(pool, card_db, pass_id: str = PASS_ID,
                             catalog_version: str = CATALOG_VERSION) -> dict:
    """Full catalog payload: operator metadata + applicability matrix over the
    current eligible pool + the deterministic admission plan preview."""
    plan = build_plan(pool, card_db, pass_id=pass_id, catalog_version=catalog_version)
    planned = [{
        "generated_candidate_id": p.generated_candidate_id,
        "family_id": p.family_id, "source_candidate_id": p.source_candidate_id,
        "operator": p.operator, "params": p.params,
        "deck_delta": p.deck_delta, "reason": p.reason,
    } for p in plan["planned"]]
    return {
        "pass_id": pass_id, "catalog_version": catalog_version,
        "seed": plan["seed"], "rotation": plan["rotation"],
        "operator_order": plan["operator_order"], "budgets": plan["budgets"],
        "operators": OPERATOR_CATALOG,
        "deck_operators": DECK_OPERATOR_ORDER,
        "eligible_source_ids": plan["eligible_source_ids"],
        "eligible_families": plan["eligible_families"],
        "applicable_operators": plan["applicable_operators"],
        "planned_admissions": planned,
        "llm_proposals": llm_candidate_proposals(pool, card_db),
    }
