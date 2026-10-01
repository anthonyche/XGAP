# Repository instructions

Keep this repository focused on the XGAP implementation, runnable examples,
regression tests, and necessary configuration. Read README.md and docs/architecture.md
before changing system behavior.

## Implementation invariants

- Preserve typed algebra, compiler semantics, hard query constraints, and canonical identities.
- Model proposals and catalogs do not certify intent; use the declared authority tool.
- Mandatory validations are independent of candidate uniqueness and zero discrepancy.
- Keep fixed-depth online lookahead and checked local physical transformations.
- Preserve completion reservations for all outcomes; unknown resource bounds are not zero.
- Execute at most one final plan per request; meter actual actions separately from hypothetical search.
- Keep legacy method identities distinct from the current controller.
- Preserve failed attempts and raw evidence outside the repository. Never fabricate measurements.
- Do not submit or resume experiments unless explicitly authorized.

## Repository hygiene

- Do not commit development reports, work logs, agent histories, run receipts,
  result tables, generated datasets, debugging dumps, handoff archives, or credentials.
- Store local evidence and operational notes outside this checkout.
- Retain minimal synthetic fixtures needed to reproduce implementation regressions.
- Use environment references for credentials; never hard-code secrets.
- Run `make acceptance` for release changes. Backend integration requires explicit configuration.
- Preserve existing remote history; do not force-push or delete remote branches without authorization.
