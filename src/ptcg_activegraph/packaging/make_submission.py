"""Build and verify the Kaggle submission tarball.

The submission is a ``.tar.gz`` containing exactly the runtime files at the
archive **root** (no nested directory):

* ``main.py`` (required entrypoint exposing ``agent``)
* ``deck.csv`` (required, exactly 60 integer card IDs, not a placeholder)
* any small local runtime modules ``main.py`` imports (optional, e.g. agent.py)

Docs, tests, data and replays are deliberately excluded to keep it small.

Preflight (``verify_submission_inputs``) is intentionally strict so likely
Kaggle failures are caught *before* upload:

* main.py exists and imports without error,
* ``main.agent({})`` returns a ``list``,
* deck.csv has exactly 60 integer rows,
* deck.csv is not a detected placeholder.

``inspect_tarball`` re-opens a built archive and checks for top-level-only
``main.py``/``deck.csv`` and the absence of nested/unwanted files.
"""

from __future__ import annotations

import importlib.util
import tarfile
from pathlib import Path

from ..decks.deck_io import load_deck
from ..decks.resolve_deck import is_placeholder_deck, load_deck_meta
from ..decks.validator import validate_deck

# Files/dirs that must never appear in the submission tarball.
_FORBIDDEN_PREFIXES = ("docs/", "tests/", "data/", "src/", "scripts/")


class SubmissionError(RuntimeError):
    """Raised when submission inputs or a built tarball are invalid."""


def _import_main(main_py: Path):
    """Import a main.py file in isolation; raise SubmissionError on failure."""
    spec = importlib.util.spec_from_file_location("ptcg_submission_main", main_py)
    if spec is None or spec.loader is None:
        raise SubmissionError(f"could not load module spec for {main_py}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - report the real import error
        raise SubmissionError(f"main.py failed to import: {exc!r}") from exc
    if not hasattr(module, "agent") or not callable(module.agent):
        raise SubmissionError("main.py does not define a callable `agent`")
    return module


def verify_submission_inputs(
    main_py: str | Path = "main.py",
    deck_csv: str | Path = "deck.csv",
    card_db=None,
    allow_placeholder: bool = False,
) -> dict:
    """Strict preflight. Returns a report dict; raises on hard failures."""
    main_py = Path(main_py)
    deck_csv = Path(deck_csv)

    if not main_py.exists():
        raise SubmissionError(f"main.py not found at {main_py}")
    if not deck_csv.exists():
        raise SubmissionError(f"deck.csv not found at {deck_csv}")

    # main.py must import and expose a callable agent that returns a list.
    module = _import_main(main_py)
    checks: list[str] = []
    for probe in ({}, None, {"select": None}):
        try:
            out = module.agent(probe)
        except Exception as exc:  # noqa: BLE001
            raise SubmissionError(
                f"main.agent({probe!r}) raised {exc!r}; runtime must never crash"
            ) from exc
        if not isinstance(out, list):
            raise SubmissionError(
                f"main.agent({probe!r}) returned {type(out).__name__}, expected list"
            )
    checks.append("main.agent returns a list for empty/None/null-select inputs")

    # Deck: exactly 60 integers.
    card_ids = load_deck(deck_csv)
    result = validate_deck(card_ids, card_db=card_db)
    if not result.valid:
        raise SubmissionError("deck.csv failed validation: " + "; ".join(result.errors))

    # Deck: not a placeholder.
    meta = load_deck_meta(deck_csv)
    placeholder = is_placeholder_deck(card_ids, meta=meta, card_db=card_db)
    if placeholder and not allow_placeholder:
        raise SubmissionError(
            "deck.csv looks like a PLACEHOLDER (not competitive). "
            "Run `python scripts/resolve_deck.py` to install a real deck, or pass "
            "--allow-placeholder to override (will likely fail Kaggle scoring)."
        )

    return {
        "main_py": str(main_py),
        "deck_csv": str(deck_csv),
        "deck_size": result.size,
        "deck_unique": len(set(card_ids)),
        "deck_valid": result.valid,
        "deck_placeholder": placeholder,
        "deck_source": meta.get("source", "unknown"),
        "checks": checks,
        "warnings": result.warnings,
    }


def inspect_tarball(out_path: str | Path) -> dict:
    """Re-open a built tarball and assert it is clean. Raises on problems."""
    out_path = Path(out_path)
    if not out_path.exists():
        raise SubmissionError(f"tarball not found at {out_path}")

    with tarfile.open(out_path, "r:gz") as tar:
        names = tar.getnames()

    problems: list[str] = []
    if "main.py" not in names:
        problems.append("missing top-level main.py")
    if "deck.csv" not in names:
        problems.append("missing top-level deck.csv")
    for name in names:
        # No nesting: members must be at the archive root.
        if "/" in name.strip("/"):
            problems.append(f"nested path not allowed: {name}")
        if any(name.startswith(p) for p in _FORBIDDEN_PREFIXES):
            problems.append(f"forbidden content: {name}")

    if problems:
        raise SubmissionError("tarball inspection failed: " + "; ".join(problems))

    return {"tarball": str(out_path), "members": names}


def build_submission(
    main_py: str | Path = "main.py",
    deck_csv: str | Path = "deck.csv",
    out_path: str | Path = "data/submissions/submission.tar.gz",
    extra_files: list[str | Path] | None = None,
    card_db=None,
    allow_placeholder: bool = False,
) -> Path:
    """Verify inputs, build the tarball, then inspect it. Returns the path."""
    verify_submission_inputs(
        main_py, deck_csv, card_db=card_db, allow_placeholder=allow_placeholder
    )
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

    # Post-build inspection (raises if nested/forbidden/missing).
    inspect_tarball(out_path)
    return out_path
