# Caissa — Personal Chess Improvement System

A local-only post-mortem tool for solo chess study. Paste a Lichess or
Chess.com game URL and Caissa renders three stacked panels:

1. **Repertoire deviation** — the first move you left your prepared lines,
   with the moves your repertoire actually prepares.
2. **Engine evaluation** — Lichess Cloud Eval primary, local Stockfish as
   silent fallback. Per-ply graph plus per-move detail.
3. **Strategic commentary** — for a handful of critical moments (the
   deviation plus the biggest eval drops): a 150–250 word neutral
   analytical explanation, grounded in a small RAG corpus of canonical
   chess strategy passages, with book citations.

Python-only, runs on localhost, single-user.

## For AI assistants helping set this up

If you're an LLM agent reading this README to help the user, the
following 60-second briefing covers everything you need:

- **What runs:** two host processes. FastAPI backend on `:8000` and
  Streamlit UI on `:8501`. The UI talks to the backend over `localhost`.
  Not a single-process Streamlit app — cloud deploy needs refactoring
  (see *Limitations*).
- **Start order** (recommended): `uv run uvicorn src.api.main:app --reload`
  in one terminal, then `uv run streamlit run src/ui/streamlit_app.py`
  in another. Browser opens automatically to <http://localhost:8501>.
- **Required `.env`** (copy `.env.example` first):
  - `OPENAI_API_KEY` — Panel 3 dies without it.
  - `LICHESS_USERNAME` — needed so the deviation detector knows which
    colour the user played in fetched games.
  - `STOCKFISH_PATH` — absolute path to a Stockfish binary on disk.
  - `CHESSCOM_USERNAME` — only needed if the user pastes Chess.com URLs.
  - `OPENROUTER_*` — currently dead code, ignore.
- **Required filesystem**: drop the user's prepared openings at
  `data/repertoires/white.pgn` and/or `black.pgn`. Without these,
  Panel 1 just shows a "place a repertoire here" caption — Panels 2 + 3
  still work.
- **First-run gotchas**:
  - Cold `/advise` call downloads `BAAI/bge-small-en-v1.5` (~130 MB).
    Slow first request, fast after.
  - Corpus indexes on FastAPI startup from `data/corpus_seed.json`.
    Requires `with TestClient(app):` context if you're calling via test
    client, otherwise lifespan doesn't fire and citations come back empty.
  - The UI's `/advise` HTTP timeout is 60 s. Reasonable for `gpt-5-mini`;
    bump it if the user picks a slower model.
- **LLM provider:** OpenAI only (`generate_explanation` in
  `src/advisor/llm.py`). To swap providers, edit `OpenAIClient` or pass
  a custom `openai_client` instance into `generate_explanation`.
- **Tests:** `uv run pytest` — expect 204 passing, 0 skipped. `uv run
  ruff check src tests` should be clean. Streamlit panels are tested
  via `streamlit.testing.v1.AppTest`.
- **Do not deploy as-is to Streamlit Community Cloud** — the cloud
  runs only one process and there's no FastAPI server on that side.
  Refactor the UI's HTTP calls to direct function calls into the
  `pipeline`/`diff_game`/`analyse_position` modules first.

## Architecture

