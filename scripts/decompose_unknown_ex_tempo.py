#!/usr/bin/env python3
"""Decompose the provisional ``unknown_ex_tempo`` bucket into replay-grounded
subfamilies.

This is a DOCUMENTATION + META-ANALYSIS script (Pass 13). It does NOT:
- upload or submit anything,
- generate gameplay candidates,
- invent card IDs,
- mutate root main.py / deck.csv,
- commit official card data (it only *reads* local card metadata to attach
  human-readable names; the outputs store names + counts, never the raw CSV).

For every episode currently labelled ``unknown_ex_tempo`` it reads the opponent
deck, fingerprints it, and assigns a subfamily ONLY when a confirmed signature
``ex`` card (already present in the archetype's ``evidence_card_ids``) is found in
the deck. Decks without a confident signature stay in ``generic_unknown_ex_tempo``.

Inputs:
- data/meta_replays/replay_registry.json
- data/meta_replays/archetypes.yaml
- data/meta_replays/decks/*.csv
- data/cards/EN_Card_Data.csv (optional; for names/categories only)

Outputs:
- data/meta_replays/unknown_ex_tempo_decomposition.json
- data/meta_replays/unknown_ex_tempo_decomposition.md
- data/meta_replays/archetypes_refined.yaml
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_JSON = REPO_ROOT / "data" / "meta_replays" / "replay_registry.json"
ARCHETYPES_YAML = REPO_ROOT / "data" / "meta_replays" / "archetypes.yaml"
DECKS_DIR = REPO_ROOT / "data" / "meta_replays" / "decks"
CARD_META_CSV = REPO_ROOT / "data" / "cards" / "EN_Card_Data.csv"

OUT_JSON = REPO_ROOT / "data" / "meta_replays" / "unknown_ex_tempo_decomposition.json"
OUT_MD = REPO_ROOT / "data" / "meta_replays" / "unknown_ex_tempo_decomposition.md"
OUT_REFINED_YAML = REPO_ROOT / "data" / "meta_replays" / "archetypes_refined.yaml"

TARGET_ARCHETYPE = "unknown_ex_tempo"
GENERIC_LABEL = "generic_unknown_ex_tempo"

# Signature ex cards -> subfamily label. Every card id here is already present in
# the unknown_ex_tempo ``evidence_card_ids`` in archetypes.yaml. NO id is invented.
# A subfamily is only assigned when its signature card actually appears in a deck.
#
# NOTE: the authoritative card->name mapping is data/cards/EN_Card_Data.csv, NOT
# the ``evidence_card_names`` field in archetypes.yaml. That field had ids 678/756
# names swapped relative to the card DB; the labels below follow the card DB:
#   678 = Mega Lucario ex, 756 = Mega Kangaskhan ex.
SIGNATURE_MAP: dict[int, str] = {
    678: "mega_lucario_ex_tempo",         # Mega Lucario ex
    756: "mega_kangaskhan_energy_stack",  # Mega Kangaskhan ex
    121: "dragapult_ex",                  # Dragapult ex
    269: "lightning_bellibolt",           # Iono's Bellibolt ex
}
# Minimum copies of a signature card to count as a confident label.
SIGNATURE_MIN_COPIES = 2


def _load_card_metadata() -> dict[int, dict[str, str]]:
    """id -> {name, category, type, stage, rule}. Empty dict if unavailable."""
    meta: dict[int, dict[str, str]] = {}
    if not CARD_META_CSV.exists():
        return meta
    with CARD_META_CSV.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_id = (row.get("Card ID") or "").strip()
            if not raw_id.isdigit():
                continue
            meta[int(raw_id)] = {
                "name": (row.get("Card Name") or "").strip(),
                "category": (row.get("Category") or "").strip(),
                "type": (row.get("Type") or "").strip(),
                "stage": (row.get("Stage (Pokémon)/Type (Energy and Trainer)") or "").strip(),
                "rule": (row.get("Rule") or "").strip(),
            }
    return meta


def _read_deck(path: Path) -> list[int]:
    ids: list[int] = []
    for tok in path.read_text().split():
        tok = tok.strip().strip(",")
        if tok.isdigit():
            ids.append(int(tok))
    return ids


def _deck_path_for(episode_id: int, player_idx: str) -> Path:
    return DECKS_DIR / f"{episode_id}_{player_idx}_deck.csv"


def _fingerprint(ids: list[int]) -> str:
    import hashlib

    payload = ",".join(str(i) for i in sorted(ids))
    return hashlib.sha256(payload.encode()).hexdigest()


def _energy_distribution(counts: Counter, meta: dict[int, dict[str, str]]) -> dict[str, int]:
    dist: Counter = Counter()
    for cid, n in counts.items():
        m = meta.get(cid)
        if not m:
            continue
        if m.get("category", "").lower().startswith("energy"):
            etype = m.get("type") or m.get("stage") or "Unknown"
            dist[etype] += n
    return dict(sorted(dist.items(), key=lambda kv: -kv[1]))


def _category_counts(counts: Counter, meta: dict[int, dict[str, str]]) -> dict[str, int]:
    cat: Counter = Counter()
    for cid, n in counts.items():
        m = meta.get(cid)
        cat[(m.get("category") if m else "") or "Unknown"] += n
    return dict(sorted(cat.items(), key=lambda kv: -kv[1]))


def _ex_mega_hints(counts: Counter, meta: dict[int, dict[str, str]]) -> list[str]:
    hints: list[str] = []
    for cid, n in counts.items():
        m = meta.get(cid)
        if not m:
            continue
        name = m.get("name", "")
        low = name.lower()
        if " ex" in f" {low}" or low.endswith(" ex") or "mega " in low or "stage" in (m.get("stage", "").lower()):
            tag = name
            if "mega " in low:
                tag += " [Mega]"
            elif low.endswith(" ex") or " ex" in f" {low} ":
                tag += " [ex]"
            hints.append(f"{tag} x{n}")
    return sorted(set(hints))


def _distinctive_cards(counts: Counter, meta: dict[int, dict[str, str]], top: int = 8) -> list[dict[str, Any]]:
    """Top cards by copies, excluding plain basic energies (id<=10 heuristic)."""
    out: list[dict[str, Any]] = []
    for cid, n in counts.most_common():
        m = meta.get(cid, {})
        if m.get("category", "").lower().startswith("energy") and "basic" in m.get("rule", "").lower():
            continue
        if m.get("category", "").lower().startswith("energy") and cid <= 10:
            continue
        out.append({"card_id": cid, "copies": n, "card_name": m.get("name") or None})
        if len(out) >= top:
            break
    return out


def _classify(counts: Counter) -> tuple[str, str, list[str]]:
    """Return (subfamily, confidence, evidence)."""
    present = [(cid, counts[cid]) for cid in SIGNATURE_MAP if counts.get(cid, 0) >= SIGNATURE_MIN_COPIES]
    if not present:
        return GENERIC_LABEL, "low", ["no signature ex card found at >= %d copies" % SIGNATURE_MIN_COPIES]
    # Choose the signature with the most copies.
    cid, copies = max(present, key=lambda kv: kv[1])
    label = SIGNATURE_MAP[cid]
    confidence = "moderate" if copies >= 3 else "provisional"
    evidence = [f"signature card id {cid} present x{copies}"]
    if len(present) > 1:
        evidence.append(
            "multiple signatures present: "
            + ", ".join(f"{c}x{n}" for c, n in sorted(present, key=lambda kv: -kv[1]))
        )
    return label, confidence, evidence


def main() -> None:
    registry = json.loads(REGISTRY_JSON.read_text())
    archetypes_doc = yaml.safe_load(ARCHETYPES_YAML.read_text())
    meta = _load_card_metadata()
    metadata_available = bool(meta)

    target = None
    for a in archetypes_doc.get("archetypes", []):
        if a.get("archetype_id") == TARGET_ARCHETYPE:
            target = a
            break
    if target is None:
        raise SystemExit(f"archetype {TARGET_ARCHETYPE!r} not found in {ARCHETYPES_YAML}")

    episode_ids = list(target.get("replay_episode_ids", []))
    player_indices = target.get("player_indices", []) or []
    # Map episode -> player index (e.g. "p0").
    ep_to_pidx: dict[int, str] = {}
    for entry in player_indices:
        ep_str, _, pidx = str(entry).partition(":")
        if ep_str.isdigit():
            ep_to_pidx[int(ep_str)] = pidx or "p0"

    # Map episode -> result from our perspective using the registry records.
    ep_to_result: dict[int, str] = {}
    ep_to_opp_name: dict[int, str] = {}
    for rec in registry.get("records", []):
        ep = rec.get("episode_id")
        if ep is None:
            continue
        ep_to_result[int(ep)] = rec.get("perspective") or "unknown"
        ep_to_opp_name[int(ep)] = rec.get("opponent_name") or rec.get("opponent") or None

    episodes_out: list[dict[str, Any]] = []
    subfamily_members: dict[str, list[int]] = {}
    for ep in episode_ids:
        pidx = ep_to_pidx.get(ep, "p0")
        deck_path = _deck_path_for(ep, pidx)
        if not deck_path.exists():
            episodes_out.append({
                "episode_id": ep,
                "player_index": pidx,
                "error": f"deck file missing: {deck_path.name}",
            })
            continue
        ids = _read_deck(deck_path)
        counts = Counter(ids)
        subfamily, confidence, evidence = _classify(counts)
        subfamily_members.setdefault(subfamily, []).append(ep)
        episodes_out.append({
            "episode_id": ep,
            "opponent_name": ep_to_opp_name.get(ep),
            "player_index": pidx,
            "result_from_our_perspective": ep_to_result.get(ep),
            "deck_source": str(deck_path.relative_to(REPO_ROOT)),
            "card_count": len(ids),
            "unique_cards": len(counts),
            "deck_fingerprint": _fingerprint(ids),
            "closest_subfamily": subfamily,
            "confidence": confidence,
            "evidence": evidence,
            "top_distinctive_cards": _distinctive_cards(counts, meta),
            "energy_type_distribution": _energy_distribution(counts, meta) if metadata_available else {},
            "category_counts": _category_counts(counts, meta) if metadata_available else {},
            "ex_mega_stage_hints": _ex_mega_hints(counts, meta) if metadata_available else [],
        })

    # Build subfamily summaries (only those that actually have members, plus the
    # generic fallback which is always retained as a category).
    subfamilies: list[dict[str, Any]] = []
    all_labels = set(SIGNATURE_MAP.values()) | {GENERIC_LABEL}
    for label in sorted(all_labels):
        members = sorted(subfamily_members.get(label, []))
        sig_ids = [cid for cid, lab in SIGNATURE_MAP.items() if lab == label]
        if not members and label != GENERIC_LABEL:
            continue
        confidence = "low"
        if members:
            confidence = "moderate" if len(members) >= 2 else "provisional"
        if label == GENERIC_LABEL and not members:
            confidence = "n/a (no unlabelled decks this pass)"
        subfamilies.append({
            "subfamily_id": label,
            "n_episodes": len(members),
            "episode_ids": members,
            "signature_card_ids": sig_ids,
            "signature_card_names": [meta.get(c, {}).get("name") for c in sig_ids] if metadata_available else [],
            "confidence": confidence,
            "status": "provisional",
        })

    # Decomposition is "supported" when every source episode resolved to a named
    # (non-generic) subfamily and at least 2 distinct subfamilies emerged.
    named_eps = sum(len(subfamily_members.get(lbl, [])) for lbl in SIGNATURE_MAP.values())
    distinct_named = sum(1 for lbl in set(SIGNATURE_MAP.values()) if subfamily_members.get(lbl))
    decomposition_supported = named_eps == len(episode_ids) and distinct_named >= 2

    result = {
        "schema": "activegraph.meta.unknown_decomposition/v1",
        "pass": 13,
        "generated_by": "scripts/decompose_unknown_ex_tempo.py",
        "source_archetype": TARGET_ARCHETYPE,
        "card_metadata_available": metadata_available,
        "no_invented_card_ids": True,
        "signature_map": {str(k): v for k, v in SIGNATURE_MAP.items()},
        "source_episode_ids": sorted(episode_ids),
        "n_source_episodes": len(episode_ids),
        "decomposition_supported": decomposition_supported,
        "n_subfamilies_found": distinct_named,
        "unresolved_generic_episodes": sorted(subfamily_members.get(GENERIC_LABEL, [])),
        "subfamilies": subfamilies,
        "episodes": episodes_out,
    }

    OUT_JSON.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    OUT_MD.write_text(_render_md(result))
    _write_refined_archetypes(result, archetypes_doc)

    print(f"Wrote {OUT_JSON.relative_to(REPO_ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(REPO_ROOT)}")
    print(f"Wrote {OUT_REFINED_YAML.relative_to(REPO_ROOT)}")
    print(f"Source episodes: {len(episode_ids)} | named subfamilies: {distinct_named} | "
          f"supported: {decomposition_supported}")


def _render_md(result: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Unknown-EX Tempo Decomposition (Pass 13)")
    lines.append("")
    lines.append("> Documentation + meta-analysis only. No upload, no new candidates, "
                 "no invented card IDs.")
    lines.append("")
    lines.append(f"- Source archetype: `{result['source_archetype']}`")
    lines.append(f"- Source episodes analysed: **{result['n_source_episodes']}**")
    lines.append(f"- Named subfamilies found: **{result['n_subfamilies_found']}**")
    lines.append(f"- Decomposition supported by evidence: **{result['decomposition_supported']}**")
    lines.append(f"- Card metadata available (names/categories): **{result['card_metadata_available']}**")
    unresolved = result["unresolved_generic_episodes"]
    lines.append(f"- Unresolved (generic) episodes: **{len(unresolved)}**"
                 + (f" ({unresolved})" if unresolved else ""))
    lines.append("")
    lines.append("## Subfamilies")
    lines.append("")
    lines.append("| subfamily | episodes | n | signature cards | confidence | status |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for sf in result["subfamilies"]:
        sigs = ", ".join(
            f"{cid} ({name})" if name else str(cid)
            for cid, name in zip(sf["signature_card_ids"],
                                 sf.get("signature_card_names") or [None] * len(sf["signature_card_ids"]))
        ) or "—"
        eps = ", ".join(str(e) for e in sf["episode_ids"]) or "—"
        lines.append(f"| `{sf['subfamily_id']}` | {eps} | {sf['n_episodes']} | {sigs} | "
                     f"{sf['confidence']} | {sf['status']} |")
    lines.append("")
    lines.append("## Per-episode fingerprints")
    lines.append("")
    for ep in result["episodes"]:
        if ep.get("error"):
            lines.append(f"### Episode {ep['episode_id']} — ERROR: {ep['error']}")
            lines.append("")
            continue
        lines.append(f"### Episode {ep['episode_id']} ({ep['player_index']}) → "
                     f"`{ep['closest_subfamily']}`")
        lines.append("")
        lines.append(f"- Result (our perspective): `{ep['result_from_our_perspective']}`")
        lines.append(f"- Opponent name: {ep.get('opponent_name') or '_unknown_'}")
        lines.append(f"- Cards: {ep['card_count']} ({ep['unique_cards']} unique)")
        lines.append(f"- Confidence: {ep['confidence']}")
        lines.append(f"- Evidence: {'; '.join(ep['evidence'])}")
        lines.append(f"- Fingerprint: `{ep['deck_fingerprint'][:16]}…`")
        if ep["ex_mega_stage_hints"]:
            lines.append(f"- ex/Mega/Stage hints: {', '.join(ep['ex_mega_stage_hints'])}")
        if ep["energy_type_distribution"]:
            lines.append(f"- Energy types: {ep['energy_type_distribution']}")
        if ep["category_counts"]:
            lines.append(f"- Category counts: {ep['category_counts']}")
        tops = ", ".join(
            f"{c['card_id']}"
            + (f" ({c['card_name']})" if c.get("card_name") else "")
            + f" x{c['copies']}"
            for c in ep["top_distinctive_cards"]
        )
        lines.append(f"- Top distinctive cards: {tops}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _write_refined_archetypes(result: dict[str, Any], archetypes_doc: dict) -> None:
    """Emit archetypes_refined.yaml: confirmed archetypes preserved, unknown bucket
    replaced by evidence-grounded subfamilies."""
    confirmed = [
        {k: a.get(k) for k in ("archetype_id", "confidence", "is_ours",
                               "evidence_card_ids", "evidence_card_names",
                               "replay_episode_ids")}
        for a in archetypes_doc.get("archetypes", [])
        if a.get("archetype_id") != TARGET_ARCHETYPE
    ]
    refined_subfamilies = []
    for sf in result["subfamilies"]:
        if sf["n_episodes"] == 0 and sf["subfamily_id"] != GENERIC_LABEL:
            continue
        refined_subfamilies.append({
            "archetype_id": sf["subfamily_id"],
            "parent": TARGET_ARCHETYPE,
            "confidence": sf["confidence"],
            "status": sf["status"],
            "is_ours": False,
            "n_episodes": sf["n_episodes"],
            "replay_episode_ids": sf["episode_ids"],
            "signature_card_ids": sf["signature_card_ids"],
            "signature_card_names": sf.get("signature_card_names") or [],
        })
    doc = {
        "schema": "activegraph.meta.archetypes_refined/v1",
        "pass": 13,
        "generated_by": "scripts/decompose_unknown_ex_tempo.py",
        "note": ("unknown_ex_tempo decomposed into evidence-grounded subfamilies. "
                 "Confirmed archetypes carried over unchanged. No invented card IDs."),
        "decomposition_supported": result["decomposition_supported"],
        "confirmed_and_other_archetypes": confirmed,
        "unknown_ex_tempo_subfamilies": refined_subfamilies,
    }
    OUT_REFINED_YAML.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))


if __name__ == "__main__":
    main()
