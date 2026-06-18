"""Build the canonical replay registry from inbox entries.

Responsibilities (Pass 11B):
* Deduplicate inbox entries by ``EpisodeId`` (and, for byte-identical
  re-uploads, by file sha256). The first-seen file for an episode wins; later
  duplicates are recorded but not re-processed.
* Attribute each seat's deck to a known *own* deck (v1 / v2 / a pass-10
  candidate) by multiset fingerprint, or label it an opponent deck.
* Determine match perspective relative to *us* (our_win / our_loss / our_draw /
  self_mirror / opponent_only_or_unknown / error_or_invalid).
* Classify the opponent deck's archetype via ``meta.archetypes.classify_deck``.

No card id is invented; opponent ids come straight from the replay action.
"""

from __future__ import annotations

import tarfile
from pathlib import Path

from ..meta import archetypes as arch_mod
from . import fingerprints as fp
from .inbox import name_is_ours

# --- known own-deck sources ------------------------------------------------

# High-priority labelled own decks (matched first, in this order).
_OWN_DECK_FILES: dict[str, str] = {
    "v1_deck_loader_fix": "data/baselines/v1_kaggle_349_8/deck.csv",
    "v2_deck_energy_trim_light": "data/baselines/v2_kaggle_479_1_deck_energy_trim_light/deck.csv",
}
_OWN_DECK_TARBALLS: dict[str, str] = {
    "combo_full_safety_v3_fixed": "data/submissions/candidates/combo_full_safety_v3_fixed.tar.gz",
}
# Where pass-10 / generated candidate decks live (each gets pass10_candidate_<id>).
_PASS10_TARBALL_DIRS = (
    "data/submissions/candidates",
    "data/submissions/candidates_pass10",
)
_PASS10_DECK_GLOBS = (
    "data/baselines/_pass10_deck_variants/*/deck.csv",
)


def _read_deck_ids_text(text: str) -> list[int]:
    out: list[int] = []
    for tok in text.replace(",", "\n").split():
        tok = tok.strip()
        if tok.isdigit() or (tok.startswith("-") and tok[1:].isdigit()):
            out.append(int(tok))
    return out


def _read_deck_csv(path: Path) -> list[int]:
    try:
        return _read_deck_ids_text(path.read_text(encoding="utf-8"))
    except OSError:
        return []


def _read_deck_from_tarball(path: Path) -> list[int]:
    if not path.exists():
        return []
    try:
        with tarfile.open(path, "r:gz") as tf:
            for m in tf.getmembers():
                if Path(m.name).name == "deck.csv":
                    fh = tf.extractfile(m)
                    if fh is None:
                        return []
                    return _read_deck_ids_text(fh.read().decode("utf-8"))
            return []
    except (tarfile.TarError, OSError):
        return []


def load_known_own_decks(repo_root: str | Path) -> dict[str, list[int]]:
    """Return ``{deck_label: card_ids}`` for every known own deck on disk.

    Insertion order is the match priority: the canonical v1 / v2 / combo labels
    win over generic ``pass10_candidate_<id>`` labels for shared multisets.
    """
    repo = Path(repo_root)
    known: dict[str, list[int]] = {}

    # 1. Canonical baselines (root deck.csv shares v1's multiset).
    for label, rel in _OWN_DECK_FILES.items():
        ids = _read_deck_csv(repo / rel)
        if ids:
            known[label] = ids
    # 2. Named candidate tarballs with dedicated labels.
    for label, rel in _OWN_DECK_TARBALLS.items():
        ids = _read_deck_from_tarball(repo / rel)
        if ids:
            known[label] = ids
    # 3. Pass-10 / generated candidates -> pass10_candidate_<id>.
    seen_labels = set(known)
    for d in _PASS10_TARBALL_DIRS:
        tdir = repo / d
        if not tdir.is_dir():
            continue
        for tar in sorted(tdir.glob("*.tar.gz")):
            label = f"pass10_candidate_{tar.name[:-len('.tar.gz')]}"
            if label in seen_labels:
                continue
            ids = _read_deck_from_tarball(tar)
            if ids:
                known.setdefault(label, ids)
    for g in _PASS10_DECK_GLOBS:
        for deck in sorted(repo.glob(g)):
            label = f"pass10_candidate_{deck.parent.name}"
            ids = _read_deck_csv(deck)
            if ids:
                known.setdefault(label, ids)
    return known


def _seat_is_ours(entry: dict, seat: int, known_own: dict[str, list[int]]) -> bool:
    """A seat is ours if its agent name matches OR its deck multiset matches a
    known own deck."""
    if seat in entry.get("our_seats_by_name", []):
        return True
    deck = entry.get("decks", {}).get(str(seat))
    if deck and fp.match_multiset(deck, known_own) is not None:
        return True
    return False


