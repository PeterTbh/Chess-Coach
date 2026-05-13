"""Tests for the LLM strategic-explanation generator (Slice 4b).

All tests use a fake chat client — no live network calls.
"""

from __future__ import annotations

import pytest

from src.advisor.llm import (
    SYSTEM_PROMPT,
    Citation,
    EngineAnalysis,
    LlmApiError,
    LlmHallucinationError,
    LlmRequest,
    LlmResult,
    OpenAIClient,
    OpenRouterClient,
    allowed_moves_from_engine,
    build_user_prompt,
    extract_san_tokens,
    find_hallucinated_moves,
    generate_explanation,
)

STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def _engine(
    *,
    best_uci: str = "e2e4",
    best_san: str = "e4",
    pv: list[str] | None = None,
    eval_cp: int | None = 30,
) -> EngineAnalysis:
    return EngineAnalysis(
        eval_cp=eval_cp,
        mate=None,
        best_move_uci=best_uci,
        best_move_san=best_san,
        pv_uci=pv if pv is not None else ["e2e4", "e7e5", "g1f3"],
        depth=22,
    )


def _request(*, fen: str = STARTING_FEN, **engine_kw) -> LlmRequest:
    return LlmRequest(
        fen=fen,
        tags=["open_center", "semi_open_center"],
        user_color="white",
        game_phase_hint="opening",
        engine=_engine(**engine_kw),
        citations=[
            Citation(source="Test Author - Test Book", page=42, snippet="An example passage."),
        ],
    )


class _FakeClient:
    """Returns a queued list of responses, one per call. Considered configured."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def is_configured(self) -> bool:
        return True

    def chat_completions_create(
        self, *, model: str, messages: list[dict[str, str]]
    ) -> str:
        self.calls.append({"model": model, "messages": list(messages)})
        if not self._responses:
            raise AssertionError("FakeClient ran out of responses")
        return self._responses.pop(0)


# ---- SAN extractor -------------------------------------------------------

def test_extract_san_matches_piece_moves() -> None:
    """Piece moves and captures are flagged; bare pawn pushes are deliberately
    not matched (they collide with square references in prose)."""
    text = "After e4, white develops with Nf3 and Bb5."
    toks = extract_san_tokens(text)
    assert "Nf3" in toks
    assert "Bb5" in toks
    # Bare pawn push intentionally not in the match set.
    assert "e4" not in toks


def test_extract_san_matches_capture_check_mate() -> None:
    text = "Then Bxe5+ and finally Qh7#."
    toks = extract_san_tokens(text)
    # Flags are stripped by normalisation.
    assert "Bxe5" in toks
    assert "Qh7" in toks


def test_extract_san_matches_castling_both_styles() -> None:
    text = "After 0-0 black plays O-O-O."
    toks = extract_san_tokens(text)
    assert "O-O" in toks  # both 0-0 and O-O normalise to O-O
    assert "O-O-O" in toks


def test_extract_san_matches_promotion_and_disambiguation() -> None:
    text = "The d-pawn runs to d8=Q and the rook Rae1 supports."
    toks = extract_san_tokens(text)
    assert "d8=Q" in toks
    assert "Rae1" in toks


def test_extract_san_dedupes_repeated_tokens() -> None:
    toks = extract_san_tokens("Nf3 ... Nf3 ... Nf3")
    assert toks.count("Nf3") == 1


def test_extract_san_ignores_plain_english_words() -> None:
    text = "The position calls for prophylactic thinking and patient play."
    toks = extract_san_tokens(text)
    assert toks == []


# ---- allowed_moves_from_engine ------------------------------------------

def test_allowed_includes_best_move() -> None:
    allowed = allowed_moves_from_engine(STARTING_FEN, _engine(best_san="e4"))
    assert "e4" in allowed


def test_allowed_converts_pv_uci_to_san() -> None:
    eng = _engine(
        best_uci="e2e4", best_san="e4",
        pv=["e2e4", "e7e5", "g1f3", "b8c6"],
    )
    allowed = allowed_moves_from_engine(STARTING_FEN, eng)
    assert {"e4", "e5", "Nf3", "Nc6"} <= allowed


def test_allowed_skips_invalid_uci_but_keeps_walking() -> None:
    """A malformed PV entry shouldn't abort the rest of the chain."""
    eng = _engine(pv=["e2e4", "ZZZZ", "g1f3"])  # second is junk
    allowed = allowed_moves_from_engine(STARTING_FEN, eng)
    assert "e4" in allowed


def test_allowed_handles_bad_fen_gracefully() -> None:
    allowed = allowed_moves_from_engine("not a fen", _engine())
    # best move SAN is always included even if the FEN is unparseable.
    assert "e4" in allowed


# ---- find_hallucinated_moves --------------------------------------------

def test_find_hallucinated_returns_empty_when_only_allowed_used() -> None:
    allowed = {"e4", "e5", "Nf3"}
    text = "After e4 e5 Nf3 the king-pawn opening unfolds."
    assert find_hallucinated_moves(text, allowed) == []


