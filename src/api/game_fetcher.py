"""Single-game PGN fetcher.

Phase 2 slices 1+2: Lichess and Chess.com.

Lichess single-game endpoint:
    GET https://lichess.org/game/export/{gameId}
    Accept: application/x-chess-pgn

Chess.com strategy:
    The Public Data API has no single-game endpoint, so we walk the user's
    monthly archives (newest first) and match by URL suffix. Requires
    ``CHESSCOM_USERNAME`` in `.env`.
        GET https://api.chess.com/pub/player/{user}/games/archives
        GET {monthly_url}  → JSON { games: [{ url, pgn, ... }] }
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

import httpx

from src.shared.chess_utils import classify_time_control, extract_user_color, parse_pgn
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

# Chess.com URL forms: /game/live/{id}, /game/daily/{id}, /analysis/game/live/{id}.
# Game id is a numeric uuid in the URL.
CHESSCOM_GAME_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?chess\.com/"
    r"(?:analysis/)?"
    r"game/(?P<kind>live|daily)/(?P<id>\d+)"
    r"(?:[/?#].*)?$"
)
CHESSCOM_API_BASE = "https://api.chess.com"
CHESSCOM_ARCHIVES_URL = "{base}/pub/player/{user}/games/archives"

HTTP_TIMEOUT_SECONDS = 10.0
USER_AGENT = "Caissa/0.1 (personal chess post-mortem)"
MAX_CHESSCOM_ARCHIVE_MONTHS = 24

Site = Literal["lichess", "chesscom", "manual"]


class GameFetchError(Exception):
    """Raised when a game URL cannot be parsed or its PGN cannot be fetched."""


@dataclass(frozen=True)
class ParsedGameURL:
    site: Literal["lichess", "chesscom"]
    game_id: str


# ---- URL parsing -----------------------------------------------------------

def parse_game_url(url: str) -> ParsedGameURL:
    """Extract `(site, game_id)` from a Lichess or Chess.com game URL.

    Raises `GameFetchError` on unrecognized formats.
    """
    cleaned = url.strip()
    m = LICHESS_GAME_RE.match(cleaned)
    if m is not None:
        return ParsedGameURL(site="lichess", game_id=m.group("id"))
    m = CHESSCOM_GAME_RE.match(cleaned)
    if m is not None:
        return ParsedGameURL(site="chesscom", game_id=m.group("id"))
    raise GameFetchError(f"Unrecognized game URL: {cleaned!r}")


# ---- Lichess fetch ---------------------------------------------------------

def fetch_lichess_pgn(game_id: str, *, client: httpx.Client | None = None) -> str:
    """Download a single Lichess game's PGN."""
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
            raise GameFetchError(f"Lichess fetch failed: HTTP {resp.status_code}")
        text = resp.text.strip()
        if not text:
            raise GameFetchError("Lichess returned empty PGN.")
        return text

    if client is not None:
        return _do_get(client)
    with httpx.Client() as http:
        return _do_get(http)


# ---- Chess.com fetch -------------------------------------------------------

def _chesscom_url_matches_id(game_url: str, game_id: str) -> bool:
    """A Chess.com game JSON entry's `url` ends with the canonical numeric id."""
    if not game_url:
        return False
    return game_url.rstrip("/").rsplit("/", 1)[-1] == game_id


def fetch_chesscom_pgn(
    game_id: str,
    *,
    username: str,
    client: httpx.Client | None = None,
    max_months: int = MAX_CHESSCOM_ARCHIVE_MONTHS,
) -> str:
    """Walk a user's monthly Chess.com archives looking for `game_id`.

    Walks from newest to oldest, capped at `max_months` months.
    """
    if not username:
        raise GameFetchError(
            "CHESSCOM_USERNAME is not set in .env; cannot fetch Chess.com games."
        )
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    def _do(http: httpx.Client) -> str:
        archives_url = CHESSCOM_ARCHIVES_URL.format(base=CHESSCOM_API_BASE, user=username)
        resp = http.get(archives_url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
        if resp.status_code == 404:
            raise GameFetchError(f"Chess.com user {username!r} not found.")
        if resp.status_code != 200:
            raise GameFetchError(
                f"Chess.com archives lookup failed: HTTP {resp.status_code}"
            )
        archives: list[str] = resp.json().get("archives", [])
        # Newest first, capped.
        for monthly_url in reversed(archives[-max_months:]):
            month = http.get(monthly_url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
            if month.status_code != 200:
                logger.warning(
                    "Skipping unreadable Chess.com archive %s (HTTP %s)",
                    monthly_url, month.status_code,
                )
                continue
            for entry in month.json().get("games", []):
                if _chesscom_url_matches_id(entry.get("url", ""), game_id):
                    pgn = entry.get("pgn", "").strip()
                    if not pgn:
                        raise GameFetchError(
                            f"Chess.com game {game_id} found but has no PGN."
                        )
                    return pgn
        raise GameFetchError(
            f"Chess.com game {game_id} not found in {username!r}'s last "
            f"{max_months} months of archives."
        )

    if client is not None:
        return _do(client)
    with httpx.Client() as http:
        return _do(http)


# ---- Metadata builder ------------------------------------------------------

def build_metadata_from_pgn(*, site: Site, game_id: str, pgn: str) -> GameMetadata:
    """Parse a PGN into a `GameMetadata`. Raises `GameFetchError` on bad PGN."""
    game = parse_pgn(pgn)
    if game is None:
        raise GameFetchError("Could not parse PGN.")
    headers = game.headers
    white = headers.get("White", "?") or "?"
    black = headers.get("Black", "?") or "?"
    result = headers.get("Result", "*") or "*"
    time_control = headers.get("TimeControl", "") or ""
    time_class = classify_time_control(time_control)

    user_handle = (
        settings.lichess_username if site == "lichess"
        else settings.chesscom_username if site == "chesscom"
        else ""
    )
    user_color = extract_user_color(pgn, user_handle) if user_handle else None
    if user_color is None:
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
        time_control=time_control,
        time_class=time_class,
        pgn=pgn,
    )


# ---- Orchestrator ----------------------------------------------------------

def fetch_game(url: str, *, client: httpx.Client | None = None) -> GameMetadata:
    """End-to-end: URL → PGN → `GameMetadata`."""
    parsed = parse_game_url(url)
    if parsed.site == "lichess":
        pgn = fetch_lichess_pgn(parsed.game_id, client=client)
        return build_metadata_from_pgn(site="lichess", game_id=parsed.game_id, pgn=pgn)
    if parsed.site == "chesscom":
        pgn = fetch_chesscom_pgn(
            parsed.game_id,
            username=settings.chesscom_username,
            client=client,
        )
        return build_metadata_from_pgn(site="chesscom", game_id=parsed.game_id, pgn=pgn)
    raise GameFetchError(f"Unsupported site: {parsed.site}")