| Layer | Choice |
|---|---|
| Python | 3.11, [uv](https://docs.astral.sh/uv/) |
| Backend | FastAPI + Uvicorn |
| UI | Streamlit (`localhost:8501`) |
| Repertoire store | SQLite (`data/caissa.sqlite`) |
| Engine | Lichess Cloud Eval API → local Stockfish (host binary) |
| RAG vector DB | ChromaDB persistent client (`data/chroma/`) |
| Embeddings | `BAAI/bge-small-en-v1.5` via sentence-transformers |
| LLM | OpenAI (`gpt-5-mini` by default) via the openai SDK |
| PGN, board SVG | `python-chess` |

The strategic-commentary pipeline is `classify(FEN) → retrieve top-3 from
ChromaDB → LLM call → anti-hallucination regex check → result`. Anything
the model says that looks like a move must appear in the engine's PV or
the best move; otherwise the LLM is asked to rewrite once, and a second
violation surfaces as an error.

## Quick start

### 1. Prerequisites

- Python 3.11 (uv installs it for you).
- macOS, Linux, or WSL.
- For local engine fallback: a Stockfish binary somewhere on disk
  ([download](https://stockfishchess.org/download/)).

### 2. Install

```bash
git clone <repo-url> Chess-Coach
cd Chess-Coach
uv sync --extra dev
```

### 3. Configure `.env`

Copy `.env.example` to `.env` and fill in:

```bash
cp .env.example .env
```

Required (or fallback won't work):

| Variable | What it does |
|---|---|
| `LICHESS_USERNAME` / `CHESSCOM_USERNAME` | Which side of fetched games is *you*, so the deviation detector picks the right repertoire. |
| `STOCKFISH_PATH` | Absolute path to your Stockfish binary. Inside Docker `stockfish` works on PATH. |
| `OPENAI_API_KEY` | Required for Panel 3. Get one at <https://platform.openai.com/api-keys>. |
| `OPENAI_MODEL` | Default `gpt-5-mini`. |

### 4. Drop your repertoire PGNs

Caissa expects your prepared lines at:

```
data/repertoires/white.pgn   # your repertoire when playing White
data/repertoires/black.pgn   # your repertoire when playing Black
```

A **sample Catalan repertoire** ships at `data/repertoires/white.pgn`
(four chapters, 60 indexed positions) so Panel 1 is immediately
testable. Replace it with your own when you have one — same path,
same format. The black side is left unset on purpose: drop your own
`black.pgn` next to it.

Each file may contain a single PGN game with sub-tree variations, or
multiple concatenated games (one per chapter / opening). Export from
Lichess Studies or hand-write them; SQLite indexing is automatic on
the next `/repertoire/diff` request.

The store reloads from disk whenever the PGN file's `mtime` is newer
than the last indexed version — edit and re-run.

### 5. Run

**Host mode (recommended for first run, no Docker needed):**

```bash
# Terminal 1 — API
uv run uvicorn src.api.main:app --reload

# Terminal 2 — UI
uv run streamlit run src/ui/streamlit_app.py
```

Open <http://localhost:8501>.

**Docker mode (all services, including a Chroma server you don't actually need):**

```bash
docker compose up
```

The Chroma container in `docker-compose.yml` is left over from an earlier
plan; the running app uses an embedded persistent client at `data/chroma/`
regardless. You can ignore the container or remove it from the compose
file.

## How to use it

1. Paste a game URL in the **Game URL** form:
   - Lichess: `https://lichess.org/<id>` (works for any game id, public or yours).
   - Chess.com: `https://chess.com/game/live/<id>` (requires `CHESSCOM_USERNAME` set,
     since Caissa walks your monthly archive to find the game).
2. **Panel 1 — Repertoire deviation.**
   - Banner shows your first off-book move, or "You stayed in prep through move N".
   - The move list below colours your halfmoves green (in-book), red (deviation),
     grey (after). Click any move to jump the position viewer.
   - On deviation, a board renders the position you faced, with the moves your
     repertoire prepared listed next to it.
3. **Panel 2 — Engine evaluation.**
   - Click **Compute evaluations** to run `/eval` on every ply. Lichess
     Cloud Eval is tried first; positions Lichess doesn't know fall back
     to local Stockfish silently. The result is plotted from white's POV.
4. **Panel 3 — Strategic commentary.**
   - Gated on having computed evaluations.
   - Caissa auto-suggests "critical moments" (deviation + top eval drops
     against the user). You can untick or add halfmoves via the checkboxes.
   - Click **Explain selected positions** to call the LLM once per pick.
     Each result renders as a card: board, explanation paragraph, book
     citations, and which provider answered. Results are cached for the
     session.

## Strategic-commentary internals

- **Position classifier** (`src/advisor/classifier.py`): rule-based,
  pure-FEN → list of structural tags (`isolated_queen_pawn`,
  `opposite_side_castling`, `endgame_phase`, …). No LLM involved.
- **RAG corpus** (`data/corpus_seed.json`): hand-written placeholder of
  ~22 chess-strategy passages drawn from canonical English sources
  (Watson, Silman, Nimzowitsch, Dvoretsky, Aagaard, Karpov, Soltis).
  Auto-indexed into ChromaDB on API startup with `mtime`-based re-index.
  When real PDF extraction lands, swap in the same JSON schema and
  everything else keeps working.
- **Retrieval**: top-3 by cosine similarity of `(FEN + tags + best move)`
  through `bge-small-en-v1.5`. No similarity floor — the LLM is told to
  use what's relevant.
- **LLM**: OpenAI (default `gpt-5-mini`) via the OpenAI Python SDK.
  Runs the anti-hallucination cycle: initial call → SAN regex check → one
  retry with corrective hint → second violation raises.

## Project layout

```
src/
├── advisor/
│   ├── classifier.py        # FEN → structural tags (rule-based)
│   ├── corpus.py            # seed loader + ChromaDB indexer + embedders
│   ├── retrieval.py         # top-k similarity search
│   ├── llm.py               # OpenAI client + anti-hallucination retry
│   ├── critical_moments.py  # auto-pick deviation + eval-drop plies
│   └── pipeline.py          # /advise orchestration
├── api/
│   ├── main.py              # FastAPI routes + lifespan corpus refresh
│   └── game_fetcher.py      # Lichess + Chess.com single-game fetch
├── engine/
│   ├── lichess_eval.py      # Lichess Cloud Eval client
│   └── stockfish.py         # local UCI subprocess wrapper
├── repertoire/
│   ├── store.py             # SQLite schema, loader, queries
│   └── diff.py              # walk played game vs. repertoire
├── shared/
│   ├── chess_utils.py       # PGN parse, color extraction, time class
│   ├── schemas.py           # Pydantic models at all module boundaries
│   └── settings.py          # pydantic-settings over .env
└── ui/
    ├── streamlit_app.py
    └── components/
        ├── game_walker.py       # PGN → ply-by-ply views
        ├── repertoire_panel.py  # Panel 1
        └── explain_panel.py     # Panel 3
data/
├── repertoires/            # you drop white.pgn / black.pgn here
├── corpus_seed.json        # committed seed for the RAG
├── caissa.sqlite           # repertoire store (auto-created, gitignored)
└── chroma/                 # vector DB (auto-created, gitignored)
tests/                      # 210 tests, pytest + Streamlit AppTest
```

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness probe. |
| `POST` | `/game/fetch` | URL or pasted PGN → `GameMetadata`. |
| `POST` | `/repertoire/diff` | PGN + username → `DeviationReport`. |
| `POST` | `/eval` | FEN → cp/mate/best/pv. `source` ∈ `lichess_cloud`/`local_stockfish`/`any`. |
| `POST` | `/advise` | FEN + user_color (+ optional engine_analysis) → `AdviseResponse`. |
| `GET` | `/youtube_search` | Stub (deferred). |

Pydantic schemas live in `src/shared/schemas.py`.

## Development

```bash
uv run pytest                # 210 tests
uv run ruff check src tests
uv run ruff check --fix src tests
```

Streamlit UI tests use `streamlit.testing.v1.AppTest` and run headlessly
in CI.

## Operational notes

- **Cost.** A 200-word explanation costs roughly 0.3 ¢ on `gpt-5-mini`,
  and Panel 3 fires at most 4 calls per game. Less than 5 ¢ to analyse
  a full Sunday.
- **Privacy.** Everything runs locally. The only network calls are to
  Lichess (game fetch + cloud eval), HuggingFace (one-time embedder
  download), and OpenAI.
- **Secrets.** `.env` is gitignored. Rotate keys if you ever commit one
  by accident.

## Limitations

- Only single-PGN repertoires per colour. No multi-file libraries (yet).
- Two-process architecture (FastAPI + Streamlit) — won't deploy to
  Streamlit Community Cloud without first inlining the API calls.
