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

`expected_source_results.json` freezes each native query's rows independently,
while `expected_result.json` freezes the projected coordinator answer. This
prevents a nonempty-but-wrong source load from satisfying the live gate.

This is a deterministic integration fixture, not a realistic financial-risk
benchmark and not evidence for ontology or ambiguity-resolution quality.

The deployment-neutral loader is gated to avoid accidental writes:

```bash
XGAP_LOAD_M15_FIXTURE=1 \
python -m xgap.experiments.m15_fixture_loader --run-id <unique-run-id>
```

It appends only namespaced, idempotent facts, verifies each backend against the
frozen source rows, persists a new run directory, and never retries. Run it
only after both endpoint variables refer to dedicated M15 services.
