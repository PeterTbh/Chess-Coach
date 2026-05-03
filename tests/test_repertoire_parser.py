"""Tests for the Module B repertoire parser (Phase 2 Slice 3)."""

from __future__ import annotations

from pathlib import Path

import chess
import pytest

from src.repertoire.parser import (
    DEFAULT_FILENAMES,
    ExpectedMove,
    Repertoire,
    RepertoireError,
    RepertoireNotFoundError,
    RepertoireParseError,
    load_default_repertoire,
    load_repertoire,
)

# ---- Fixtures -------------------------------------------------------------

# Two-game repertoire:
# 1) Spanish mainline with a 3.Bc4 sideline.
# 2) Italian (transposition: position after 3.Bc4 Bc5 is reached by both).
SPANISH_PLUS_ITALIAN_PGN = """
[Event "Spanish mainline"]
[Site "?"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 (3. Bc4 Bc5) a6 4. Ba4 Nf6 *

[Event "Italian"]
[Site "?"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 *
""".strip()


SINGLE_LINE_BLACK_PGN = """
[Event "Caro-Kann"]
[Result "*"]

1. e4 c6 2. d4 d5 *
""".strip()


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ---- load_repertoire: happy path ------------------------------------------

def test_load_repertoire_returns_repertoire_object(tmp_path: Path) -> None:
    path = _write(tmp_path, "white.pgn", SPANISH_PLUS_ITALIAN_PGN)
    rep = load_repertoire(path, "white")
    assert isinstance(rep, Repertoire)
    assert rep.color == "white"
    assert len(rep.games) == 2  # Spanish + Italian


def test_load_repertoire_indexes_starting_position(tmp_path: Path) -> None:
    path = _write(tmp_path, "white.pgn", SPANISH_PLUS_ITALIAN_PGN)
    rep = load_repertoire(path, "white")
    start_fen = chess.STARTING_FEN
    expected = rep.expected_at(start_fen)
    assert len(expected) == 1
    assert expected[0].san == "e4"
    assert expected[0].uci == "e2e4"


def test_load_repertoire_indexes_sideline(tmp_path: Path) -> None:
    """After 1.e4 e5 2.Nf3 Nc6, both 3.Bb5 and 3.Bc4 should be expected."""
    path = _write(tmp_path, "white.pgn", SPANISH_PLUS_ITALIAN_PGN)
    rep = load_repertoire(path, "white")

    board = chess.Board()
    for san in ["e4", "e5", "Nf3", "Nc6"]:
        board.push_san(san)
    expected = rep.expected_at(board.fen())
    sans = [m.san for m in expected]
    # Mainline first, sideline second.
    assert sans == ["Bb5", "Bc4"]


def test_load_repertoire_handles_transposition(tmp_path: Path) -> None:
    """Position after 1.e4 e5 2.Nf3 Nc6 3.Bc4 must yield Bc5 (from both games)."""
    path = _write(tmp_path, "white.pgn", SPANISH_PLUS_ITALIAN_PGN)
    rep = load_repertoire(path, "white")

    board = chess.Board()
    for san in ["e4", "e5", "Nf3", "Nc6", "Bc4"]:
        board.push_san(san)
    expected = rep.expected_at(board.fen())
    # Deduped by SAN — only one Bc5 entry, even though two games reach here.
    assert [m.san for m in expected] == ["Bc5"]


def test_load_repertoire_indexes_full_mainline_depth(tmp_path: Path) -> None:
    """Spanish line: 4.Ba4 then 4...Nf6 should both be indexed."""
    path = _write(tmp_path, "white.pgn", SPANISH_PLUS_ITALIAN_PGN)
    rep = load_repertoire(path, "white")

    board = chess.Board()
    for san in ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]:
        board.push_san(san)
    assert [m.san for m in rep.expected_at(board.fen())] == ["Ba4"]

    board.push_san("Ba4")
    assert [m.san for m in rep.expected_at(board.fen())] == ["Nf6"]


