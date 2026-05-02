"""Pydantic schemas for all I/O at module boundaries."""

from typing import Literal

from pydantic import BaseModel


class GameFetchRequest(BaseModel):
    url: str
    pgn_override: str | None = None


class GameMetadata(BaseModel):
    site: Literal["lichess", "chesscom", "manual"]
    game_id: str
    white_username: str
    black_username: str
    user_color: Literal["white", "black"]
    result: str
    pgn: str


class AdviseRequest(BaseModel):
    fen: str
    game_url: str | None = None
    player_color: Literal["white", "black"] | None = None


class BookCitation(BaseModel):
    source: str
    page: int
    snippet: str


class AdviseResponse(BaseModel):
    fen: str
    explanation: str
    citations: list[BookCitation]
    classifier_tags: list[str]
    model_used: Literal["gemma_local", "anthropic_fallback"]


class RepertoireDiffRequest(BaseModel):
    pgn: str
    username: str


class RepertoireDeviation(BaseModel):
    deviated: bool
    deviation_move_number: int | None
    move_played: str | None
    move_expected: str | None
    fen_at_deviation: str | None
    repertoire_line_name: str | None


class EvalRequest(BaseModel):
    fen: str
    source: Literal["lichess_cloud", "local_stockfish", "any"]


class EvalResponse(BaseModel):
    fen: str
    cp: int | None
    mate: int | None
    best_move_uci: str | None
    pv: list[str]
    source: str


class GameEvalSeries(BaseModel):
    plies: list[EvalResponse]
    largest_drop_ply: int | None


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


class YouTubeSearchResponse(BaseModel):
    status: Literal["deferred"]
    use_chessvision_extension_for_now: bool
