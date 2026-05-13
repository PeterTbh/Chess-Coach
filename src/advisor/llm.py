"""OpenRouter-backed strategic-explanation generator (Slice 4b).

Per scope F2 step 3: take FEN + classifier tags + engine analysis +
retrieved book citations; ask the LLM for a ~150-250 word neutral
analytical explanation; verify that no move appears in the output that
isn't in the engine's PV or best move; retry once on violation.

Provider: OpenRouter, accessed via the OpenAI SDK (API-compatible).
Default model: ``google/gemma-4-31b-it:free`` — configurable via
``OPENROUTER_MODEL``. Heavy SDK import is lazy so importing this module
is free.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol

import chess

from src.shared.settings import settings

logger = logging.getLogger(__name__)

MODEL_USED_OPENAI = "openai"

# ---- Errors --------------------------------------------------------------


class LlmError(Exception):
    """Base for LLM module errors."""


class LlmApiError(LlmError):
    """OpenRouter call failed (network, auth, 5xx, malformed response)."""


class LlmHallucinationError(LlmError):
    """The model mentioned a move outside the engine PV twice in a row."""


# ---- Inputs / outputs ----------------------------------------------------


@dataclass(frozen=True)
class Citation:
    source: str
    page: int
    snippet: str


@dataclass(frozen=True)
class EngineAnalysis:
    eval_cp: int | None
    mate: int | None
    best_move_uci: str
    best_move_san: str
    pv_uci: list[str]
    depth: int | None = None


@dataclass(frozen=True)
class LlmRequest:
    fen: str
    tags: list[str]
    user_color: str
    game_phase_hint: str | None
    engine: EngineAnalysis
    citations: list[Citation]


@dataclass(frozen=True)
class LlmResult:
    explanation: str
    model_used: str
    retries_used: int  # 0 = clean first try, 1 = retried once and passed


# ---- SAN extraction + allowed-set ----------------------------------------

# SAN token recogniser.
#
# We intentionally do NOT match bare pawn pushes like "e4" — those collide
# constantly with square references in prose ("the rook on f1", "the d5
# square"), producing false hallucination flags. We accept the trade-off
# that pawn-only inventions can slip through; piece moves, captures, and
# castling are the cases that matter and they're all unambiguous in text.
_SAN_PATTERN = re.compile(
    r"\b("
    r"O-O(?:-O)?"
    r"|0-0(?:-0)?"
    r"|[KQRBN][a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?"  # piece moves
    r"|[a-h]x[a-h][1-8](?:=[QRBN])?[+#]?"                 # pawn captures
    r"|[a-h][18]=[QRBN][+#]?"                              # pawn promotion
    r")\b"
)


def _normalise_san(s: str) -> str:
    """Strip flags + canonicalise castling so comparisons aren't fooled by '+'/'#'."""
    s = s.replace("0-0", "O-O")
    s = s.rstrip("+#")
    return s


def extract_san_tokens(text: str) -> list[str]:
    """Return every plausible SAN-looking token in ``text``, deduped + normalised."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _SAN_PATTERN.finditer(text):
        token = _normalise_san(m.group(1))
        if token not in seen:
            seen.add(token)
            out.append(token)
    return out


def allowed_moves_from_engine(fen: str, engine: EngineAnalysis) -> set[str]:
    """Build the legal-moves whitelist: ``best_move_san`` + PV converted to SAN."""
    allowed = {_normalise_san(engine.best_move_san)}
    try:
        board = chess.Board(fen)
    except ValueError:
        return allowed
    for uci in engine.pv_uci:
        try:
            move = chess.Move.from_uci(uci)
            if move in board.legal_moves:
                san = board.san(move)
                allowed.add(_normalise_san(san))
                board.push(move)
        except (ValueError, AssertionError):
            # Unparseable UCI in PV — skip but keep walking the rest.
            continue
    return allowed


def find_hallucinated_moves(text: str, allowed: set[str]) -> list[str]:
    """Return tokens from ``text`` that look like moves but aren't allowed."""
    return [t for t in extract_san_tokens(text) if t not in allowed]


# ---- Prompts -------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a chess analyst writing for a 1500-2000 ELO club player. "
    "Voice: neutral, analytical, English. "
    "Explain only what the engine evaluation and the retrieved book "
    "passages support. Do not invent moves or evaluations. "
    "If you reference a move, it must be one I have provided in the "
    "engine analysis (best move or principal variation). "
    "Length: 150-250 words. No bullet lists; one cohesive paragraph."
)


