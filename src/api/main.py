"""FastAPI entry point — Phase 1 stubs only."""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException

from src.api.game_fetcher import GameFetchError, build_metadata_from_pgn, fetch_game
from src.engine.lichess_eval import (
    InvalidFenError,
    LichessEvalError,
    PositionNotInCloudError,
    fetch_cloud_eval,
)
from src.repertoire.diff import DiffError, diff_game
from src.repertoire.parser import (
    RepertoireError,
    RepertoireNotFoundError,
    load_default_repertoire,
)
from src.shared.chess_utils import extract_user_color
from src.shared.schemas import (
    AdviseRequest,
    AdviseResponse,
    BookCitation,
    EvalRequest,
    EvalResponse,
    GameFetchRequest,
    GameMetadata,
    HealthResponse,
    RepertoireDeviation,
    RepertoireDiffRequest,
    YouTubeSearchResponse,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

VERSION = "0.1.0"

app = FastAPI(title="Caissa API", version=VERSION)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=VERSION)


@app.post("/advise", response_model=AdviseResponse)
def advise(req: AdviseRequest) -> AdviseResponse:
    """Phase 1 stub — Module A wires up in Phase 4."""
    logger.info("advise stub called fen=%s", req.fen)
    return AdviseResponse(
        fen=req.fen,
        explanation="[stub] Strategic advisor not wired yet. Phase 4.",
        citations=[
            BookCitation(source="stub", page=0, snippet="placeholder"),
        ],
        classifier_tags=["stub"],
        model_used="anthropic_fallback",
    )


@app.post("/repertoire/diff", response_model=RepertoireDeviation)
def repertoire_diff(req: RepertoireDiffRequest) -> RepertoireDeviation:
    """Detect first user deviation from `data/repertoires/{color}.pgn`.

    Color is inferred from the PGN ``[White]``/``[Black]`` headers using
    ``req.username``. The matching repertoire file is loaded from the
    default location.
    """
    logger.info("repertoire/diff called for user=%s", req.username)

    color = extract_user_color(req.pgn, req.username)
    if color is None:
        raise HTTPException(
            status_code=400,
            detail=f"Username {req.username!r} not in PGN [White]/[Black] headers",
        )

    try:
        repertoire = load_default_repertoire(color)
    except RepertoireNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No repertoire file for {color}. Place one at "
                f"data/repertoires/{color}.pgn — see CLAUDE.md."
            ),
        ) from exc
    except RepertoireError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        return diff_game(req.pgn, req.username, repertoire)
    except DiffError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/eval", response_model=EvalResponse)
def eval_position(req: EvalRequest) -> EvalResponse:
    """Evaluate a position via Lichess Cloud Eval.

    Source dispatch:
    - ``"lichess_cloud"`` / ``"any"`` — query Lichess. 404 → 404.
    - ``"local_stockfish"`` — not yet wired (M3). Returns 501.
    """
    logger.info("eval called source=%s", req.source)

    if req.source == "local_stockfish":
        raise HTTPException(
            status_code=501, detail="local_stockfish not yet implemented (M3)"
        )

    try:
        return fetch_cloud_eval(req.fen)
    except InvalidFenError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PositionNotInCloudError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LichessEvalError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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
