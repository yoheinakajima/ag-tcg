"""Build the Kaggle submission tarball.

The submission is a ``.tar.gz`` containing exactly the runtime files:

* ``main.py`` (required entrypoint exposing ``agent``)
* ``deck.csv`` (required, 60 integer card IDs)
* any small local runtime modules ``main.py`` imports (optional)

Docs, tests, data and replays are deliberately excluded to keep it small.
"""

from __future__ import annotations

import tarfile
from pathlib import Path

from ..decks.deck_io import load_deck
from ..decks.validator import validate_deck


class SubmissionError(RuntimeError):
    """Raised when submission inputs are invalid."""


def verify_submission_inputs(
    main_py: str | Path,
    deck_csv: str | Path,
    card_db=None,
) -> dict:
    """Verify ``main.py`` exists and ``deck.csv`` is a valid 60-int decklist.

    Returns a report dict. Raises :class:`SubmissionError` on hard failures.
    """
    main_py = Path(main_py)
    deck_csv = Path(deck_csv)

    if not main_py.exists():
        raise SubmissionError(f"main.py not found at {main_py}")
    if not deck_csv.exists():
        raise SubmissionError(f"deck.csv not found at {deck_csv}")

    card_ids = load_deck(deck_csv)
    result = validate_deck(card_ids, card_db=card_db)
    if not result.valid:
        raise SubmissionError(
            "deck.csv failed validation: " + "; ".join(result.errors)
        )

    return {
        "main_py": str(main_py),
        "deck_csv": str(deck_csv),
        "deck_size": result.size,
        "deck_valid": result.valid,
        "warnings": result.warnings,
    }


def build_submission(
    main_py: str | Path = "main.py",
    deck_csv: str | Path = "deck.csv",
    out_path: str | Path = "data/submissions/submission.tar.gz",
    extra_files: list[str | Path] | None = None,
    card_db=None,
) -> Path:
    """Create the submission tarball after verifying inputs.

    ``extra_files`` are additional small runtime modules to include (e.g.
    ``agent.py`` if ``main.py`` imports it). They are added at the archive root.
    """
    report = verify_submission_inputs(main_py, deck_csv, card_db=card_db)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    members: list[tuple[Path, str]] = [
        (Path(main_py), "main.py"),
        (Path(deck_csv), "deck.csv"),
    ]
    for extra in extra_files or []:
        p = Path(extra)
        if p.exists():
            members.append((p, p.name))

    with tarfile.open(out_path, "w:gz") as tar:
        for path, arcname in members:
            tar.add(path, arcname=arcname)

    report["tarball"] = str(out_path)
    report["members"] = [arc for _, arc in members]
    return out_path