def test_find_hallucinated_flags_unsupported_move() -> None:
    allowed = {"e4"}
    text = "After e4 white sometimes plays Nh3 too."
    assert "Nh3" in find_hallucinated_moves(text, allowed)


def test_find_hallucinated_ignores_check_and_mate_flags() -> None:
    """A move 'Bxe5+' must be considered identical to 'Bxe5' when allowed."""
    allowed = {"Bxe5"}
    assert find_hallucinated_moves("White plays Bxe5+!", allowed) == []


# ---- build_user_prompt ---------------------------------------------------

def test_prompt_contains_fen_tags_citations_and_engine() -> None:
    req = _request()
    p = build_user_prompt(req)
    assert STARTING_FEN in p
    assert "open_center" in p
    assert "Test Author - Test Book" in p
    assert "p.42" in p
    assert "An example passage." in p
    assert "+0.30" in p  # eval_cp formatting


def test_prompt_appends_retry_hint_when_provided() -> None:
    req = _request()
    p = build_user_prompt(req, retry_hint="please retry")
    assert p.endswith("please retry")


def test_system_prompt_locks_persona_and_word_count() -> None:
    assert "1500-2000 ELO" in SYSTEM_PROMPT
    assert "neutral" in SYSTEM_PROMPT.lower()
    assert "150-250 words" in SYSTEM_PROMPT


# ---- generate_explanation (end-to-end with FakeClient) -------------------

def test_clean_first_response_passes_with_zero_retries() -> None:
    client = _FakeClient([
        "White's best move is e4. The opening leads to space and central control."
    ])
    result = generate_explanation(_request(), openai_client=client)
    assert isinstance(result, LlmResult)
    assert result.retries_used == 0
    assert "e4" in result.explanation
    assert result.model_used == "openai"
    assert len(client.calls) == 1


def test_response_without_any_move_passes_immediately() -> None:
    """Explanation that discusses only structure (no SAN tokens) is fine."""
    client = _FakeClient([
        "The position features a balanced central structure with no immediate weaknesses."
    ])
    result = generate_explanation(_request(), openai_client=client)
    assert result.retries_used == 0


def test_hallucinated_move_triggers_one_retry_then_passes() -> None:
    client = _FakeClient([
        "White should play Nh3 to develop quickly.",  # Nh3 not in PV
        "White plays e4 to control the centre.",      # clean retry
    ])
    result = generate_explanation(_request(), openai_client=client)
    assert result.retries_used == 1
    assert len(client.calls) == 2
    # Retry call must include a corrective user turn referencing the bad move.
    retry_msgs = client.calls[1]["messages"]
    last_user = retry_msgs[-1]
    assert last_user["role"] == "user"
    assert "Nh3" in last_user["content"]


def test_hallucination_on_both_passes_raises() -> None:
    client = _FakeClient([
        "White plays Nh3 winning.",
        "Actually Nh3 is even better.",
    ])
    with pytest.raises(LlmHallucinationError) as info:
        generate_explanation(_request(), openai_client=client)
    assert "Nh3" in str(info.value)


def test_system_prompt_is_first_message() -> None:
    client = _FakeClient(["fine response with no moves at all"])
    generate_explanation(_request(), openai_client=client)
    msgs = client.calls[0]["messages"]
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == SYSTEM_PROMPT


def test_model_id_passed_through() -> None:
    client = _FakeClient(["ok"])
    generate_explanation(
        _request(),
        openai_client=client,
        openai_model="custom/test-model",
    )
    assert client.calls[0]["model"] == "custom/test-model"


# ---- OpenRouterClient error path ----------------------------------------

def test_openrouter_raises_when_api_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.advisor import llm as llm_mod
    monkeypatch.setattr(llm_mod.settings, "openrouter_api_key", "")
    cli = OpenRouterClient(api_key="")
    with pytest.raises(LlmApiError, match="OpenRouter API key is not configured"):
        cli.chat_completions_create(
            model="google/gemma-4-31b-it:free",
            messages=[{"role": "user", "content": "hi"}],
        )


def test_openrouter_wraps_sdk_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = OpenRouterClient(api_key="dummy-test-key")

    class _Boom:
        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                def create(**_kw):
                    raise RuntimeError("boom")
    cli._client = _Boom()  # bypass lazy load
    with pytest.raises(LlmApiError, match="boom"):
        cli.chat_completions_create(model="m", messages=[])


# ---- OpenAIClient sanity -----------------------------------------------

def test_openai_client_reports_not_configured_when_key_empty() -> None:
    cli = OpenAIClient(api_key="")
    assert cli.is_configured() is False


def test_openai_client_raises_when_used_without_key() -> None:
    cli = OpenAIClient(api_key="")
    with pytest.raises(LlmApiError, match="OpenAI API key is not configured"):
        cli.chat_completions_create(model="gpt-5-mini", messages=[])
