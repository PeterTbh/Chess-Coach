"""Phase 2 tests — game fetcher (Lichess + Chess.com) and time-control classifier."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from src.api.game_fetcher import (
    GameFetchError,
    build_metadata_from_pgn,
    fetch_chesscom_pgn,
    fetch_game,
    fetch_lichess_pgn,
    parse_game_url,
)
from src.api.main import app
from src.shared.chess_utils import classify_time_control

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

CANNED_CHESSCOM_PGN = """[Event "Live Chess"]
[Site "Chess.com"]
[Date "2024.06.10"]
[Round "?"]
[White "carol"]
[Black "dave"]
[Result "0-1"]
[TimeControl "180+2"]
[ECO "B01"]
[Termination "dave won by checkmate"]

1. e4 d5 2. exd5 Qxd5 3. Nc3 Qa5 0-1
"""

CANNED_CHESSCOM_DAILY_PGN = """[Event "Daily Chess"]
[Site "Chess.com"]
[White "ed"]
[Black "fran"]
[Result "1-0"]
[TimeControl "1/86400"]

1. d4 d5 1-0
"""


def _mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


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
        "https://lichess.org/abcd1234WXYZ",
        "https://lichess.org/abcd1234WXYZ/white",
    ],
)
def test_parse_lichess_url_variants(url: str) -> None:
    parsed = parse_game_url(url)
    assert parsed.site == "lichess"
    assert parsed.game_id == "abcd1234"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.chess.com/game/live/12345678",
        "https://chess.com/game/live/12345678",
        "chess.com/game/live/12345678",
        "https://www.chess.com/game/live/12345678?username=foo",
        "https://www.chess.com/analysis/game/live/12345678",
        "https://www.chess.com/analysis/game/live/12345678/?tab=analysis",
    ],
)
def test_parse_chesscom_live_url_variants(url: str) -> None:
    parsed = parse_game_url(url)
    assert parsed.site == "chesscom"
    assert parsed.game_id == "12345678"


def test_parse_chesscom_daily_url() -> None:
    parsed = parse_game_url("https://www.chess.com/game/daily/87654321")
    assert parsed.site == "chesscom"
    assert parsed.game_id == "87654321"


def test_parse_garbage_url_raises() -> None:
    with pytest.raises(GameFetchError, match="Unrecognized"):
        parse_game_url("not a url at all")


def test_parse_short_lichess_id_raises() -> None:
    with pytest.raises(GameFetchError):
        parse_game_url("https://lichess.org/abcd123")


# ---- Lichess fetch ---------------------------------------------------------

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


def test_fetch_game_lichess_returns_metadata() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=CANNED_LICHESS_PGN)

    with _mock_client(handler) as client:
        meta = fetch_game("https://lichess.org/abcd1234", client=client)

    assert meta.site == "lichess"
    assert meta.game_id == "abcd1234"
    assert meta.white_username == "alice"
    assert meta.black_username == "bob"
    assert meta.result == "1-0"
    assert meta.time_control == "300+0"
    assert meta.time_class == "blitz"
    assert "1. e4 e5" in meta.pgn
    assert meta.user_color == "white"  # No matching settings → fallback


def test_fetch_game_lichess_user_color_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.shared import settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "lichess_username", "bob")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=CANNED_LICHESS_PGN)

    with _mock_client(handler) as client:
        meta = fetch_game("https://lichess.org/abcd1234", client=client)

    assert meta.user_color == "black"


# ---- Chess.com fetch -------------------------------------------------------

def _chesscom_handler(
    archives: list[str],
    games_per_archive: dict[str, list[dict]],
    *,
    not_found_user: bool = False,
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        path = str(req.url)
        if path.endswith("/games/archives"):
            if not_found_user:
                return httpx.Response(404, json={"message": "user not found"})
            return httpx.Response(200, json={"archives": archives})
        if path in games_per_archive:
            return httpx.Response(200, json={"games": games_per_archive[path]})
        return httpx.Response(404, json={"message": "not found"})
    return handler


def test_fetch_chesscom_pgn_success() -> None:
    archives = [
        "https://api.chess.com/pub/player/mockuser/games/2024/05",
        "https://api.chess.com/pub/player/mockuser/games/2024/06",
    ]
    games = {
        "https://api.chess.com/pub/player/mockuser/games/2024/06": [
            {
                "url": "https://www.chess.com/game/live/12345678",
                "pgn": CANNED_CHESSCOM_PGN,
            },
        ],
        "https://api.chess.com/pub/player/mockuser/games/2024/05": [],
    }
    handler = _chesscom_handler(archives, games)
    with _mock_client(handler) as client:
        pgn = fetch_chesscom_pgn("12345678", username="mockuser", client=client)
    assert "1. e4 d5" in pgn


def test_fetch_chesscom_pgn_walks_back_to_older_month() -> None:
    archives = [
        "https://api.chess.com/pub/player/mockuser/games/2024/05",
        "https://api.chess.com/pub/player/mockuser/games/2024/06",
    ]
    games = {
        "https://api.chess.com/pub/player/mockuser/games/2024/06": [],
        "https://api.chess.com/pub/player/mockuser/games/2024/05": [
            {
                "url": "https://www.chess.com/game/live/12345678",
                "pgn": CANNED_CHESSCOM_PGN,
            },
        ],
    }
    handler = _chesscom_handler(archives, games)
    with _mock_client(handler) as client:
        pgn = fetch_chesscom_pgn("12345678", username="mockuser", client=client)
    assert "carol" in pgn


def test_fetch_chesscom_pgn_user_not_found() -> None:
    handler = _chesscom_handler([], {}, not_found_user=True)
    with _mock_client(handler) as client, pytest.raises(GameFetchError, match="not found"):
        fetch_chesscom_pgn("12345678", username="ghost", client=client)


def test_fetch_chesscom_pgn_game_not_in_archives() -> None:
    archives = ["https://api.chess.com/pub/player/mockuser/games/2024/06"]
    games = {"https://api.chess.com/pub/player/mockuser/games/2024/06": [
        {"url": "https://www.chess.com/game/live/99999999", "pgn": "x"},
    ]}
    handler = _chesscom_handler(archives, games)
    with _mock_client(handler) as client, pytest.raises(GameFetchError, match="not found in"):
        fetch_chesscom_pgn("12345678", username="mockuser", client=client)


def test_fetch_chesscom_pgn_no_username_raises() -> None:
    with pytest.raises(GameFetchError, match="CHESSCOM_USERNAME"):
        fetch_chesscom_pgn("12345678", username="")


def test_fetch_game_chesscom_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.shared import settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "chesscom_username", "mockuser")

    archives = ["https://api.chess.com/pub/player/mockuser/games/2024/06"]
    games = {"https://api.chess.com/pub/player/mockuser/games/2024/06": [
        {"url": "https://www.chess.com/game/live/12345678", "pgn": CANNED_CHESSCOM_PGN},
    ]}
    handler = _chesscom_handler(archives, games)

    with _mock_client(handler) as client:
        meta = fetch_game("https://www.chess.com/game/live/12345678", client=client)

    assert meta.site == "chesscom"
    assert meta.game_id == "12345678"
    assert meta.white_username == "carol"
    assert meta.black_username == "dave"
    assert meta.result == "0-1"
    assert meta.time_control == "180+2"
    assert meta.time_class == "blitz"  # 180 + 40*2 = 260


def test_fetch_game_chesscom_daily_correspondence(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.shared import settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "chesscom_username", "mockuser")

    archives = ["https://api.chess.com/pub/player/mockuser/games/2024/06"]
    games = {"https://api.chess.com/pub/player/mockuser/games/2024/06": [
        {"url": "https://www.chess.com/game/daily/87654321", "pgn": CANNED_CHESSCOM_DAILY_PGN},
    ]}
    handler = _chesscom_handler(archives, games)

    with _mock_client(handler) as client:
        meta = fetch_game("https://www.chess.com/game/daily/87654321", client=client)

    assert meta.time_control == "1/86400"
    assert meta.time_class == "correspondence"


# ---- Time-control classifier ----------------------------------------------

@pytest.mark.parametrize(
    ("tc", "expected"),
    [
        ("15+0", "ultrabullet"),     # 15 < 30
        ("29", "ultrabullet"),       # boundary: 29 < 30
        ("30", "bullet"),            # boundary: 30 not < 30
        ("60+0", "bullet"),          # 60 < 120
        ("60+1", "bullet"),          # 60 + 40 = 100 < 120
        ("120+0", "blitz"),          # 120 not < 120
        ("180+2", "blitz"),          # 180 + 80 = 260
        ("300+0", "blitz"),          # 300 < 480
        ("600+0", "rapid"),          # 600 < 1500
        ("1800+0", "classical"),     # 1800 not < 1500
        ("1/86400", "correspondence"),
        ("1/3600", "classical"),     # daily but < 1 day per move
        ("-", "unknown"),
        ("", "unknown"),
        ("garbage", "unknown"),
        ("?", "unknown"),
    ],
)
def test_classify_time_control(tc: str, expected: str) -> None:
    assert classify_time_control(tc) == expected


# ---- Manual override path --------------------------------------------------

def test_build_metadata_from_pgn_manual() -> None:
    meta = build_metadata_from_pgn(site="manual", game_id="manual", pgn=CANNED_LICHESS_PGN)
    assert meta.site == "manual"
    assert meta.white_username == "alice"
    assert meta.black_username == "bob"
    assert meta.time_control == "300+0"
    assert meta.time_class == "blitz"


def test_build_metadata_garbage_pgn_uses_defaults() -> None:
    meta = build_metadata_from_pgn(site="manual", game_id="x", pgn="not a pgn")
    assert meta.white_username == "?"
    assert meta.black_username == "?"
    assert meta.result == "*"
    assert meta.time_control == ""
    assert meta.time_class == "unknown"


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
    assert body["time_class"] == "blitz"


def test_endpoint_game_fetch_rejects_garbage_url() -> None:
    client = TestClient(app)
    resp = client.post("/game/fetch", json={"url": "garbage"})
    assert resp.status_code == 400
