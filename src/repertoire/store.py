"""SQLite-backed repertoire store (Feature 1.1).

Loads `data/repertoires/{white,black}.pgn` into a normalised SQLite table
the diff logic can query by FEN. One row per move in the repertoire tree
(both colours), with `parent_node_id` linking back to the previous move
so alternatives from a given position can be reconstructed.

Schema:

    repertoires(id, color UNIQUE, source_path, loaded_at)
    repertoire_nodes(
        id, repertoire_id, parent_node_id, ply,
        fen_before_move, fen_after_move,
        san_move, uci_move, move_color, line_name
    )

`fen_before_move` is denormalised (also reachable via parent join) but
keeps the deviation-alternative query a single index lookup.

Transpositions stay as separate rows — the underlying structure is a
variation tree, not a graph. Queries that need to merge them dedupe by
SAN at the call site.
"""

from __future__ import annotations

import io
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import chess
import chess.pgn

logger = logging.getLogger(__name__)


class RepertoireError(Exception):
    """Base for repertoire store errors."""


class RepertoireNotFoundError(RepertoireError):
    """The repertoire file does not exist at the given path."""


class RepertoireParseError(RepertoireError):
    """The file exists but contains no parseable PGN games."""

Color = Literal["white", "black"]

DEFAULT_DB_PATH = Path("data/caissa.sqlite")
DEFAULT_REPERTOIRE_DIR = Path("data/repertoires")
DEFAULT_FILENAMES: dict[str, str] = {
    "white": "white.pgn",
    "black": "black.pgn",
}


def default_repertoire_path(color: Color, base_dir: Path | str = DEFAULT_REPERTOIRE_DIR) -> Path:
    return Path(base_dir) / DEFAULT_FILENAMES[color]


# ---- Data shapes ----------------------------------------------------------

@dataclass(frozen=True)
class LoadStats:
    """Returned by :func:`load_repertoire_into_db` for UI confirmation."""
    color: Color
    positions: int       # total nodes inserted
    variations: int      # number of distinct top-level games (chapters)


@dataclass(frozen=True)
class NodeRow:
    id: int
    repertoire_id: int
    parent_node_id: int | None
    ply: int
    fen_before_move: str
    fen_after_move: str
    san_move: str
    uci_move: str
    move_color: Color
    line_name: str | None


@dataclass(frozen=True)
class ExpectedMove:
    san: str
    uci: str
    line_name: str | None


# ---- Schema ---------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS repertoires (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    color       TEXT    NOT NULL UNIQUE CHECK(color IN ('white','black')),
    source_path TEXT    NOT NULL,
    loaded_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS repertoire_nodes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repertoire_id   INTEGER NOT NULL REFERENCES repertoires(id) ON DELETE CASCADE,
    parent_node_id  INTEGER          REFERENCES repertoire_nodes(id) ON DELETE CASCADE,
    ply             INTEGER NOT NULL,
    fen_before_move TEXT    NOT NULL,
    fen_after_move  TEXT    NOT NULL,
    san_move        TEXT    NOT NULL,
    uci_move        TEXT    NOT NULL,
    move_color      TEXT    NOT NULL CHECK(move_color IN ('white','black')),
    line_name       TEXT
);

CREATE INDEX IF NOT EXISTS idx_nodes_fen_after
    ON repertoire_nodes(repertoire_id, fen_after_move);
CREATE INDEX IF NOT EXISTS idx_nodes_fen_before
    ON repertoire_nodes(repertoire_id, fen_before_move);
CREATE INDEX IF NOT EXISTS idx_nodes_parent
    ON repertoire_nodes(parent_node_id);
"""


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open (or create) the repertoire SQLite DB and ensure schema exists."""
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


# ---- PGN walking ----------------------------------------------------------

def _read_all_games(pgn_text: str) -> list[chess.pgn.Game]:
    games: list[chess.pgn.Game] = []
    stream = io.StringIO(pgn_text)
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break
        if not list(game.mainline_moves()) and not game.variations:
            continue
        games.append(game)
    return games


def _insert_node(
    conn: sqlite3.Connection,
    *,
    repertoire_id: int,
    parent_node_id: int | None,
    ply: int,
    fen_before: str,
    fen_after: str,
    san: str,
    uci: str,
    move_color: Color,
    line_name: str | None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO repertoire_nodes (
            repertoire_id, parent_node_id, ply,
            fen_before_move, fen_after_move,
            san_move, uci_move, move_color, line_name
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            repertoire_id, parent_node_id, ply,
            fen_before, fen_after,
            san, uci, move_color, line_name,
        ),
    )
    return int(cur.lastrowid)


def _index_game(
    conn: sqlite3.Connection,
    *,
    repertoire_id: int,
    game: chess.pgn.Game,
    line_name: str | None,
) -> int:
    """Walk every variation of `game`; insert one row per move. Returns count."""
    inserted = 0

    def _walk(node: chess.pgn.GameNode, board: chess.Board, parent_db_id: int | None) -> None:
        nonlocal inserted
        for child in node.variations:
            move = child.move
            if move is None:
                continue
            fen_before = board.fen()
            try:
                san = board.san(move)
            except (ValueError, AssertionError):
                logger.warning(
                    "Skipping illegal move in repertoire %r: %s at %s",
                    line_name, move.uci(), fen_before,
                )
                continue
            uci = move.uci()
            move_color: Color = "white" if board.turn == chess.WHITE else "black"
            board.push(move)
            fen_after = board.fen()
            ply = board.ply()
            new_id = _insert_node(
                conn,
                repertoire_id=repertoire_id,
                parent_node_id=parent_db_id,
                ply=ply,
                fen_before=fen_before,
                fen_after=fen_after,
                san=san,
                uci=uci,
                move_color=move_color,
                line_name=line_name,
            )
            inserted += 1
            _walk(child, board, new_id)
            board.pop()

    _walk(game, game.board(), None)
    return inserted


