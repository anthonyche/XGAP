# Full-snapshot FinBench serving inputs

Authority: approved FinBench/native plus matched-RDF experiment preparation;
the user's pause expired at2026-09-13 12:00 Asia/Shanghai and work resumed12:08.

RQ contribution: a common source snapshot, ordinary input schema and frozen
statistics make answer-quality/online-cost comparisons interpretable. This
milestone does not change the planner, baseline algorithms or120 query groups.
It is prerequisite engineering, not a new ablation or performance result.

Allowed: offline serving publisher, exact artifact checks, four focused tiny
checks, one actual source-only publication and evidence. No evaluation answer or
method output reads, model/engine calls, training, accepted-gate reruns or native
campaign. On failure keep partial files and the error; do not automatically retry.

All18 source tables stay represented. Native graph and matched RDF preserve
injective xgap_id identities, edge identity/multiplicity, properties and the
existing graph/control split. Large load files use streaming SHA checks; the
16-MiB runtime metadata/catalog boundary is unchanged. Mapping/query semantics
remain those of the already accepted same-facts representation.

The catalog covers all source entities with typed business IDs, bare ID aliases
and observed names, all source schema terms, and observed control categories.
No entry is authoritative. Bare IDs/names may refer to several entity types;
ambiguity is retained. Numeric amounts/timestamps do not generate catalog entries;
they remain typed query literals. This is a declared grounding vocabulary, not
removal of facts or an answer-selected subgraph. No query anchors drive inclusion.
Canonical artifact order resolves ties under the existing one-shot policy; it is
not a trained ranking or accuracy guarantee.

New frozen statistics identify the exact serving source bytes. Graph work rows
are all entities plus relationships; width is mean compact load-row JSON bytes.
Control work rows are entities; width is total serialized triples per entity.
These are explicit source-work proxies, not result cardinalities, wire bytes or
backend storage sizes. Keep their provenance and raw counts. The original32-sample
tiny model is embedded unchanged through FrozenWorkDeployment; transfer is
uncalibrated and no collection/fit occurs. Later dataset training, if used, stays
within the separate frozen training group and protocol.

Success: actual complete source counts/hashes, every entity addressable in the
catalog, control identity coverage, no query/gold reads, unchanged trained model,
new source identities and both mode configs accepted by FrozenOneShotProfile.
One tiny compiler/estimator boundary verifies the new deployment metadata without
executing a plan. No repeat of old native/LLM correctness gates is needed here.

Formal campaign readiness stays false: services have not loaded these facts,
the full same-facts external adapter and common scoring integration, resource
watchdog and method budgets are separate remaining gates. Do not claim actual
SF0.1 one-shot query success or ranking/latency benefits from file publication.

## Pre-publication evidence

Existing materializer completed one actualSF0.1 action at35d9449 in7146.473ms:
55,604 entities,309,577 relationships, all18 tables; zero model/backend/query/answer
actions. Output root /Users/anthonyche/xgap-data/finbench-sf01-serving-20260913-v1/rdf.

Four new publisher risks are now accepted. The first test collection caught an
extra closing brace (no tests executed); after correction3 tests passed0.36s and
the catalog test exposed missing required request-constructor fields in the test.
Only that test was corrected/rerun and passed0.24s. No baseline, native request,
model, training or old test was rerun. Actual profile publication remains next.

First actual profile attempt at516fbb4 stopped before catalog publication with
KeyError loan: the reused tiny schema helper lacked the fifth entity's plural
alias. Source materialization was unchanged. This is our schema-helper defect,
not a dataset or baseline limitation. The exact failure is retained in
experiments/artifacts/finbench_serving_first_attempt_20260913.json. A minimal
all-five-type/thirteen-relation metadata replay passes0.22s after adding loans;
no prior passing checks repeated. A new output version is the next action.
