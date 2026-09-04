# M15 Split Financial-Risk Fixture

This fixture is intentionally vertically partitioned.

- Neo4j contains the resolved person, account ownership, company keys, and
  transfer facts. It contains no company risk classification or company name.
- Fuseki contains company keys, names, and risk classifications. It contains
  no person, account, or transfer facts.

The frozen query asks for transfers of at least USD 50,000 made by the exact
entity `person-alice-smith` on or after 2026-08-05 to companies classified as
`HIGH`. Neo4j returns candidates `C1` and `C2`; Fuseki returns high-risk
companies `C1` and `C3`; only the coordinator alignment and join can produce
the expected answer for `C1`.

This is a deterministic integration fixture, not a realistic financial-risk
benchmark and not evidence for ontology or ambiguity-resolution quality.
