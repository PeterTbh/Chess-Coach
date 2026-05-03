"""Repertoire PGN parser (Module B foundation).

Phase 2 deliverable: load `data/repertoires/{white,black}.pgn` (or any
PGN path) into a position-keyed index that the Phase 3 diff logic can
walk.

A repertoire file may contain:
- A single game with a mainline plus PGN sub-tree variations `(...)`.
- Multiple concatenated games (each treated as a separate "chapter").
- PGN headers identifying the line (e.g. `[Event "Catalan mainline"]`).

Convention assumed:
- The file at `white.pgn` is the user's repertoire when playing White.
- The file at `black.pgn` is the user's repertoire when playing Black.

The diff use case at Phase 3 needs: "given the position after ply N,
which moves does the repertoire prepare for ply N+1?" — so we index by
the FEN of the parent position. Transpositions (two distinct lines
arriving at the same FEN) merge their expected-move lists, deduplicated
by SAN.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import chess
import chess.pgn

logger = logging.getLogger(__name__)

Color = Literal["white", "black"]


# ---- Errors ---------------------------------------------------------------

class RepertoireError(Exception):
    """Base for repertoire parser errors."""


class RepertoireNotFoundError(RepertoireError):
    """The repertoire file does not exist at the given path."""


class RepertoireParseError(RepertoireError):
    """The file exists but contains no parseable PGN games."""


# ---- Data shapes ----------------------------------------------------------

@dataclass(frozen=True)
class ExpectedMove:
    """A move the repertoire prepares for, from a specific position."""
    san: str
    uci: str
    line_name: str | None = None  # PGN [Event] header, or chapter title


@dataclass
class Repertoire:
    """An indexed repertoire ready for position-keyed lookup.

    `position_index` maps a FEN (the position **before** the move) to the
    list of moves the repertoire knows from that position. The list
    preserves insertion order (mainline first, then sidelines).
    """
    color: Color
    games: list[chess.pgn.Game] = field(default_factory=list)
    position_index: dict[str, list[ExpectedMove]] = field(default_factory=dict)

    def expected_at(self, fen: str) -> list[ExpectedMove]:
        """Return prep'd moves at `fen`, or `[]` if the position isn't covered."""
        return self.position_index.get(fen, [])

    def covers(self, fen: str) -> bool:
        return fen in self.position_index


# ---- Parsing --------------------------------------------------------------

def _read_all_games(pgn_text: str) -> list[chess.pgn.Game]:
    """Parse every concatenated game block from a PGN string.

    Skips empty header-only blocks. Returns `[]` if nothing parses.
    """
    games: list[chess.pgn.Game] = []
    stream = io.StringIO(pgn_text)
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break
        # Header-only block with no moves: ignore.
        if not list(game.mainline_moves()) and not game.variations:
            continue
        games.append(game)
    return games


def _index_game(
    game: chess.pgn.Game,
    *,
    line_name: str | None,
    index: dict[str, list[ExpectedMove]],
) -> None:
    """Walk every variation of `game` and add `(parent_fen → move)` entries."""

    def _walk(node: chess.pgn.GameNode, board: chess.Board) -> None:
        for child in node.variations:
            move = child.move
            if move is None:
                continue
            parent_fen = board.fen()
            try:
                san = board.san(move)
            except (ValueError, AssertionError):
                logger.warning(
                    "Skipping illegal move in repertoire %r: %s at %s",
                    line_name, move.uci(), parent_fen,
                )
                continue
            uci = move.uci()
            existing = index.setdefault(parent_fen, [])
            if not any(m.san == san for m in existing):
                existing.append(
                    ExpectedMove(san=san, uci=uci, line_name=line_name)
                )
            board.push(move)
            _walk(child, board)
            board.pop()

    _walk(game, game.board())


def load_repertoire(path: Path | str, color: Color) -> Repertoire:
    """Load and index a repertoire PGN file.

    Args:
        path: Filesystem path to the PGN file.
        color: Which side this repertoire covers (`"white"` or `"black"`).

    Raises:
        RepertoireNotFoundError: file does not exist.
        RepertoireParseError: file exists but contains no parseable PGN.
        RepertoireError: file cannot be read (I/O error).
    """
    p = Path(path)
    if not p.is_file():
        raise RepertoireNotFoundError(f"Repertoire file not found: {p}")
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise RepertoireError(f"Could not read {p}: {exc}") from exc

    games = _read_all_games(text)
    if not games:
        raise RepertoireParseError(f"No parseable games in {p}")

    repertoire = Repertoire(color=color, games=games)
    for game in games:
        line_name = (
            game.headers.get("Event")
            or game.headers.get("White")
            or None
        )
        _index_game(game, line_name=line_name, index=repertoire.position_index)
    return repertoire


# ---- Default-path convenience --------------------------------------------

DEFAULT_REPERTOIRE_DIR = Path("data/repertoires")
DEFAULT_FILENAMES: dict[Color, str] = {
    "white": "white.pgn",
    "black": "black.pgn",
}


def load_default_repertoire(
    color: Color,
    *,
    base_dir: Path | str = DEFAULT_REPERTOIRE_DIR,
) -> Repertoire:
    """Load the user's repertoire from the project's default location."""
    return load_repertoire(Path(base_dir) / DEFAULT_FILENAMES[color], color)