def _deck_label(deck: list[int] | None, known_own: dict[str, list[int]],
                is_ours: bool) -> str:
    if not deck:
        return "unknown_own_deck" if is_ours else "opponent_unknown"
    match = fp.match_multiset(deck, known_own)
    if match:
        return match
    return "unknown_own_deck" if is_ours else "opponent_unknown"


def build_seat_record(entry: dict, seat: int, known_own: dict[str, list[int]],
                      card_names: dict[int, str] | None) -> dict:
    deck = entry.get("decks", {}).get(str(seat)) or []
    is_ours = _seat_is_ours(entry, seat, known_own)
    label = _deck_label(deck, known_own, is_ours)
    rec = {
        "seat": seat,
        "agent": (entry.get("agents") or [None] * (seat + 1))[seat]
        if seat < len(entry.get("agents") or []) else None,
        "is_ours": is_ours,
        "deck_label": label,
        "fingerprint": fp.deck_fingerprint(deck) if deck else None,
    }
    if not is_ours and deck:
        rec["archetype"] = arch_mod.classify_deck(deck, is_own_deck=False,
                                                  card_names=card_names)
    elif is_ours and deck:
        rec["archetype"] = arch_mod.classify_deck(deck, is_own_deck=True,
                                                  card_names=card_names)
    else:
        rec["archetype"] = None
    return rec


def _perspective(entry: dict, seats: list[dict]) -> dict:
    statuses = entry.get("statuses") or []
    rewards = entry.get("rewards") or []
    if entry.get("status") == "failed_parse" or not seats:
        return {"perspective": "error_or_invalid", "our_seat": None,
                "our_reward": None}
    if statuses and any(s not in ("DONE", "ACTIVE", "INACTIVE") for s in statuses):
        return {"perspective": "error_or_invalid", "our_seat": None,
                "our_reward": None}
    our_seats = [s["seat"] for s in seats if s["is_ours"]]
    if len(our_seats) >= 2:
        return {"perspective": "self_mirror", "our_seat": our_seats,
                "our_reward": None}
    if len(our_seats) == 0:
        return {"perspective": "opponent_only_or_unknown", "our_seat": None,
                "our_reward": None}
    seat = our_seats[0]
    reward = rewards[seat] if seat < len(rewards) else None
    if reward is None:
        persp = "opponent_only_or_unknown"
    elif reward > 0:
        persp = "our_win"
    elif reward < 0:
        persp = "our_loss"
    else:
        persp = "our_draw"
    return {"perspective": persp, "our_seat": seat, "our_reward": reward}


def build_registry(entries: list[dict], known_own: dict[str, list[int]],
                   card_names: dict[int, str] | None = None) -> dict:
    """Build the deduplicated registry object from raw inbox entries."""
    records: list[dict] = []
    errors: list[dict] = []
    seen_episode: dict = {}
    seen_file_sha: dict[str, str] = {}
    duplicates: list[dict] = []

    for entry in entries:
        if entry.get("status") == "failed_parse":
            errors.append({
                "filename": entry.get("filename"),
                "path": entry.get("path"),
                "error": entry.get("error"),
                "file_sha256": entry.get("file_sha256"),
            })
            continue

        episode = entry.get("episode_id")
        sha = entry.get("file_sha256")

        if sha and sha in seen_file_sha:
            duplicates.append({"filename": entry.get("filename"),
                               "episode_id": episode,
                               "status": "duplicate_file_hash",
                               "same_as": seen_file_sha[sha]})
            continue
        if episode is not None and episode in seen_episode:
            duplicates.append({"filename": entry.get("filename"),
                               "episode_id": episode,
                               "status": "duplicate_episode",
                               "same_as": seen_episode[episode]})
            continue

        seats = [build_seat_record(entry, int(s), known_own, card_names)
                 for s in sorted(entry.get("decks", {}), key=int)]
        persp = _perspective(entry, seats)

        record = {
            "episode_id": episode,
            "filename": entry.get("filename"),
            "file_sha256": sha,
            "status": entry.get("status", "parsed"),
            "module_version": entry.get("module_version"),
            "agents": entry.get("agents"),
            "rewards": entry.get("rewards"),
            "statuses": entry.get("statuses"),
            "num_steps": entry.get("num_steps"),
            "warnings": entry.get("warnings", []),
            "seats": seats,
            **persp,
        }
        records.append(record)
        if sha:
            seen_file_sha[sha] = entry.get("filename")
        if episode is not None:
            seen_episode[episode] = entry.get("filename")

    records.sort(key=lambda r: str(r.get("episode_id")))
    return {
        "schema": "activegraph.replays.registry/v1",
        "pass": "11b",
        "replays_total": len(entries),
        "replays_registered": len(records),
        "duplicates_skipped": duplicates,
        "errors": errors,
        "known_own_decks": sorted(known_own),
        "records": records,
    }
