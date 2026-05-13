"""Pydantic schemas for all I/O at module boundaries."""

from typing import Literal

from pydantic import BaseModel


class GameFetchRequest(BaseModel):
    url: str
    pgn_override: str | None = None


TimeClass = Literal[
    "ultrabullet",
    "bullet",
    "blitz",
    "rapid",
    "classical",
    "correspondence",
    "unknown",
]


class GameMetadata(BaseModel):
    site: Literal["lichess", "chesscom", "manual"]
    game_id: str
    white_username: str
    black_username: str
    user_color: Literal["white", "black"]
    result: str
    time_control: str = ""  # Raw PGN TimeControl header, e.g. "300+0" or "1/86400"
    time_class: TimeClass = "unknown"
    pgn: str


class EngineAnalysisInput(BaseModel):
    eval_cp: int | None = None
    mate: int | None = None
    best_move_uci: str
    best_move_san: str
    pv: list[str] = []  # UCI strings
    depth: int | None = None


class AdviseRequest(BaseModel):
    fen: str
    user_color: Literal["white", "black"]
    engine_analysis: EngineAnalysisInput | None = None
    game_phase_hint: Literal["opening", "middlegame", "endgame"] | None = None


class BookCitation(BaseModel):
    source: str
    page: int
    snippet: str


class EngineInputEcho(BaseModel):
    eval_cp: int | None = None
    mate: int | None = None
    best_move_san: str


class AdviseResponse(BaseModel):
    fen: str
    explanation: str
    citations: list[BookCitation]
    classifier_tags: list[str]
    model_used: Literal["local", "openrouter", "openai"]
    engine_input_echo: EngineInputEcho


class RepertoireDiffRequest(BaseModel):
    pgn: str
    username: str
    game_id: str | None = None


class MoveInBook(BaseModel):
    ply: int
    san: str
    user_color: Literal["white", "black"]


class RepertoireExpectedMove(BaseModel):
    san: str
    uci: str
    line_name: str | None


class DeviationDetail(BaseModel):
    occurred: bool
    deviation_ply: int | None
    deviation_move_number: int | None
    move_played_san: str | None
    move_played_uci: str | None
    fen_before_deviation: str | None
    expected_moves_from_repertoire: list[RepertoireExpectedMove]
    deepest_repertoire_match_node_id: int | None


class DeviationReport(BaseModel):
    game_id: str
    user_color: Literal["white", "black"]
    in_book_until_ply: int
    deviation: DeviationDetail
    moves_in_book: list[MoveInBook]


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
