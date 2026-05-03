"""Tests for src.ui.components.game_walker."""

from __future__ import annotations

from src.shared.chess_utils import STARTING_FEN
from src.ui.components.game_walker import walk_pgn

PGN = """
[Event "Test"]
[White "a"]
[Black "b"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 *
""".strip()


def test_walk_pgn_returns_starting_view_at_ply_0() -> None:
    views = walk_pgn(PGN)
    assert views[0].ply == 0
    assert views[0].fen == STARTING_FEN
    assert views[0].san is None
    assert views[0].move_uci is None
    assert views[0].side_to_move == "white"


def test_walk_pgn_records_each_ply() -> None:
    views = walk_pgn(PGN)
    assert len(views) == 5  # start + 4 plies
    assert [v.san for v in views[1:]] == ["e4", "e5", "Nf3", "Nc6"]
    assert [v.move_uci for v in views[1:]] == ["e2e4", "e7e5", "g1f3", "b8c6"]


def test_walk_pgn_side_to_move_alternates() -> None:
    views = walk_pgn(PGN)
    assert [v.side_to_move for v in views] == [
        "white",  # before any move
        "black",  # after 1.e4
        "white",  # after 1...e5
        "black",  # after 2.Nf3
        "white",  # after 2...Nc6
    ]


def test_walk_pgn_returns_empty_on_unparseable() -> None:
    assert walk_pgn("definitely not pgn") == [] or walk_pgn(
        "definitely not pgn"
    )[0].ply == 0
    # Either python-chess returns None (→ []) or an empty Game (→ just start view).


def test_walk_pgn_fullmove_number() -> None:
    views = walk_pgn(PGN)
    # Before move 1: fullmove=1. After 1.e4 (black to move): still 1.
    # After 1...e5 (white to move): 2. After 2.Nf3: 2. After 2...Nc6: 3.
    assert [v.fullmove_number for v in views] == [1, 1, 2, 2, 3]
