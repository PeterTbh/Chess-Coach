"""Single-game PGN fetcher.

Phase 2 slice 1: Lichess only. Chess.com lands in slice 2.

Lichess single-game endpoint:
    GET https://lichess.org/game/export/{gameId}
    Accept: application/x-chess-pgn
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

import httpx

from src.shared.chess_utils import extract_user_color, parse_pgn
from src.shared.schemas import GameMetadata
from src.shared.settings import settings

logger = logging.getLogger(__name__)

# Lichess game IDs are 8 base62 chars; the export endpoint accepts that
# 8-char form directly. Some URLs append 4 more chars (the "fully qualified"
# 12-char internal id) plus optional `/white`|`/black` perspective suffix
# and optional fragment/query.
LICHESS_GAME_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?lichess\.org/"
    r"(?P<id>[A-Za-z0-9]{8})"
    r"(?:[A-Za-z0-9]{4})?"
    r"(?:/(?:white|black))?"
    r"(?:[/#?].*)?$"
)
LICHESS_EXPORT_URL = "https://lichess.org/game/export/{game_id}"
HTTP_TIMEOUT_SECONDS = 10.0
USER_AGENT = "Caissa/0.1 (personal chess post-mortem)"

Site = Literal["lichess", "chesscom", "manual"]


class GameFetchError(Exception):
    """Raised when a game URL cannot be parsed or its PGN cannot be fetched."""


@dataclass(frozen=True)
class ParsedGameURL:
    site: Literal["lichess", "chesscom"]
    game_id: str


def parse_game_url(url: str) -> ParsedGameURL:
    """Extract `(site, game_id)` from a Lichess or Chess.com game URL.

    Raises `GameFetchError` on unrecognized formats.
    """
    cleaned = url.strip()
    match = LICHESS_GAME_RE.match(cleaned)
    if match is not None:
        return ParsedGameURL(site="lichess", game_id=match.group("id"))
    if "chess.com" in cleaned.lower():
        raise GameFetchError(
            "Chess.com fetcher not implemented yet (Phase 2 slice 2)."
        )
    raise GameFetchError(f"Unrecognized game URL: {cleaned!r}")


def fetch_lichess_pgn(game_id: str, *, client: httpx.Client | None = None) -> str:
    """Download a single Lichess game's PGN.

    Pass `client` to inject an `httpx.Client` (used in tests with `MockTransport`).
    """
    url = LICHESS_EXPORT_URL.format(game_id=game_id)
    headers = {
        "Accept": "application/x-chess-pgn",
        "User-Agent": USER_AGENT,
    }

    def _do_get(http: httpx.Client) -> str:
        resp = http.get(url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
        if resp.status_code == 404:
            raise GameFetchError(f"Lichess game {game_id} not found.")
        if resp.status_code != 200:
            raise GameFetchError(
                f"Lichess fetch failed: HTTP {resp.status_code}"
            )
        text = resp.text.strip()
        if not text:
            raise GameFetchError("Lichess returned empty PGN.")
        return text

    if client is not None:
        return _do_get(client)
    with httpx.Client() as http:
        return _do_get(http)


def build_metadata_from_pgn(*, site: Site, game_id: str, pgn: str) -> GameMetadata:
    """Parse a PGN into a `GameMetadata`. Raises `GameFetchError` on bad PGN."""
    game = parse_pgn(pgn)
    if game is None:
        raise GameFetchError("Could not parse PGN.")
    headers = game.headers
    white = headers.get("White", "?") or "?"
    black = headers.get("Black", "?") or "?"
    result = headers.get("Result", "*") or "*"

    user_handle = (
        settings.lichess_username if site == "lichess"
        else settings.chesscom_username if site == "chesscom"
        else ""
    )
    user_color = extract_user_color(pgn, user_handle) if user_handle else None
    if user_color is None:
        # We can't infer — pick White as a non-destructive default.
        # Streamlit can let the user override; Phase 3 may refine.
        logger.info(
            "user_color undetermined for site=%s game=%s; defaulting to white",
            site, game_id,
        )
        user_color = "white"

    return GameMetadata(
        site=site,
        game_id=game_id,
        white_username=white,
        black_username=black,
        user_color=user_color,
        result=result,
        pgn=pgn,
    )


def fetch_game(url: str, *, client: httpx.Client | None = None) -> GameMetadata:
    """End-to-end: URL → PGN → `GameMetadata`."""
    parsed = parse_game_url(url)
    if parsed.site == "lichess":
        pgn = fetch_lichess_pgn(parsed.game_id, client=client)
        return build_metadata_from_pgn(site="lichess", game_id=parsed.game_id, pgn=pgn)
    # parse_game_url already filters chesscom with a clearer message;
    # this is defensive in case the parser grows.
    raise GameFetchError(f"Unsupported site: {parsed.site}")
