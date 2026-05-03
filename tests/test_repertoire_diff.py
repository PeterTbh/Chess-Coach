"""Tests for the Module B diff (Phase 3 Slice 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.repertoire.diff import DiffError, diff_game
from src.repertoire.parser import load_repertoire

# ---- Fixtures ------------------------------------------------------------

# White repertoire: Spanish mainline with a Bc4 sideline + Italian transposition.
WHITE_REP_PGN = """
[Event "Spanish mainline"]
[Site "?"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 (3. Bc4 Bc5) a6 4. Ba4 Nf6 5. O-O *

[Event "Italian"]
[Site "?"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 *
""".strip()


# Black repertoire: Caro-Kann.
BLACK_REP_PGN = """
[Event "Caro-Kann advance"]
[Result "*"]

1. e4 c6 2. d4 d5 3. e5 Bf5 *
""".strip()


def _played_pgn(white: str, black: str, moves: str, result: str = "*") -> str:
    return (
        f'[Event "Test"]\n'
        f'[White "{white}"]\n'
        f'[Black "{black}"]\n'
        f'[Result "{result}"]\n\n'
        f"{moves} {result}\n"
    )


@pytest.fixture
def white_rep(tmp_path: Path):
    p = tmp_path / "white.pgn"
    p.write_text(WHITE_REP_PGN, encoding="utf-8")
    return load_repertoire(p, "white")


@pytest.fixture
def black_rep(tmp_path: Path):
    p = tmp_path / "black.pgn"
    p.write_text(BLACK_REP_PGN, encoding="utf-8")
    return load_repertoire(p, "black")


# ---- Happy-path: user stays in book --------------------------------------

def test_in_book_full_mainline_no_deviation(white_rep) -> None:
    pgn = _played_pgn(
        "alex", "opp",
        "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O",
    )
    result = diff_game(pgn, "alex", white_rep)
    assert result.deviated is False
    assert result.deviation_move_number is None
    assert result.move_played is None
    assert result.repertoire_line_name == "Spanish mainline"


def test_sideline_match_is_not_a_deviation(white_rep) -> None:
    """User plays the Bc4 sideline; repertoire knows about it."""
    pgn = _played_pgn("alex", "opp", "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5")
    result = diff_game(pgn, "alex", white_rep)
    assert result.deviated is False


# ---- Deviation detection -------------------------------------------------

def test_deviation_at_user_move_3(white_rep) -> None:
    """White plays 3. d3 instead of repertoire's Bb5/Bc4."""
    pgn = _played_pgn("alex", "opp", "1. e4 e5 2. Nf3 Nc6 3. d3")
    result = diff_game(pgn, "alex", white_rep)
    assert result.deviated is True
    assert result.deviation_move_number == 3
    assert result.move_played == "d3"
    # Mainline-first ordering: Bb5 is the first expected.
    assert result.move_expected == "Bb5"
    assert result.repertoire_line_name == "Spanish mainline"


def test_deviation_at_user_move_5(white_rep) -> None:
    """White follows mainline through move 4 then deviates."""
    pgn = _played_pgn(
        "alex", "opp",
        "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. d3",
    )
    result = diff_game(pgn, "alex", white_rep)
    assert result.deviated is True
    assert result.deviation_move_number == 5
    assert result.move_played == "d3"
    assert result.move_expected == "O-O"


def test_deviation_at_first_move(white_rep) -> None:
    pgn = _played_pgn("alex", "opp", "1. d4 d5")
    result = diff_game(pgn, "alex", white_rep)
    assert result.deviated is True
    assert result.deviation_move_number == 1
    assert result.move_played == "d4"
    assert result.move_expected == "e4"


def test_deviation_for_black_user(black_rep) -> None:
    """Black plays 1...e5 instead of Caro-Kann's c6."""
    pgn = _played_pgn("opp", "alex", "1. e4 e5")
    result = diff_game(pgn, "alex", black_rep)
    assert result.deviated is True
    # Black's first move is still chess move 1.
    assert result.deviation_move_number == 1
    assert result.move_played == "e5"
    assert result.move_expected == "c6"


def test_black_user_in_book_no_deviation(black_rep) -> None:
    pgn = _played_pgn("opp", "alex", "1. e4 c6 2. d4 d5 3. e5 Bf5")
    result = diff_game(pgn, "alex", black_rep)
    assert result.deviated is False
    assert result.repertoire_line_name == "Caro-Kann advance"


# ---- Opponent novelty (not a user deviation) ----------------------------

def test_opponent_novelty_is_not_user_deviation(white_rep) -> None:
    """After 1.e4, Black plays the Scandinavian (1...d5). White's
    repertoire has no entry for this position, so the user simply
    runs out of book — not a deviation."""
    pgn = _played_pgn("alex", "opp", "1. e4 d5 2. exd5")
    result = diff_game(pgn, "alex", white_rep)
    assert result.deviated is False
    # The line name from the last in-book ply (1.e4 → "Spanish mainline"
    # since the parser indexed e4 first under Spanish).
    assert result.repertoire_line_name == "Spanish mainline"


def test_game_shorter_than_repertoire(white_rep) -> None:
    """User plays 4 in-book moves and the game ends. No deviation."""
    pgn = _played_pgn("alex", "opp", "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6", result="1-0")
    result = diff_game(pgn, "alex", white_rep)
    assert result.deviated is False


# ---- Errors --------------------------------------------------------------

def test_diff_raises_on_username_not_in_headers(white_rep) -> None:
    pgn = _played_pgn("someoneelse", "opp", "1. e4 e5")
    with pytest.raises(DiffError, match="not found"):
        diff_game(pgn, "alex", white_rep)


def test_diff_raises_on_color_mismatch(white_rep) -> None:
    """Played as black, but only the white repertoire is loaded."""
    pgn = _played_pgn("opp", "alex", "1. e4 c6")
    with pytest.raises(DiffError, match="white"):
        diff_game(pgn, "alex", white_rep)


def test_diff_raises_on_garbage_pgn_via_missing_headers(white_rep) -> None:
    """Garbage parses to an empty game with no headers — username
    lookup fails, which is the user-facing error we want."""
    with pytest.raises(DiffError, match="not found"):
        diff_game("garbage not pgn at all", "alex", white_rep)


def test_diff_username_match_is_case_insensitive(white_rep) -> None:
    pgn = _played_pgn("Alex", "Opp", "1. e4 e5 2. Nf3 Nc6 3. d3")
    result = diff_game(pgn, "ALEX", white_rep)
    assert result.deviated is True
    assert result.move_played == "d3"
