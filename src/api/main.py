"""FastAPI entry point — Phase 1 stubs only."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from src.advisor.corpus import (
    BgeEmbedder,
    CorpusError,
    build_or_refresh_corpus,
    get_client,
    get_or_create_collection,
)
from src.advisor.llm import LlmApiError, LlmHallucinationError
from src.advisor.pipeline import AdviseError
from src.advisor.pipeline import advise as run_advise
from src.api.game_fetcher import GameFetchError, build_metadata_from_pgn, fetch_game
from src.engine.lichess_eval import (
    InvalidFenError,
    LichessEvalError,
    PositionNotInCloudError,
    fetch_cloud_eval,
)
from src.engine.stockfish import (
    StockfishError,
    StockfishUnavailableError,
    analyse_position,
)
from src.repertoire.diff import DiffError, diff_game
from src.repertoire.store import (
    DEFAULT_DB_PATH,
    RepertoireError,
    RepertoireNotFoundError,
    init_db,
)
from src.shared.schemas import (
    AdviseRequest,
    AdviseResponse,
    DeviationReport,
    EvalRequest,
    EvalResponse,
    GameFetchRequest,
    GameMetadata,
    HealthResponse,
    RepertoireDiffRequest,
    YouTubeSearchResponse,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

VERSION = "0.1.0"


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Refresh the corpus index from the seed file on every startup.

    Lazy embedder load — if the seed file is unchanged the indexer
    skips before the heavy sentence-transformers import happens.
    """
    try:
        embedder = BgeEmbedder()
        client = get_client()
        collection = get_or_create_collection(client, embedder)
        written = build_or_refresh_corpus(collection)
        logger.info("startup: corpus rows indexed=%d", written)
    except CorpusError as exc:
        logger.warning("startup: corpus index skipped: %s", exc)
    yield


app = FastAPI(title="Caissa API", version=VERSION, lifespan=_lifespan)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=VERSION)


@app.post("/advise", response_model=AdviseResponse)
def advise(req: AdviseRequest) -> AdviseResponse:
    """Strategic explanation pipeline (classify → retrieve → LLM)."""
    logger.info("advise called fen=%s user=%s", req.fen, req.user_color)
    try:
        return run_advise(req)
    except LlmHallucinationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except LlmApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except AdviseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/repertoire/diff", response_model=DeviationReport)
def repertoire_diff(req: RepertoireDiffRequest) -> DeviationReport:
    """Detect first user deviation against the user's SQLite repertoire.

    The repertoire is lazy-loaded from `data/repertoires/{color}.pgn` on
    first request and reloaded whenever the PGN's mtime is newer than the
    stored `loaded_at`. Returns the full :class:`DeviationReport`.
    """
    logger.info("repertoire/diff called for user=%s", req.username)
    conn = init_db(DEFAULT_DB_PATH)
    try:
        return diff_game(req.pgn, req.username, conn, game_id=req.game_id)
    except RepertoireNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No repertoire file for the user's color. Place one at "
                f"data/repertoires/<color>.pgn — see CLAUDE.md. ({exc})"
            ),
        ) from exc
    except RepertoireError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DiffError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@app.post("/eval", response_model=EvalResponse)
def eval_position(req: EvalRequest) -> EvalResponse:
    """Evaluate a position via Lichess Cloud Eval or local Stockfish.

    Source dispatch:
    - ``"lichess_cloud"`` — only Lichess. 404 surfaced as 404.
    - ``"local_stockfish"`` — only local Stockfish.
    - ``"any"`` — try Lichess first, fall back to Stockfish on 404 or
      upstream failure.
    """
    logger.info("eval called source=%s", req.source)

    if req.source == "local_stockfish":
        return _eval_via_stockfish(req.fen)

    try:
        return fetch_cloud_eval(req.fen)
    except InvalidFenError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PositionNotInCloudError as exc:
        if req.source == "any":
            logger.info("Lichess 404 for %s — falling back to Stockfish", req.fen)
            return _eval_via_stockfish(req.fen)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LichessEvalError as exc:
        if req.source == "any":
            logger.info("Lichess upstream error — falling back to Stockfish: %s", exc)
            return _eval_via_stockfish(req.fen)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _eval_via_stockfish(fen: str) -> EvalResponse:
    try:
        return analyse_position(fen)
    except StockfishUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except StockfishError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/game/fetch", response_model=GameMetadata)
def game_fetch(req: GameFetchRequest) -> GameMetadata:
    """Fetch a single game's PGN and metadata.

    Phase 2 slice 1: Lichess URLs are fetched live. Chess.com lands in
    slice 2. A `pgn_override` short-circuits the fetch (manual paste).
    """
    logger.info("game/fetch called url=%s override=%s", req.url, bool(req.pgn_override))
    try:
        if req.pgn_override:
            return build_metadata_from_pgn(
                site="manual", game_id="manual", pgn=req.pgn_override
            )
        return fetch_game(req.url)
    except GameFetchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/youtube_search", response_model=YouTubeSearchResponse)
def youtube_search() -> YouTubeSearchResponse:
    """Module E is deferred. Returns a stable deferral payload."""
    return YouTubeSearchResponse(
        status="deferred",
        use_chessvision_extension_for_now=True,
    )
