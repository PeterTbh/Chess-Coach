"""Local Stockfish wrapper via python-chess UCI subprocess.

Used as fallback when Lichess Cloud Eval doesn't know a position
(common for Chess.com games). The Stockfish binary is installed in the
API Docker image; locally, it must be on ``PATH`` (or pointed at via
``STOCKFISH_PATH``).

For Phase 3 we run a short time-bounded analysis (default 0.5s,
single PV) — good enough to surface "you blundered here" without
making /eval slow.
"""

from __future__ import annotations

import logging

import chess
import chess.engine

from src.shared.chess_utils import validate_fen
from src.shared.schemas import EvalResponse
from src.shared.settings import settings

logger = logging.getLogger(__name__)

DEFAULT_TIME_SECONDS = 0.5
SOURCE_NAME = "local_stockfish"


def _default_binary() -> str:
    """Resolved at call time so tests / .env edits take effect immediately."""
    return settings.stockfish_path


class StockfishError(Exception):
    """Base for local Stockfish wrapper errors."""


class StockfishUnavailableError(StockfishError):
    """The Stockfish binary could not be launched (missing/permission)."""


class StockfishAnalysisError(StockfishError):
    """The engine returned a result we can't normalize."""


class InvalidFenError(StockfishError):
    """FEN failed local validation before sending."""


def analyse_position(
    fen: str,
    *,
    time_seconds: float = DEFAULT_TIME_SECONDS,
    binary: str | None = None,
) -> EvalResponse:
    """Run local Stockfish and return a normalized :class:`EvalResponse`.

    Score is reported from White's POV (positive = good for White),
    matching Lichess Cloud Eval's convention.

    Raises:
        InvalidFenError: ``fen`` is not a legal position.
        StockfishUnavailableError: binary cannot be launched.
        StockfishAnalysisError: result missing required fields.
    """
    if not validate_fen(fen):
        raise InvalidFenError(f"Invalid FEN: {fen!r}")

    resolved_binary = binary if binary is not None else _default_binary()
    try:
        engine = chess.engine.SimpleEngine.popen_uci(resolved_binary)
    except FileNotFoundError as exc:
        raise StockfishUnavailableError(
            f"Stockfish binary not found at {resolved_binary!r}"
        ) from exc
    except chess.engine.EngineError as exc:
        raise StockfishUnavailableError(f"Could not launch Stockfish: {exc}") from exc

    try:
        board = chess.Board(fen)
        info = engine.analyse(board, chess.engine.Limit(time=time_seconds))
    except chess.engine.EngineError as exc:
        raise StockfishAnalysisError(f"Stockfish analysis failed: {exc}") from exc
    finally:
        engine.quit()

    return _info_to_eval_response(fen, info)


def _info_to_eval_response(
    fen: str, info: chess.engine.InfoDict
) -> EvalResponse:
    score = info.get("score")
    if score is None:
        raise StockfishAnalysisError(f"Stockfish returned no score: {info!r}")

    white_pov = score.white()
    cp = white_pov.score(mate_score=None)
    mate = white_pov.mate()

    pv_moves = info.get("pv") or []
    pv_uci = [m.uci() for m in pv_moves]
    best_move = pv_uci[0] if pv_uci else None

    return EvalResponse(
        fen=fen,
        cp=cp,
        mate=mate,
        best_move_uci=best_move,
        pv=pv_uci,
        source=SOURCE_NAME,
    )
