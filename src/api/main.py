"""FastAPI entry point — Phase 1 stubs only."""

from __future__ import annotations

import logging

from fastapi import FastAPI

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
    """Phase 1 stub — Module B diff wires up in Phase 3."""
    logger.info("repertoire/diff stub called for user=%s", req.username)
    return RepertoireDeviation(
        deviated=False,
        deviation_move_number=None,
        move_played=None,
        move_expected=None,
        fen_at_deviation=None,
        repertoire_line_name=None,
    )


@app.post("/eval", response_model=EvalResponse)
def eval_position(req: EvalRequest) -> EvalResponse:
    """Phase 1 stub — engine clients wire up in Phase 3."""
    logger.info("eval stub called source=%s", req.source)
    return EvalResponse(
        fen=req.fen,
        cp=0,
        mate=None,
        best_move_uci=None,
        pv=[],
        source="stub",
    )


@app.post("/game/fetch", response_model=GameMetadata)
def game_fetch(req: GameFetchRequest) -> GameMetadata:
    """Phase 1 stub — game fetcher wires up in Phase 2."""
    logger.info("game/fetch stub called url=%s", req.url)
    return GameMetadata(
        site="manual",
        game_id="stub",
        white_username="stub_white",
        black_username="stub_black",
        user_color="white",
        result="*",
        pgn=req.pgn_override or "",
    )


@app.get("/youtube_search", response_model=YouTubeSearchResponse)
def youtube_search() -> YouTubeSearchResponse:
    """Module E is deferred. Returns a stable deferral payload."""
    return YouTubeSearchResponse(
        status="deferred",
        use_chessvision_extension_for_now=True,
    )