def test_load_repertoire_records_line_name(tmp_path: Path) -> None:
    path = _write(tmp_path, "white.pgn", SPANISH_PLUS_ITALIAN_PGN)
    rep = load_repertoire(path, "white")
    moves_at_start = rep.expected_at(chess.STARTING_FEN)
    # First-encountered game's name (Spanish) wins for the shared start.
    assert moves_at_start[0].line_name == "Spanish mainline"


def test_load_repertoire_black_color(tmp_path: Path) -> None:
    path = _write(tmp_path, "black.pgn", SINGLE_LINE_BLACK_PGN)
    rep = load_repertoire(path, "black")
    assert rep.color == "black"
    # After 1.e4, Black plays c6.
    board = chess.Board()
    board.push_san("e4")
    expected = rep.expected_at(board.fen())
    assert [m.san for m in expected] == ["c6"]


def test_load_repertoire_accepts_string_path(tmp_path: Path) -> None:
    path = _write(tmp_path, "white.pgn", SPANISH_PLUS_ITALIAN_PGN)
    rep = load_repertoire(str(path), "white")
    assert len(rep.games) == 2


def test_covers_returns_false_for_unknown_position(tmp_path: Path) -> None:
    path = _write(tmp_path, "white.pgn", SPANISH_PLUS_ITALIAN_PGN)
    rep = load_repertoire(path, "white")
    # 1.d4 is not in this repertoire.
    board = chess.Board()
    board.push_san("d4")
    assert rep.covers(board.fen()) is False
    assert rep.expected_at(board.fen()) == []


# ---- load_repertoire: errors ----------------------------------------------

def test_load_repertoire_raises_not_found_on_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope.pgn"
    with pytest.raises(RepertoireNotFoundError):
        load_repertoire(missing, "white")


def test_load_repertoire_raises_parse_error_on_empty_file(tmp_path: Path) -> None:
    path = _write(tmp_path, "white.pgn", "")
    with pytest.raises(RepertoireParseError):
        load_repertoire(path, "white")


def test_load_repertoire_raises_parse_error_on_garbage(tmp_path: Path) -> None:
    path = _write(tmp_path, "white.pgn", "this is not pgn at all just words")
    with pytest.raises(RepertoireParseError):
        load_repertoire(path, "white")


def test_load_repertoire_skips_header_only_block(tmp_path: Path) -> None:
    """A PGN with only headers and no moves should be treated as empty."""
    pgn = '[Event "?"]\n[Result "*"]\n\n*'
    path = _write(tmp_path, "white.pgn", pgn)
    with pytest.raises(RepertoireParseError):
        load_repertoire(path, "white")


def test_repertoire_error_hierarchy_is_consistent() -> None:
    assert issubclass(RepertoireNotFoundError, RepertoireError)
    assert issubclass(RepertoireParseError, RepertoireError)


# ---- ExpectedMove --------------------------------------------------------

def test_expected_move_is_immutable() -> None:
    em = ExpectedMove(san="e4", uci="e2e4", line_name="Test")
    with pytest.raises((AttributeError, TypeError)):
        em.san = "d4"  # type: ignore[misc]


# ---- load_default_repertoire ---------------------------------------------

def test_load_default_repertoire_uses_conventional_filenames(tmp_path: Path) -> None:
    (tmp_path / "white.pgn").write_text(SPANISH_PLUS_ITALIAN_PGN, encoding="utf-8")
    (tmp_path / "black.pgn").write_text(SINGLE_LINE_BLACK_PGN, encoding="utf-8")

    white = load_default_repertoire("white", base_dir=tmp_path)
    black = load_default_repertoire("black", base_dir=tmp_path)
    assert len(white.games) == 2
    assert len(black.games) == 1


def test_load_default_repertoire_raises_when_file_missing(tmp_path: Path) -> None:
    # Empty dir.
    with pytest.raises(RepertoireNotFoundError):
        load_default_repertoire("white", base_dir=tmp_path)


def test_default_filenames_constant_shape() -> None:
    assert DEFAULT_FILENAMES == {"white": "white.pgn", "black": "black.pgn"}
