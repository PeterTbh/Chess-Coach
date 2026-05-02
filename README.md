# Caissa — Personal Chess Improvement System

A local-only Streamlit app for solo post-mortem analysis. Paste a Lichess or
Chess.com game URL and get three stacked panels:

1. **Repertoire deviation** — first move you left your prep
2. **Engine evaluation** — Lichess Cloud Eval (fallback: local Stockfish)
3. **Strategic commentary** — RAG over a curated chess-book corpus, served by
   a fine-tuned Gemma 4 E4B with Anthropic API fallback

Python-only. Runs on localhost. For personal use.

See `CLAUDE.md` for architecture, modules, and current build phase.
