# CLAUDE.md — Caissa

**Current status: Phase 2 in progress (foundations: game fetcher + repertoire parser).**

## Mission

Build a local, single-user chess post-mortem tool. After playing on Lichess or
Chess.com, the user opens the local Streamlit app, pastes the game URL, and
sees three stacked panels:

1. Where they left their opening prep (repertoire diff against
   `data/repertoires/white.pgn` or `black.pgn`).
2. Where they went wrong tactically/positionally (Lichess Cloud Eval API,
   fallback local Stockfish for chess.com positions).
3. What the position was actually about (fine-tuned Gemma 4 E4B trained on a
   curated corpus of English-language chess strategy books, with Anthropic API
   fallback).

The intellectual contribution is the integration architecture and the extracted
book corpus, not novel ML research.

## Modules (v1)

- **A — Strategic Advisor (CORE).** FEN → rule-based position classifier →
  RAG over book corpus → LLM (Gemma local primary, Anthropic fallback) →
  formatted explanation with citations. Voice: neutral analytical, English,
  ~1500–2000 ELO. No personalization.
- **B — Repertoire Deviation Detector.** PGN game vs. exactly two PGN files
  per user (`white.pgn`, `black.pgn`). Walk both move lists in parallel until
  divergence; report move number, move played, move expected. The user
  supplies `data/repertoires/{white,black}.pgn` themselves (Lichess Studies
  export, hand-written PGN, etc.); Caissa consumes whatever's at those paths.
- **C — Chessable export.** **Paused.** Chessable has no export and
  scraping violates ToS. Caissa expects user-supplied PGNs at
  `data/repertoires/{white,black}.pgn`. Revisit only if Chessable opens an
  official export API.
- **D — Streamlit Web App.** Localhost:8501. URL input → PGN fetch → three
  panels. Board rendered via `streamlit.components.v1` with chessboard.js.
  Aggressive `st.cache_data` keyed by `(FEN, classifier_tags)`.
- **E — YouTube reverse search.** **Deferred.** `/youtube_search` returns a
  stub deferral payload.

## Build Order (phases)

1. **Phase 1 — Scaffold (THIS PHASE).** Repo structure, Docker, FastAPI
   stubs, Streamlit landing, schemas, chess_utils.
   *Acceptance:* `docker compose up` works, `/health` 200, Streamlit loads.
2. **Phase 2 — Foundations.** Game fetcher (Lichess + Chess.com), URL input
   metadata display, Module B PGN parser.
3. **Phase 3 — Scale & Engine Source.** PDF extraction pipeline (1 book →
   top 50, ≥5,000 rows). Module B diff logic. Lichess Cloud Eval client.
4. **Phase 4 — RAG & Wire-Up.** ChromaDB indexed. `/advise` returns valid
   `AdviseResponse` via Anthropic fallback. All three panels render.
5. **Phase 5 — SHIP GATE.** End-to-end Lichess + Chess.com flows.
   *Failure cut:* drop chess.com, do not start fine-tune.
6. **Phase 6 — Fine-tune Dataset.** ~2,000 instruction pairs, ≤€15.
7. **Phase 7 — QLoRA Fine-tune.** Unsloth on Colab Pro, 2–4 hours. Save
   adapter, convert to GGUF.
8. **Phase 8 — Local Inference Swap.** Module A primary = llama.cpp,
   fallback = Anthropic. Side-by-side toggle.
9. **Phase 9 — Edge Cases & Hardening.** PGN edge cases, error handling,
   5 real games end-to-end.
10. **Phase 10 — Polish & Demo.** UI tightening, operational README, demo
    video (3–5 min, 2–3 takes).

## Tech Stack (locked)

| Layer        | Choice                                                  |
|--------------|---------------------------------------------------------|
| Python       | 3.11 + uv                                               |
| PDF          | PyMuPDF                                                 |
| Engine       | Stockfish 17 (Docker fallback) + Lichess Cloud Eval     |
| Vision       | gudbrandtandberg/ChessVision (later)                    |
| Embeddings   | bge-small-en-v1.5                                       |
| Vector DB    | ChromaDB (Docker)                                       |
| LLM dev      | Anthropic API (Sonnet 4.6)                              |
| LLM prod     | llama.cpp + GGUF Gemma 4 E4B (host, not Docker)         |
| Fine-tune    | Unsloth + QLoRA on Colab Pro                            |
| Backend      | FastAPI + Uvicorn (Docker)                              |
| UI           | Streamlit (Docker, 8501)                                |
| Game APIs    | Lichess Open API, Chess.com Public Data¹                |
| PGN          | python-chess                                            |
| Board render | `streamlit.components.v1` + chessboard.js               |

LLM inference runs on the Mac host (Apple Silicon Metal not available inside
Docker). Everything else is Docker Compose.

¹ `openingtree/openingtree` (JS/React SPA) is **read-only reference** for
bulk-fetch URL construction patterns (Lichess filters, Chess.com archives
walker). Not a runtime dependency. Phase 2 implements single-game fetch
directly with `httpx`; revisit only if bulk repertoire mining is needed.

## Code Conventions

- Type hints everywhere; no `Any`.
- Pydantic for all I/O at module boundaries.
- `ruff` lint, `pytest` tests.
- Streamlit: `st.session_state`, `st.cache_data`/`st.cache_resource`.
- stdlib `logging`, no `print()` in `src/`.
- Secrets in `.env`; `.env.example` shows schema.
- Conventional commits, feature branches per module.

## Get-Shit-Done 2.0 Hooks

**Per turn:**
- State module(s) being touched.
- State smallest testable end-to-end slice.
- Write code, run it, show output.
- End with: working / stubbed / next slice.

**Per session:**
- Read `CLAUDE.md` first.
- Run previous phase's acceptance before new work.
- Scope creep → `notebooks/PHASE2_IDEAS.md`.

## Failure Mode Cuts (in order)

1. Module E stub (already deferred).
2. Chess.com support (Lichess-only).
3. Position classifier sophistication.
4. Gemma fine-tune itself (Anthropic stays primary).

**Do not cut:** Module A RAG, Module B diff, Streamlit panels on Lichess.

## Demo Scenario (Phase 10 target)

User pastes a Lichess Catalan game URL where they deviated on move 9.

- Panel 1: "Deviation on move 9. You played Bd2; repertoire plays Qc2."
- Panel 2: Eval graph showing drop from +0.4 to -0.7 over moves 9–12.
- Panel 3: Analytical paragraph on the Catalan plan with a book citation.

User clicks move 22 (IQP middlegame). Panel 3 updates with IQP-specific
explanation citing Watson MCO vol. 1 p. 142.

Build for this exact walkthrough. Nothing else.
