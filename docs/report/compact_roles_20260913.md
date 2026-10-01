# Named entities, business IDs and ordinary variables — 2026-09-13

Prompt revision4509c15 passed three new ordinary-NL requests on the frozen
eight-node/sixteen-edge Neo4j/Fuseki graph. Every request made one actual model
call, selected one estimated plan and returned the independent exact answer.
This is a tiny integration result, not held-out effectiveness or a speedup claim.

| Request kind | Mode | Grounding lookups | Model input/output tokens | Source calls | Complete online s | Answer |
|---|---|---:|---|---:|---:|---|
|Named Alice → owned accounts|precision|1|2102 /180|3|2.341|account1, exact|
|Person business ID1 → direct transfer totals|performance|0|2202 /548|10|3.524|account2=66, account3=9; exact|
|Generic blocked-account variable|precision|0|2100 /167|3|1.451|accounts2,3,4; exact|

The model emitted the expected named mention only for Alice; business-ID and
generic cases had no entity holes. Three independent focused checks passed
first attempt in0.35s, proving the child profile changes prompt/identity metadata
only, explicit ID predicates survive lowering, and unresolved required mentions
still fail. The compiler, grounding rules, estimator, policy budgets and baseline
engines were not modified. V1 prompt/profile files and old scores remain intact.

The new prompt distinguishes a variable name, a declared type and an optional
proper-name mention. Literal business IDs remain typed property predicates.
It restates the existing path/deduplication boundary; no response is repaired,
required constraint dropped or canonical identity guessed after a failure.
See [decision and bounds](../decisions/compact_entity_roles_v2.md).

The three live calls used qwen3.8-27b,6404 input/895 output tokens in total,
and16 source requests. There were no data loads, catalog builds, fits, probes,
baseline calls or retries. Controller49874 exited0; all owned processes and the
observer are terminal. [Pinned evidence](../../experiments/artifacts/compact_roles_20260913.json)
and [CSV](../../experiments/artifacts/compact_roles_20260913.csv). Raw receipt:
`/Users/anthonyche/xgap-data/compact-roles-native-20260913-v2/receipt.json`, SHA
`fa2a669525c135fa006c09925d2be83f81a909ac6205d3465c59420082309af4`.

Native/RDF full profiles were derived offline under
`/Users/anthonyche/xgap-data/finbench-compact-roles-v2-20260913`. No source/schema,
catalog, estimator, model settings or policies changed. Read-only association
receipts point to the original frozen stores and FedUP summary with explicit
parent provenance; old offline costs/counts are inherited, not new load work.
The new RDF NL journal carries eight previous outcomes by reference and starts
with the previously unrun group2. All48 groups and the same method order remain;
v1 failures and v2 attempts must not be silently reported as homogeneous v2 data.
Native NL remains unstarted. The subsequent real evaluation is recorded separately.
