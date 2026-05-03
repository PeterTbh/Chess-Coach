"""Helpers for walking a fetched game's PGN ply-by-ply for the UI.

The Streamlit panels need:
- The FEN at every ply (for /eval lookups + board rendering).
- The SAN of each move (for the move list display).
- The UCI of the last move (so the SVG renderer can highlight it).
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

from src.shared.chess_utils import STARTING_FEN, parse_pgn


@dataclass(frozen=True)
class PlyView:
    """One position in the played game.

    ``ply == 0`` is the starting position (no last move). Subsequent
    plies are numbered 1..N in playing order.
    """

    ply: int
    fen: str
    san: str | None  # None for ply 0
    move_uci: str | None  # None for ply 0
    fullmove_number: int  # chess move number (1-indexed)
    side_to_move: str  # "white" or "black" — whose turn AT this ply


def walk_pgn(pgn_text: str) -> list[PlyView]:
    """Return a list of :class:`PlyView` from start through end of game.

    Returns an empty list if the PGN cannot be parsed.
    """
    game = parse_pgn(pgn_text)
    if game is None:
        return []

    board = game.board()
    views: list[PlyView] = [
        PlyView(
            ply=0,
            fen=board.fen(),
            san=None,
            move_uci=None,
            fullmove_number=board.fullmove_number,
            side_to_move="white" if board.turn == chess.WHITE else "black",
        )
    ]

    for i, move in enumerate(game.mainline_moves(), start=1):
        san = board.san(move)
        uci = move.uci()
        board.push(move)
        views.append(
            PlyView(
                ply=i,
                fen=board.fen(),
                san=san,
                move_uci=uci,
                fullmove_number=board.fullmove_number,
                side_to_move="white" if board.turn == chess.WHITE else "black",
            )
        )

    return views


def starting_view() -> PlyView:
    """A :class:`PlyView` for the standard starting position (no game)."""
    return PlyView(
        ply=0,
        fen=STARTING_FEN,
        san=None,
        move_uci=None,
        fullmove_number=1,
        side_to_move="white",
    )