def build_user_prompt(req: LlmRequest, *, retry_hint: str | None = None) -> str:
    """Compose the per-call prompt. ``retry_hint`` is appended on a retry pass."""
    eval_str = _format_eval(req.engine)
    tag_str = ", ".join(req.tags) if req.tags else "(none)"
    pv_san = _pv_to_san_string(req.fen, req.engine)
    cit_block = (
        "\n\n".join(
            f"[{i + 1}] {c.source}, p.{c.page}: {c.snippet}"
            for i, c in enumerate(req.citations)
        )
        or "(no retrieved passages)"
    )
    phase = f"\nPhase hint: {req.game_phase_hint}" if req.game_phase_hint else ""
    body = (
        f"FEN: {req.fen}\n"
        f"User color: {req.user_color}{phase}\n"
        f"Classifier tags: {tag_str}\n"
        f"Engine evaluation: {eval_str}\n"
        f"Engine best move (SAN): {req.engine.best_move_san}\n"
        f"Principal variation (SAN): {pv_san}\n\n"
        f"Retrieved book passages:\n{cit_block}\n\n"
        "Write the explanation now."
    )
    if retry_hint:
        body += f"\n\n{retry_hint}"
    return body


def _format_eval(engine: EngineAnalysis) -> str:
    if engine.mate is not None:
        return f"mate in {engine.mate}"
    if engine.eval_cp is None:
        return "unknown"
    sign = "+" if engine.eval_cp >= 0 else ""
    return f"{sign}{engine.eval_cp / 100:.2f} (white POV)"


def _pv_to_san_string(fen: str, engine: EngineAnalysis) -> str:
    try:
        board = chess.Board(fen)
    except ValueError:
        return "(unavailable)"
    sans: list[str] = []
    for uci in engine.pv_uci[:6]:  # cap PV length in the prompt
        try:
            move = chess.Move.from_uci(uci)
            if move not in board.legal_moves:
                break
            sans.append(board.san(move))
            board.push(move)
        except (ValueError, AssertionError):
            break
    return " ".join(sans) if sans else "(none)"


# ---- OpenAI client -------------------------------------------------------


class _ChatClient(Protocol):
    def chat_completions_create(
        self, *, model: str, messages: list[dict[str, str]]
    ) -> str: ...


class OpenAIClient:
    """OpenAI Chat Completions wrapper. Heavy SDK import is lazy."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else settings.openai_api_key
        self._base_url = base_url or settings.openai_base_url
        self._timeout = (
            timeout if timeout is not None else settings.openai_timeout_seconds
        )
        self._client: Any = None

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _load(self) -> Any:
        if self._client is None:
            if not self._api_key:
                raise LlmApiError("OpenAI API key is not configured")
            from openai import OpenAI  # heavy import deferred
            self._client = OpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=self._timeout,
            )
        return self._client

    def chat_completions_create(
        self, *, model: str, messages: list[dict[str, str]]
    ) -> str:
        try:
            response = self._load().chat.completions.create(
                model=model,
                messages=messages,
            )
        except Exception as exc:  # openai raises a tree of subclasses
            raise LlmApiError(f"OpenAI call failed: {exc}") from exc
        try:
            return response.choices[0].message.content or ""
        except (AttributeError, IndexError) as exc:
            raise LlmApiError(f"OpenAI response shape unexpected: {response!r}") from exc


# ---- Main entry ----------------------------------------------------------


def _try_provider(
    *,
    client: _ChatClient,
    model: str,
    model_label: str,
    req: LlmRequest,
    allowed: set[str],
) -> LlmResult:
    """Run one provider's full attempt cycle: call → hallucination check →
    one retry. Raises :class:`LlmApiError` or :class:`LlmHallucinationError`
    on terminal failure. The caller decides whether to fall back."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(req)},
    ]
    text = client.chat_completions_create(model=model, messages=messages)
    bad = find_hallucinated_moves(text, allowed)
    if not bad:
        return LlmResult(explanation=text.strip(), model_used=model_label, retries_used=0)

    logger.info("[%s] hallucinated moves on first pass: %s — retrying", model_label, bad)
    retry_hint = (
        "Your previous response mentioned moves that are not in the engine output: "
        f"{', '.join(bad)}. "
        f"Use only these moves: {sorted(allowed)}. Rewrite the explanation."
    )
    messages.append({"role": "assistant", "content": text})
    messages.append({"role": "user", "content": retry_hint})
    text2 = client.chat_completions_create(model=model, messages=messages)
    bad2 = find_hallucinated_moves(text2, allowed)
    if not bad2:
        return LlmResult(explanation=text2.strip(), model_used=model_label, retries_used=1)

    raise LlmHallucinationError(
        f"[{model_label}] invented moves on both passes: first={bad}, retry={bad2}"
    )


def generate_explanation(
    req: LlmRequest,
    *,
    openai_client: OpenAIClient | _ChatClient | None = None,
    openai_model: str | None = None,
) -> LlmResult:
    """Generate a strategic explanation through OpenAI.

    The call runs once, then once more on a hallucination violation, then
    raises :class:`LlmHallucinationError`. API failures bubble up as
    :class:`LlmApiError` with the underlying message.
    """
    client = openai_client if openai_client is not None else OpenAIClient()
    model = openai_model or settings.openai_model
    allowed = allowed_moves_from_engine(req.fen, req.engine)

    return _try_provider(
        client=client,
        model=model,
        model_label=MODEL_USED_OPENAI,
        req=req,
        allowed=allowed,
    )
