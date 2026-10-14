# ADR-0004: Repository hygiene — IDE files untracked, agent conventions tracked, brief and master prompt committed

- Status: **decided**
- Date: 2026-10-14
- Resolves: Q-01, Q-02, Q-03

## Context
`.gitignore` on `main` listed `.idea/`, `.vscode/`, `AGENTS.md`, and `docs/agents/`, yet all of them were tracked. As a result, new files under `docs/agents/` were silently ignored. The project brief lived outside the repo, and the master prompt was saved with a stray `_1` suffix.

## Decision
1. **`.idea/` and `.vscode/` are not tracked.** They were removed from the index (`git rm --cached`; the local files are kept) and stay in `.gitignore`. Editor settings are per developer.
2. **`AGENTS.md` and `docs/agents/` are tracked.** Their lines were removed from `.gitignore`. `AGENTS.md` stays at the repo root. Where the `docs/agents/` content should live is part of the Stage 2 structure proposal; it is not moved yet.
3. **The project brief is committed at `docs/brief/project-draft.pdf`.** It is a byte-identical copy of the original, sha256 `5f2e5132e38906990cc22a10ab0e8ac83440ac8b7140b52d12695c4f072b5322`. It goes under `docs/` because it is an input to the design docs; it is not code or data. Its folder name allows later brief revisions next to it.
4. **The master prompt is renamed to `metis_claude_code_master_prompt.md`** (root) and committed. Whether it moves is also left to Stage 2.

## Alternatives considered
- **Brief under `data/`.** Rejected: it is not dataset material, and `data/` has read-only semantics.
- **Keep IDE configs tracked for shared settings.** Rejected by the user. They also encoded black, which ADR-0001 replaces with ruff.

## Consequences
- In this clone the files stay on disk. **Collaborators who pull this commit will have the previously tracked `.idea/` and `.vscode/` files deleted from their working tree** by git. They should copy them aside before pulling, or re-create them afterwards. After that, the files stay ignored.
- The brief PDF is tracked in git (319 KB). That is acceptable at this size.
