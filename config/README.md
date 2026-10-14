# config/

Versioned configuration **data**, not code. Examples: the model catalogue and equivalence groups, price tables with source and check date, the logged-label mapping, application defaults (strategy selection, thresholds), and baseline definitions.

- **No secrets, ever.** Secrets come from the environment or an untracked `.env` (Stage 6).
- Experiment configs live with their experiment and only override these defaults.
- Production defaults may name only promoted components.
- File format and precedence are decided in Stage 6; the catalogue and price schema in Stage 7.

Rules: [repository_structure.md §5](../docs/architecture/repository_structure.md#5-configuration-files-config).
