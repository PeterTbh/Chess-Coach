"""Chess utility helpers: FEN/PGN validation, color extraction, time-control classifier."""

from __future__ import annotations

import io
import logging
from typing import Literal

import chess
import chess.pgn

logger = logging.getLogger(__name__)

STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

# Speed thresholds in "estimated total seconds" = base + 40*increment.
# Boundaries follow the established Lichess/openingtree convention.
_ULTRABULLET_MAX = 30
_BULLET_MAX = 120
_BLITZ_MAX = 480
_RAPID_MAX = 1500
_CORRESPONDENCE_DAY_SECS = 86400

TimeClassName = Literal[
    "ultrabullet",
    "bullet",
    "blitz",
    "rapid",
    "classical",
    "correspondence",
    "unknown",
]


def classify_time_control(time_control: str) -> TimeClassName:
    """Classify a PGN `TimeControl` header into a speed bucket.

    Recognized formats:
    - `"base+inc"` (Lichess + Chess.com live), e.g. ``"300+0"``, ``"180+2"``.
    - `"base"` (no increment).
    - `"1/N"` (Chess.com daily; N seconds per move). N≥86400 → correspondence,
      otherwise classical.
    - ``"-"``, ``""``, ``"?"`` → ``"unknown"``.
    """
    tc = time_control.strip()
    if tc in {"", "-", "?"}:
        return "unknown"

    if "/" in tc:
        try:
            _, secs_str = tc.split("/", 1)
            secs = int(secs_str)
        except ValueError:
            return "unknown"
        return "correspondence" if secs >= _CORRESPONDENCE_DAY_SECS else "classical"

    try:
        if "+" in tc:
            base_s, inc_s = tc.split("+", 1)
            base, inc = int(base_s), int(inc_s)
        else:
            base, inc = int(tc), 0
    except ValueError:
        return "unknown"

    total = base + 40 * inc
    if total < _ULTRABULLET_MAX:
        return "ultrabullet"
    if total < _BULLET_MAX:
        return "bullet"
    if total < _BLITZ_MAX:
        return "blitz"
    if total < _RAPID_MAX:
        return "rapid"
    return "classical"


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
