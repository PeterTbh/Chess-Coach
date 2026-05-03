"""Tests for the Lichess Cloud Eval client (Phase 3 Slice 2)."""

from __future__ import annotations

import httpx
import pytest

from src.engine.lichess_eval import (
    InvalidFenError,
    LichessEvalError,
    PositionNotInCloudError,
    fetch_cloud_eval,
)
from src.shared.chess_utils import STARTING_FEN

# ---- Helpers --------------------------------------------------------------


def _client_with(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


# ---- Happy path -----------------------------------------------------------

def test_fetch_cloud_eval_parses_cp_response() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params["fen"] == STARTING_FEN
        return httpx.Response(
            200,
            json={
                "fen": STARTING_FEN,
                "knodes": 695524,
                "depth": 75,
                "pvs": [{"moves": "e2e4 e7e5 g1f3 b8c6", "cp": 19}],
            },
        )

    transport = httpx.MockTransport(handler)
    with _client_with(transport) as c:
        result = fetch_cloud_eval(STARTING_FEN, client=c)

    assert result.fen == STARTING_FEN
    assert result.cp == 19
    assert result.mate is None
    assert result.best_move_uci == "e2e4"
    assert result.pv == ["e2e4", "e7e5", "g1f3", "b8c6"]
    assert result.source == "lichess_cloud"


def test_fetch_cloud_eval_parses_mate_response() -> None:
    fen = "6k1/5ppp/8/8/8/8/5PPP/4Q2K w - - 0 1"

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "fen": fen,
                "knodes": 100,
                "depth": 30,
                "pvs": [{"moves": "e1e8", "mate": 1}],
            },
        )

    with _client_with(httpx.MockTransport(handler)) as c:
        result = fetch_cloud_eval(fen, client=c)
    assert result.cp is None
    assert result.mate == 1
    assert result.best_move_uci == "e1e8"


def test_fetch_cloud_eval_uses_multipv_param() -> None:
    captured: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["multiPv"] = req.url.params["multiPv"]
        return httpx.Response(
            200,
            json={"fen": STARTING_FEN, "pvs": [{"moves": "e2e4", "cp": 0}]},
        )

    with _client_with(httpx.MockTransport(handler)) as c:
        fetch_cloud_eval(STARTING_FEN, multi_pv=3, client=c)
    assert captured["multiPv"] == "3"


# ---- Error cases ----------------------------------------------------------

def test_invalid_fen_raises_locally_without_http_call() -> None:
    called = False

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    with _client_with(httpx.MockTransport(handler)) as c, pytest.raises(InvalidFenError):
        fetch_cloud_eval("not a fen", client=c)
    assert called is False


def test_404_maps_to_position_not_in_cloud() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "Not found"})

    with _client_with(httpx.MockTransport(handler)) as c, pytest.raises(
        PositionNotInCloudError
    ):
        fetch_cloud_eval(STARTING_FEN, client=c)


def test_500_maps_to_generic_error() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    with _client_with(httpx.MockTransport(handler)) as c, pytest.raises(
        LichessEvalError, match="500"
    ):
        fetch_cloud_eval(STARTING_FEN, client=c)


def test_network_error_maps_to_generic_error() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("DNS failure")

    with _client_with(httpx.MockTransport(handler)) as c, pytest.raises(
        LichessEvalError, match="Network"
    ):
        fetch_cloud_eval(STARTING_FEN, client=c)


def test_malformed_body_no_pvs() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"fen": STARTING_FEN, "depth": 10})

    with _client_with(httpx.MockTransport(handler)) as c, pytest.raises(
        LichessEvalError, match="pvs"
    ):
        fetch_cloud_eval(STARTING_FEN, client=c)


def test_malformed_body_pv_missing_cp_and_mate() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"fen": STARTING_FEN, "pvs": [{"moves": "e2e4"}]}
        )

    with _client_with(httpx.MockTransport(handler)) as c, pytest.raises(
        LichessEvalError, match="cp"
    ):
        fetch_cloud_eval(STARTING_FEN, client=c)


def test_malformed_json_body() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    with _client_with(httpx.MockTransport(handler)) as c, pytest.raises(
        LichessEvalError, match="JSON"
    ):
        fetch_cloud_eval(STARTING_FEN, client=c)
