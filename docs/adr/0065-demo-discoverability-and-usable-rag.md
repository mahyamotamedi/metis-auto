# ADR-0065: Put mode controls first and list bots with usable stored RAG

- Status: **draft**, implementing the owner's demo corrections of 2026-11-05.
- Date: 2026-11-05
- Relates to: ADR-0054, ADR-0056, ADR-0066; UI-A01, UI-A33, UI-R03, FR-FIN-02.

## Context

The owner could not find Live/Fake controls beneath the long bot list, saw two
samples per language, and asked to include the dataset bots' RAG or remove bots
without it from the demo. A configuration snapshot alone is insufficient evidence
of usable retrieved context: a configured corpus may have no stored chunks, and
logged chunks may exist without a configured corpus.

## Decision

1. In a chat workspace, render Advanced first in the sidebar, initially expanded,
   before optimization switches, conversations, and the bot list. No default live
   permission or mode is changed.
2. When an original sample and its `_dupes` variant both exist, show the dedup
   sample only. This keeps one Persian and one English sample while retaining
   duplicate-chunk context for the three-stage demo. Original preset definitions
   remain available for diagnostics and historical measurements.
3. **Amends ADR-0056 points 2 and 3 for the current demo list:** determine usable
   RAG from the existence of nonblank chunk text on a logged AI turn, not from
   `corpus_ids_state`. Show only real-bot cards with usable stored RAG. Do not
   delete source records or saved conversations.
4. Keep Option A: load the latest logged AI turn with usable chunks and send
   its nonblank passages in logged order. This is fixed recorded context, not a
   new question-dependent retriever and not a recovery of an unexported corpus.
5. Preserve existing traffic labels when hiding cards. Bots newly discoverable
   solely from observed RAG follow the original directory so existing bot labels
   do not silently refer to another bot's saved conversation.

## Alternatives and consequences

- Deleting dataset bots would destroy unrelated source data; rejected.
- Using the configured-corpus flag would retain empty-context bots and miss
  observed RAG; rejected. A content-free existence query precedes lazy text reads.
- A full retrieval/search service would change the approved Option A scope; not
  implemented. Logged passages may not match every newly typed question.
- The UI's stored workspace is initialized once. Restart the demo and open a new
  browser session to reload imported code and rebuild its directory.
- Tests use synthetic source rows and a throwaway PostgreSQL database. No paid
  call, production data modification, budget change, or approval change occurs.

## Follow-up: warning presentation and context integrity (2026-11-05)

- At the owner's request, remove the persistent Live-ON and LLMLingua warning
  banners. Keep the header's mode chip, experimental control label, permission
  checks, failed-setting errors, budget enforcement and blocked/stopped banners.
  This changes presentation, not the safety gates or compression's quality status.
- The Persian dedup preset must preserve the original shop's instructions and
  full knowledge verbatim, with repetition as its only content difference.
  Its earlier abbreviated documents changed delivery/payment policies and
  omitted shipping prices. Original preset definitions stay unchanged.
- Correct the implementation of the sprint-winners draft's dedup-before-
  compression order: `reduce` transforms the source chunks once; `build` lays
  out the prepared request without deduplicating again. Distinct chunks may
  compress to identical text; removing them after counting corrupts the trace.
  No new retrieval or quality claim is introduced.
- RAG SQL must exclude tab/newline-only chunks as well as space-only chunks,
  both when identifying usable bots and when choosing their latest usable turn.
