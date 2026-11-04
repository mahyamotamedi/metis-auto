## Demo settings discoverability and usable RAG (2026-11-05)

- Moved Advanced to the top of the chat sidebar, initially expanded, without
  enabling live calls. Optimization controls also precede the long bot list.
- Consolidated synthetic samples to one Persian and one English dedup example;
  original preset definitions remain available for diagnostics.
- Based RAG availability on nonblank stored chunks from logged AI turns, rather
  than corpus configuration. The demo loads the latest usable logged chunk set
  and hides real bots without usable RAG; no source records were deleted.
- Preserved existing bot labels and appended newly discoverable RAG-only bots.
  A read-only database count found 179 usable-RAG bots among 592 eligible bots,
  including six with observed RAG despite missing corpus configuration.
- Updated quickstart, UI explanation and module reference; recorded
  ADR-XXXX (demo-discoverability-and-usable-rag) as a draft.
- Validation: 261 targeted UI, wiring and architecture tests passed; five
  PostgreSQL integration tests passed against synthetic throwaway data. Ruff
  lint, formatting and diff whitespace checks passed. Visually verified Advanced
  first, two samples, and the paged Metis list showing 50 of 179 bots.
- Updated demo runs at http://localhost:8502; the existing port 8501 process was
  left untouched. No paid calls were made by the assistant. Recorded RAG is fixed
  context, not question-dependent retrieval. Changes remain uncommitted.