# ---- Load ----------------------------------------------------------------

def load_repertoire_into_db(
    conn: sqlite3.Connection,
    pgn_path: Path | str,
    color: Color,
) -> LoadStats:
    """Replace the repertoire for `color` with the contents of `pgn_path`.

    Existing rows for this colour are deleted first (cascade-removes nodes).
    """
    p = Path(pgn_path)
    if not p.is_file():
        raise RepertoireNotFoundError(f"Repertoire file not found: {p}")
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise RepertoireError(f"Could not read {p}: {exc}") from exc

    games = _read_all_games(text)
    if not games:
        raise RepertoireParseError(f"No parseable games in {p}")

    with conn:  # one transaction
        conn.execute("DELETE FROM repertoires WHERE color = ?", (color,))
        cur = conn.execute(
            "INSERT INTO repertoires (color, source_path, loaded_at) VALUES (?, ?, ?)",
            (color, str(p), datetime.now(UTC).isoformat()),
        )
        repertoire_id = int(cur.lastrowid)

        total_nodes = 0
        for game in games:
            line_name = (
                game.headers.get("Event")
                or game.headers.get("White")
                or None
            )
            total_nodes += _index_game(
                conn,
                repertoire_id=repertoire_id,
                game=game,
                line_name=line_name,
            )

    return LoadStats(color=color, positions=total_nodes, variations=len(games))


def ensure_loaded(
    conn: sqlite3.Connection,
    color: Color,
    pgn_path: Path | str | None = None,
) -> LoadStats | None:
    """Lazy-load this colour's repertoire from disk if missing or stale.

    Reloads when:
    - No row exists in ``repertoires`` for ``color``, or
    - The source PGN's mtime is newer than ``loaded_at``.

    Returns:
        :class:`LoadStats` if a (re)load happened, else ``None``.

    Raises:
        RepertoireNotFoundError: PGN file missing and no rows loaded yet.
    """
    p = Path(pgn_path) if pgn_path is not None else default_repertoire_path(color)
    row = conn.execute(
        "SELECT id, loaded_at FROM repertoires WHERE color = ?", (color,)
    ).fetchone()

    if row is None:
        return load_repertoire_into_db(conn, p, color)

    if not p.is_file():
        # Already loaded once; file removed since. Keep existing rows.
        return None

    file_mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=UTC)
    loaded_at = datetime.fromisoformat(row["loaded_at"])
    if file_mtime > loaded_at:
        return load_repertoire_into_db(conn, p, color)
    return None


# ---- Queries used by diff (Feature 1.2) ----------------------------------

def get_repertoire_id(conn: sqlite3.Connection, color: Color) -> int | None:
    row = conn.execute(
        "SELECT id FROM repertoires WHERE color = ?", (color,)
    ).fetchone()
    return int(row["id"]) if row else None


def find_node_by_fen_after(
    conn: sqlite3.Connection,
    color: Color,
    fen_after_move: str,
) -> NodeRow | None:
    """First node in this colour's repertoire that lands on `fen_after_move`."""
    row = conn.execute(
        """
        SELECT n.* FROM repertoire_nodes n
        JOIN repertoires r ON r.id = n.repertoire_id
        WHERE r.color = ? AND n.fen_after_move = ?
        ORDER BY n.id LIMIT 1
        """,
        (color, fen_after_move),
    ).fetchone()
    return _row_to_node(row) if row else None


def find_expected_moves_from(
    conn: sqlite3.Connection,
    color: Color,
    fen_before_move: str,
    move_color: Color,
) -> list[ExpectedMove]:
    """All `move_color` moves the repertoire prepares from `fen_before_move`.

    Mainline-first ordering (insertion order). Deduped by SAN to merge
    transpositions where two PGN branches arrive at the same prior position.
    """
    rows = conn.execute(
        """
        SELECT n.san_move, n.uci_move, n.line_name FROM repertoire_nodes n
        JOIN repertoires r ON r.id = n.repertoire_id
        WHERE r.color = ?
          AND n.fen_before_move = ?
          AND n.move_color = ?
        ORDER BY n.id
        """,
        (color, fen_before_move, move_color),
    ).fetchall()
    seen: set[str] = set()
    out: list[ExpectedMove] = []
    for row in rows:
        san = row["san_move"]
        if san in seen:
            continue
        seen.add(san)
        out.append(ExpectedMove(san=san, uci=row["uci_move"], line_name=row["line_name"]))
    return out


def _row_to_node(row: sqlite3.Row) -> NodeRow:
    return NodeRow(
        id=int(row["id"]),
        repertoire_id=int(row["repertoire_id"]),
        parent_node_id=int(row["parent_node_id"]) if row["parent_node_id"] is not None else None,
        ply=int(row["ply"]),
        fen_before_move=row["fen_before_move"],
        fen_after_move=row["fen_after_move"],
        san_move=row["san_move"],
        uci_move=row["uci_move"],
        move_color=row["move_color"],
        line_name=row["line_name"],
    )
