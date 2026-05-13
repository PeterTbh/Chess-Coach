"""Tests for the local Stockfish wrapper (Phase 3 Slice 3).

Pure unit tests use ``monkeypatch`` to swap in a fake engine. An
optional integration test runs only when the real ``stockfish`` binary
is on ``PATH``.
"""

from __future__ import annotations

import os
import shutil
from typing import Any

import chess
import chess.engine
import pytest

from src.engine import stockfish as sf
from src.shared.chess_utils import STARTING_FEN
from src.shared.settings import settings


def _resolve_stockfish_binary() -> str | None:
    """Return a runnable Stockfish path: explicit setting, $STOCKFISH_PATH, or PATH."""
    candidate = settings.stockfish_path or os.environ.get("STOCKFISH_PATH") or "stockfish"
    if os.path.isabs(candidate) and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    return shutil.which(candidate)

# ---- Fakes ----------------------------------------------------------------


class _FakeEngine:
    """Minimal stand-in for ``chess.engine.SimpleEngine``."""

    def __init__(self, info: dict) -> None:
        self._info = info
        self.quit_called = False

    def analyse(self, board: chess.Board, limit: Any) -> dict:
        return self._info

    def quit(self) -> None:
        self.quit_called = True


def _patch_popen(monkeypatch: pytest.MonkeyPatch, info: dict) -> _FakeEngine:
    fake = _FakeEngine(info)

    def _fake_popen(_binary: str) -> _FakeEngine:
        return fake

    monkeypatch.setattr(
        chess.engine.SimpleEngine, "popen_uci", staticmethod(_fake_popen)
    )
    return fake


def _patch_popen_raising(
    monkeypatch: pytest.MonkeyPatch, exc: BaseException
) -> None:
    def _fake_popen(_binary: str) -> _FakeEngine:
        raise exc

    monkeypatch.setattr(
        chess.engine.SimpleEngine, "popen_uci", staticmethod(_fake_popen)
    )


# ---- Score parsing --------------------------------------------------------

def test_analyse_position_returns_cp_score(monkeypatch: pytest.MonkeyPatch) -> None:
    info = {
        "score": chess.engine.PovScore(chess.engine.Cp(34), chess.WHITE),
        "pv": [chess.Move.from_uci("e2e4"), chess.Move.from_uci("e7e5")],
    }
    fake = _patch_popen(monkeypatch, info)

    result = sf.analyse_position(STARTING_FEN)

    assert result.cp == 34
    assert result.mate is None
    assert result.best_move_uci == "e2e4"
    assert result.pv == ["e2e4", "e7e5"]
    assert result.source == "local_stockfish"
    assert fake.quit_called is True


def test_analyse_position_returns_mate_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = {
        "score": chess.engine.PovScore(chess.engine.Mate(3), chess.WHITE),
        "pv": [chess.Move.from_uci("d1h5")],
    }
    _patch_popen(monkeypatch, info)

    result = sf.analyse_position(STARTING_FEN)
    assert result.mate == 3
    assert result.cp is None


def test_analyse_position_returns_negative_cp_when_black_winning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """White-POV convention: negative cp = better for Black."""
    # Black-to-move POV score saying "+200 for whoever is to move".
    # Black is to move and Black is +200 → from White's POV that's -200.
    info = {
        "score": chess.engine.PovScore(chess.engine.Cp(200), chess.BLACK),
        "pv": [],
    }
    _patch_popen(monkeypatch, info)
    result = sf.analyse_position(STARTING_FEN)
    assert result.cp == -200


def test_analyse_position_with_no_pv_yields_no_best_move(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = {"score": chess.engine.PovScore(chess.engine.Cp(0), chess.WHITE)}
    _patch_popen(monkeypatch, info)
    result = sf.analyse_position(STARTING_FEN)
    assert result.best_move_uci is None
    assert result.pv == []


# ---- Errors ---------------------------------------------------------------

def test_invalid_fen_raises_locally(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def _spy_popen(_binary: str) -> _FakeEngine:
        nonlocal called
        called = True
        return _FakeEngine({})

    monkeypatch.setattr(
        chess.engine.SimpleEngine, "popen_uci", staticmethod(_spy_popen)
    )
    with pytest.raises(sf.InvalidFenError):
        sf.analyse_position("garbage")
    assert called is False


def test_missing_binary_maps_to_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_popen_raising(monkeypatch, FileNotFoundError("no such file"))
    with pytest.raises(sf.StockfishUnavailableError, match="not found"):
        sf.analyse_position(STARTING_FEN)


def test_engine_error_on_popen_maps_to_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_popen_raising(monkeypatch, chess.engine.EngineError("crash"))
    with pytest.raises(sf.StockfishUnavailableError, match="launch"):
        sf.analyse_position(STARTING_FEN)


def test_no_score_in_info_raises_analysis_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_popen(monkeypatch, {"pv": []})
    with pytest.raises(sf.StockfishAnalysisError, match="no score"):
        sf.analyse_position(STARTING_FEN)


# ---- Optional integration test (only if binary present) ------------------

@pytest.mark.skipif(
    _resolve_stockfish_binary() is None,
    reason="stockfish binary not resolvable (not on PATH and STOCKFISH_PATH unset/invalid)",
)
def test_real_stockfish_runs_on_starting_position() -> None:
    """Sanity check: real Stockfish completes a 0.1s analysis."""
    result = sf.analyse_position(STARTING_FEN, time_seconds=0.1)
    assert result.source == "local_stockfish"
    # Starting position should be near 0 cp (white slight edge in practice).
    assert result.cp is not None
    assert -100 < result.cp < 100
    assert result.best_move_uci is not None
