## Feature 1: Repertoire-Abweichungs-Analyse

Das zerfällt in **drei Sub-Features**, weil du verschiedene Datenflüsse vermischst. Ich trenne sie sauber.

### Feature 1.1 — Repertoire-Setup (einmalig, vom Nutzer)

**Input:**

- PGN-Datei `white.pgn` (Repertoire mit Weiß, kann Variantenbaum enthalten)
- PGN-Datei `black.pgn` (Repertoire mit Schwarz, kann Variantenbaum enthalten)
- Lichess-Username **oder** [Chess.com](http://Chess.com)-Username des Spielers

**Verarbeitung:**

- PGN-Files werden mit `python-chess` als Variantenbäume in SQLite indexiert
- Pro Zug wird die FEN nach dem Zug gespeichert: `(repertoire_id, ply, fen_after_move, san_move, parent_node_id, color)`
- Username wird in `.env` oder Config gespeichert für spätere Game-Fetches

**Output:**

- Bestätigung: "White repertoire loaded: N positions across M variations"
- Bestätigung: "Black repertoire loaded: N positions across M variations"
- SQLite-Tabelle `repertoire_nodes` befüllt

**Acceptance-Kriterium:**

- Eine bekannte FEN aus dem Repertoire wird per `SELECT * WHERE fen_after_move = ?` gefunden
- Die zugehörige SAN-Sequenz lässt sich rekonstruieren

### Feature 1.2 — Spiel-Analyse mit Repertoire-Abgleich

**Input:**

- Lichess- oder [Chess.com](http://Chess.com)-Game-URL **oder** PGN-String

**Verarbeitung:**

1. Game-Fetcher holt das PGN über die jeweilige API
2. PGN-Header wird gelesen: `[White "..."]` und `[Black "..."]` bestimmen die Farbe des Nutzers (gegen seinen gespeicherten Username)
3. Je nach Farbe wird `white.pgn` oder `black.pgn` als Vergleichs-Repertoire geladen
4. Zug-für-Zug-Walk:
   - Für jeden Halbzug des Spielers (also nur die Züge des Nutzers, nicht des Gegners) wird die FEN nach dem Zug berechnet
   - Diese FEN wird in `repertoire_nodes` gesucht
   - Sobald die FEN **nicht** gefunden wird → Abweichung erkannt
   - Der **letzte gefundene Repertoire-Knoten** wird als Referenz behalten

**Output:** ein JSON-Objekt mit dieser exakten Struktur:

```json
{
  "game_id": "abc123",
  "user_color": "white",
  "in_book_until_ply": 14,
  "deviation": {
    "occurred": true,
    "deviation_ply": 15,
    "deviation_move_number": 8,
    "move_played_san": "Bd2",
    "move_played_uci": "c1d2",
    "fen_before_deviation": "rnbqkb1r/pp2pppp/2p2n2/3p4/2PP4/2N2N2/PP2PPPP/R1BQKB1R w KQkq - 0 5",
    "expected_moves_from_repertoire": [
      {"san": "Qc2", "uci": "d1c2", "line_name": "Catalan main line"},
      {"san": "Nc3", "uci": "b1c3", "line_name": "Open variation"}
    ],
    "deepest_repertoire_match_node_id": 247
  },
  "moves_in_book": [
    {"ply": 1, "san": "d4", "user_color": "white"},
    {"ply": 3, "san": "c4", "user_color": "white"},
    {"ply": 5, "san": "Nf3", "user_color": "white"}
  ]
}
```

**Acceptance-Kriterium:**

- Test-Case: ein bekanntes Lichess-Spiel mit bekannter Abweichung auf Zug 8 → System gibt `deviation_move_number: 8` zurück
- Test-Case: ein Spiel, das komplett im Buch bleibt → `deviation.occurred: false`, `in_book_until_ply: <letzter Spieler-Halbzug>`
- Test-Case: Sofort-Abweichung auf Zug 1 → `deviation_ply: 1`

### Feature 1.3 — Streamlit-Visualisierung der Abweichung

**Input:**

- Das JSON-Objekt aus Feature 1.2

**Output (im Streamlit-UI):**

- **Header**: "You deviated from your `[user_color]` repertoire on move `[deviation_move_number]`"
- **Schachbrett-Anzeige**: Die Stellung `fen_before_deviation` wird gerendert (chessboard.js HTML-Embed)
- **Tabelle**: "You played: `Bd2`" / "Your repertoire plays: `Qc2` (Catalan main line)" oder mehrere Repertoire-Alternativen falls vorhanden
- **Zug-Liste links**: alle Spieler-Halbzüge des Spiels, die Züge **im Buch** in Grün, der **Abweichungszug** in Rot, alles danach in Grau
- **Klick auf einen Zug in der Liste**: setzt das Schachbrett auf die FEN dieses Halbzugs (für späteres Zusammenspiel mit Feature 2)

**Acceptance-Kriterium:**

- UI rendert ohne Errors bei einem Deviation-Spiel
- UI rendert ohne Errors bei einem "fully in book"-Spiel mit alternativer Nachricht: "You stayed in prep through move N"

  ---

  ## Feature 2: Verbalisierung der Stockfish-Analyse

  ### Feature 2 — Strategische Erklärung einer Stellung

  **Input:** ein JSON-Objekt dieser Struktur:

  ```json
  {
    "fen": "rnbqkb1r/pp2pppp/2p2n2/3p4/2PP4/2N2N2/PP2PPPP/R1BQKB1R w KQkq - 0 5",
    "engine_analysis": {
      "eval_cp": 24,
      "best_move_uci": "c1f4",
      "best_move_san": "Bf4",
      "pv": ["c1f4", "f8e7", "e2e3", "e8g8"],
      "depth": 22
    },
    "user_color": "white",
    "game_phase_hint": "opening"
  }
  ```

  **Verarbeitung:**
  1. **Position Classifier** (rule-basiert, ohne LLM):

     - Bauernstruktur-Erkennung: IQP, hängende Bauern, Carlsbad, Karlsbad, Kettenstruktur, offene/halboffene Linien
     - Material-Imbalance: Läuferpaar, Qualität, Bauern-Differenz
     - Phasen-Bestimmung: Eröffnung (≤Zug 12), Mittelspiel, Endspiel (≤14 Material)
     - König-Position: rochiert kurz, rochiert lang, im Zentrum
     - Output: Liste von strategischen Tags, z.B. `["isolated_queen_pawn", "white_to_move", "minor_pieces_developed", "open_c_file"]`

  2. **RAG-Retrieval**:

     - Embedding der Eingabe (FEN + Tags + Engine-Move) via `bge-small-en-v1.5`
     - Top-3 ähnlichste (FEN, Kommentar)-Paare aus ChromaDB werden geholt
     - Jeder Treffer hat: Buch-Quelle, Seite, \~300 Zeichen Kontext

  3. **LLM-Call** (Gemma fine-tuned oder Anthropic-Fallback):

     - System-Prompt fixiert die Persona: "You are a chess analyst writing in neutral analytical English for a 1500-2000 ELO club player. Explain only what the engine evaluation and the retrieved book passages support. Do not invent moves or evaluations."
     - User-Prompt enthält: FEN, Tags, Engine-Output, die 3 retrieveten Buch-Passagen
     - Antwort wird als zusammenhängender Text in \~150-250 Wörtern generiert

  **Output:** ein JSON-Objekt dieser exakten Struktur:

  ```json
  {
    "fen": "rnbqkb1r/pp2pppp/2p2n2/3p4/2PP4/2N2N2/PP2PPPP/R1BQKB1R w KQkq - 0 5",
    "explanation": "This is a Catalan structure with white retaining the bishop pair option. The long diagonal a1-h8 is white's primary strategic asset; the typical plan involves Qc2 to support c-file pressure and prepare a future cxd5 break that opens lines for the fianchettoed bishop. Black's d5-pawn is well-supported but somewhat passive. Watson describes this exact structure as 'one where white's plans are slow but durable.' The engine's preferred Bf4 reinforces the principle of completing development before commiting to a structural break.",
    "classifier_tags": [
      "catalan_structure",
      "opening_phase",
      "long_diagonal_pressure",
      "central_pawn_chain_d4_c4",
      "minor_pieces_developed",
      "white_to_move"
    ],
    "citations": [
      {
        "source": "Watson - Mastering the Chess Openings vol. 1",
        "page": 142,
        "snippet": "The Catalan offers white a slow but durable initiative based on the long diagonal..."
      },
      {
        "source": "Avrukh - GM Repertoire 1A",
        "page": 87,
        "snippet": "After the standard development moves, the question of when to play c4xd5 becomes central..."
      }
    ],
    "model_used": "gemma_local",
    "engine_input_echo": {
      "eval_cp": 24,
      "best_move_san": "Bf4"
    }
  }
  ```

  **Acceptance-Kriterium:**
  - Output enthält **mindestens eine** Zitat-Quelle aus dem Buch-Korpus
  - Output erwähnt **mindestens einen** strategischen Begriff aus `classifier_tags`
  - Output erfindet **keinen** Zug, der nicht im Engine-Input vorkommt (verifizierbar durch Regex-Check auf Zug-Notation gegen `pv` und `best_move_san`)
  - Wortzahl zwischen 100 und 350
  - Sprache: Englisch
  - Ton: neutral analytisch (Verifikation manuell beim Spot-Check)

  ---

  ## Wichtig: Was hier noch fehlt für sauberen Scope

  Drei Lücken, die du noch klären musst, bevor Claude Code Feature 2 baut:

  **1. Was, wenn das Korpus für eine Position keine relevanten Treffer hat?**
  - Option C: Fallback-Text "No specific book reference matches this exact structure"

  **2. Wann triggert Feature 2?**
  - Manuell: User klickt einen "Explain" Button

  **3. Engine-Quelle für Feature 2:**
  - Lichess Cloud Eval API (gratis, ratelimited, hat nicht jede Stellung gecacht)