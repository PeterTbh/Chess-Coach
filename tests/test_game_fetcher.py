"""Phase 2 slice 1 tests — Lichess game fetcher."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from src.api.game_fetcher import (
    GameFetchError,
    build_metadata_from_pgn,
    fetch_game,
    fetch_lichess_pgn,
    parse_game_url,
)
from src.api.main import app

CANNED_LICHESS_PGN = """[Event "Rated Blitz game"]
[Site "https://lichess.org/abcd1234"]
[Date "2024.01.15"]
[Round "?"]
[White "alice"]
[Black "bob"]
[Result "1-0"]
[UTCDate "2024.01.15"]
[UTCTime "12:34:56"]
[WhiteElo "1500"]
[BlackElo "1480"]
[Variant "Standard"]
[TimeControl "300+0"]
[ECO "C20"]
[Termination "Normal"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5 7. Bb3 d6 1-0
"""


# ---- URL parsing -----------------------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "https://lichess.org/abcd1234",
        "http://lichess.org/abcd1234",
        "https://www.lichess.org/abcd1234",
        "lichess.org/abcd1234",
        "https://lichess.org/abcd1234/white",
        "https://lichess.org/abcd1234/black",
        "https://lichess.org/abcd1234#42",
        "https://lichess.org/abcd1234?key=val",
        "https://lichess.org/abcd1234WXYZ",  # 12-char fully-qualified id
        "https://lichess.org/abcd1234WXYZ/white",
    ],
)
def test_parse_lichess_url_variants(url: str) -> None:
    parsed = parse_game_url(url)
    assert parsed.site == "lichess"
    assert parsed.game_id == "abcd1234"


def test_parse_chesscom_url_raises_not_implemented() -> None:
    with pytest.raises(GameFetchError, match="not implemented"):
        parse_game_url("https://www.chess.com/game/live/123456789")


def test_parse_garbage_url_raises() -> None:
    with pytest.raises(GameFetchError, match="Unrecognized"):
        parse_game_url("not a url at all")


def test_parse_short_id_raises() -> None:
    # Lichess ids are exactly 8 chars; 7 must reject.
    with pytest.raises(GameFetchError):
        parse_game_url("https://lichess.org/abcd123")


# ---- Lichess fetch with mocked transport ----------------------------------

def _mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_lichess_pgn_success() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["req"] = req
        return httpx.Response(200, text=CANNED_LICHESS_PGN)

    with _mock_client(handler) as client:
        pgn = fetch_lichess_pgn("abcd1234", client=client)

    assert "1. e4 e5" in pgn
    sent = captured["req"]
    assert sent.url.path == "/game/export/abcd1234"
    assert sent.headers.get("Accept") == "application/x-chess-pgn"
    assert "Caissa" in (sent.headers.get("User-Agent") or "")


def test_fetch_lichess_pgn_404_raises() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    with _mock_client(handler) as client, pytest.raises(GameFetchError, match="not found"):
        fetch_lichess_pgn("abcd1234", client=client)


def test_fetch_lichess_pgn_500_raises() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    with _mock_client(handler) as client, pytest.raises(GameFetchError, match="HTTP 500"):
        fetch_lichess_pgn("abcd1234", client=client)


def test_fetch_lichess_pgn_empty_raises() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="   ")

    with _mock_client(handler) as client, pytest.raises(GameFetchError, match="empty"):
        fetch_lichess_pgn("abcd1234", client=client)


# ---- End-to-end fetch_game -------------------------------------------------

def test_fetch_game_returns_metadata() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=CANNED_LICHESS_PGN)

    with _mock_client(handler) as client:
        meta = fetch_game("https://lichess.org/abcd1234", client=client)

    assert meta.site == "lichess"
    assert meta.game_id == "abcd1234"
    assert meta.white_username == "alice"
    assert meta.black_username == "bob"
    assert meta.result == "1-0"
    assert "1. e4 e5" in meta.pgn
    # No matching username in settings → falls back to white.
    assert meta.user_color == "white"


def test_fetch_game_user_color_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.shared import settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "lichess_username", "bob")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=CANNED_LICHESS_PGN)

    with _mock_client(handler) as client:
        meta = fetch_game("https://lichess.org/abcd1234", client=client)

    assert meta.user_color == "black"


# ---- Manual override path --------------------------------------------------

def test_build_metadata_from_pgn_manual() -> None:
    meta = build_metadata_from_pgn(site="manual", game_id="manual", pgn=CANNED_LICHESS_PGN)
    assert meta.site == "manual"
    assert meta.white_username == "alice"
    assert meta.black_username == "bob"


def test_build_metadata_garbage_pgn_uses_defaults() -> None:
    # python-chess parses anything as an empty Game with default headers.
    # Strict rejection is Phase 9 (edge-case hardening); for now assert the
    # graceful-default contract.
    meta = build_metadata_from_pgn(site="manual", game_id="x", pgn="not a pgn")
    assert meta.white_username == "?"
    assert meta.black_username == "?"
    assert meta.result == "*"


# ---- /game/fetch HTTP endpoint --------------------------------------------

def test_endpoint_game_fetch_with_override() -> None:
    client = TestClient(app)
    resp = client.post(
        "/game/fetch",
        json={"url": "ignored", "pgn_override": CANNED_LICHESS_PGN},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["site"] == "manual"
    assert body["white_username"] == "alice"
    assert body["black_username"] == "bob"


def test_endpoint_game_fetch_rejects_chesscom() -> None:
    client = TestClient(app)
    resp = client.post("/game/fetch", json={"url": "https://chess.com/game/123"})
    assert resp.status_code == 400
    assert "not implemented" in resp.json()["detail"]


def test_endpoint_game_fetch_rejects_garbage_url() -> None:
    client = TestClient(app)
    resp = client.post("/game/fetch", json={"url": "garbage"})
    assert resp.status_code == 400
