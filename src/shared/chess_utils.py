"""Chess utility helpers: FEN/PGN validation, color extraction."""

from __future__ import annotations

import io
import logging
from typing import Literal

import chess
import chess.pgn

logger = logging.getLogger(__name__)

STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def validate_fen(fen: str) -> bool:
    """Return True if FEN parses to a legal chess position."""
    try:
        board = chess.Board(fen)
        return board.is_valid()
    except (ValueError, IndexError):
        return False


def parse_pgn(pgn_text: str) -> chess.pgn.Game | None:
    """Parse a PGN string into a Game. Returns None on failure."""
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
        return game
    except Exception as exc:  # python-chess raises various
        logger.warning("PGN parse failed: %s", exc)
        return None


def extract_user_color(
    pgn_text: str, username: str
) -> Literal["white", "black"] | None:
    """Read PGN headers and return which color `username` played.

    Case-insensitive match. Returns None if the user is not in either header.
    """
    game = parse_pgn(pgn_text)
    if game is None:
        return None
    white = game.headers.get("White", "").strip().lower()
    black = game.headers.get("Black", "").strip().lower()
    target = username.strip().lower()
    if target == white:
        return "white"
    if target == black:
        return "black"
    return None
