"""Tests for the Kaggle submission packager (hardened)."""

import tarfile

import pytest

from ptcg_activegraph.packaging.make_submission import (
    SubmissionError,
    build_submission,
    inspect_tarball,
    verify_submission_inputs,
)


def _write_main(path):
    path.write_text("def agent(obs):\n    return []\n", encoding="utf-8")


def _write_real_deck(path, n=60):
    # Realistic-looking large card IDs (NOT the 1..15 placeholder pattern).
    ids = [1000 + (i % 20) for i in range(n)]
    path.write_text("\n".join(str(i) for i in ids) + "\n", encoding="utf-8")


def _write_placeholder_deck(path):
    ids = [c for c in range(1, 16) for _ in range(4)]  # 1..15 x4 == placeholder
    path.write_text("\n".join(str(i) for i in ids) + "\n", encoding="utf-8")


def test_build_tarball(tmp_path):
    main_py = tmp_path / "main.py"
    deck_csv = tmp_path / "deck.csv"
    out = tmp_path / "submission.tar.gz"
    _write_main(main_py)
    _write_real_deck(deck_csv)

    result = build_submission(main_py, deck_csv, out)
    assert result.exists()
    with tarfile.open(result, "r:gz") as tar:
        names = tar.getnames()
    assert "main.py" in names
    assert "deck.csv" in names


def test_rejects_invalid_deck(tmp_path):
    main_py = tmp_path / "main.py"
    deck_csv = tmp_path / "deck.csv"
    _write_main(main_py)
    _write_real_deck(deck_csv, n=40)  # not 60

    with pytest.raises(SubmissionError):
        build_submission(main_py, deck_csv, tmp_path / "s.tar.gz")


def test_rejects_missing_main(tmp_path):
    deck_csv = tmp_path / "deck.csv"
    _write_real_deck(deck_csv)
    with pytest.raises(SubmissionError):
        verify_submission_inputs(tmp_path / "missing_main.py", deck_csv)


def test_rejects_placeholder_deck(tmp_path):
    main_py = tmp_path / "main.py"
    deck_csv = tmp_path / "deck.csv"
    _write_main(main_py)
    _write_placeholder_deck(deck_csv)
    with pytest.raises(SubmissionError):
        verify_submission_inputs(main_py, deck_csv)
    # Override is allowed explicitly.
    report = verify_submission_inputs(main_py, deck_csv, allow_placeholder=True)
    assert report["deck_placeholder"] is True


def test_rejects_main_that_does_not_return_list(tmp_path):
    main_py = tmp_path / "main.py"
    deck_csv = tmp_path / "deck.csv"
    main_py.write_text("def agent(obs):\n    return 'nope'\n", encoding="utf-8")
    _write_real_deck(deck_csv)
    with pytest.raises(SubmissionError):
        verify_submission_inputs(main_py, deck_csv)


def test_rejects_main_that_crashes(tmp_path):
    main_py = tmp_path / "main.py"
    deck_csv = tmp_path / "deck.csv"
    main_py.write_text("def agent(obs):\n    raise RuntimeError('boom')\n", encoding="utf-8")
    _write_real_deck(deck_csv)
    with pytest.raises(SubmissionError):
        verify_submission_inputs(main_py, deck_csv)


def test_inspect_catches_nested_paths(tmp_path):
    # Build a bad tarball with a nested directory and assert inspection fails.
    main_py = tmp_path / "main.py"
    deck_csv = tmp_path / "deck.csv"
    _write_main(main_py)
    _write_real_deck(deck_csv)
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(bad, "w:gz") as tar:
        tar.add(main_py, arcname="sub/main.py")   # nested!
        tar.add(deck_csv, arcname="deck.csv")
    with pytest.raises(SubmissionError):
        inspect_tarball(bad)


def test_extra_files_included(tmp_path):
    main_py = tmp_path / "main.py"
    deck_csv = tmp_path / "deck.csv"
    agent_py = tmp_path / "agent.py"
    _write_main(main_py)
    _write_real_deck(deck_csv)
    agent_py.write_text("def agent(obs):\n    return []\n", encoding="utf-8")

    out = build_submission(main_py, deck_csv, tmp_path / "s.tar.gz",
                           extra_files=[agent_py])
    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
    assert "agent.py" in names
