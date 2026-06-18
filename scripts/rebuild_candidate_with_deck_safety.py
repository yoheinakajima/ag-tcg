#!/usr/bin/env python3
"""Rebuild a candidate tarball with the deck-return safety block applied.

Packaging/runtime fix ONLY: the candidate strategy (its main.py policy logic and
its deck.csv) is preserved exactly — this just appends the embedded-deck +
robust ``select=None`` detection block (see
``ptcg_activegraph.experiments.generator.inject_deck_safety``) so the candidate's
own main.py always returns its 60-card deck on the cabt deck-selection step.

Source may be a candidate run directory (containing main.py + deck.csv) or an
existing candidate .tar.gz. Output is a flat tarball with top-level main.py +
deck.csv.

Usage:
    python scripts/rebuild_candidate_with_deck_safety.py \
        --source experiments/runs_pass9/<run>/ \
        --out data/submissions/candidates/<id>_fixed.tar.gz
"""

from __future__ import annotations

import argparse
import tarfile
import tempfile
from pathlib import Path

import _bootstrap  # noqa: F401

from ptcg_activegraph.experiments.generator import inject_deck_safety


def _read_source(source: Path) -> tuple[str, str]:
    """Return (main_py_text, deck_csv_text) from a dir or a .tar.gz."""
    if source.is_dir():
        return ((source / "main.py").read_text(encoding="utf-8"),
                (source / "deck.csv").read_text(encoding="utf-8"))
    if source.suffix in (".gz", ".tgz") or source.name.endswith(".tar.gz"):
        with tempfile.TemporaryDirectory() as tmp:
            with tarfile.open(source, "r:gz") as tar:
                tar.extractall(tmp)  # noqa: S202
            tmp_dir = Path(tmp)
            main = next(tmp_dir.rglob("main.py"))
            deck = next(tmp_dir.rglob("deck.csv"))
            return (main.read_text(encoding="utf-8"),
                    deck.read_text(encoding="utf-8"))
    raise ValueError(f"unsupported source: {source}")


def _deck_ids(deck_text: str) -> list[int]:
    return [int(x.strip()) for x in deck_text.splitlines() if x.strip()]


def rebuild(source: str, out: str) -> int:
    src = Path(source)
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    main_text, deck_text = _read_source(src)
    deck_ids = _deck_ids(deck_text)
    if len(deck_ids) != 60:
        print(f"FAIL: source deck.csv has {len(deck_ids)} rows, expected 60")
        return 1

    fixed_main = inject_deck_safety(main_text, deck_ids)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        (tmp_dir / "main.py").write_text(fixed_main, encoding="utf-8")
        # Normalise deck.csv to one integer per line (no header/whitespace).
        (tmp_dir / "deck.csv").write_text(
            "\n".join(str(c) for c in deck_ids) + "\n", encoding="utf-8")
        with tarfile.open(out_path, "w:gz") as tar:
            tar.add(tmp_dir / "main.py", arcname="main.py")
            tar.add(tmp_dir / "deck.csv", arcname="deck.csv")

    print(f"OK: wrote {out_path} ({out_path.stat().st_size} bytes)")
    print("  deck-safety block applied:",
          "# === DECK-RETURN SAFETY" in fixed_main)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True,
                        help="candidate run dir or .tar.gz")
    parser.add_argument("--out", required=True, help="output .tar.gz path")
    args = parser.parse_args()
    return rebuild(args.source, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
