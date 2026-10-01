# INT-0: frozen real-input recovery and encoding diagnosis

2026-09-11. Parent implementation `e041bea1511d257a8eedfd43af9eab3eac605ede`.
This gate serves R-E/E1 answer integration and R-C/E2 same-meaning comparisons.
It is input preparation and a compiler-interface diagnostic, not a new benchmark
result, model interpretation score or successful backend execution.

## Completed work

The original GrailQA v1.0 archive was downloaded once (17,636,773 bytes) and its
SHA matched the frozen source manifest. All three question-source JSON hashes and
all five ontology files at the pinned upstream commit also matched. Each ontology
file had one download attempt; no failed external action was retried. Public source
provenance remains in `experiments/artifacts/grailqa_m13d_sources.json`.

`scripts/restore_grailqa_int_inputs.py` uses the original 150 IDs in their original
order, verifies sources, and reconstructs only these seven required files:

- inference questions;
- evaluation-only answers and official logical forms/SPARQL;
- evaluation-only reference interpretations;
- canonical logical plans;
- backend mapping and ontology.

**All seven match the original manifest's exact byte lengths and SHA-256 values.**
The derivation stage took 2.747 seconds, excluding source validation/loading.
It did not reselect questions, enumerate ambiguity candidates, build a catalog,
scan Freebase facts, call a model or execute a backend. The output is explicitly
a partial input recovery, not a complete DatasetBundle or a newly frozen pilot.
Existing frozen dataset files and manifests were not modified.

Verified public files are retained at
`/Users/anthonyche/xgap-data/int0-grailqa-public-20260911`; recovered pilot inputs
are at `/Users/anthonyche/xgap-data/int0-grailqa-pilot150-20260911`.
The [evidence receipt](../../experiments/artifacts/grailqa_int0_input_recovery_20260911.json)
contains source identities, reconstruction hashes and both diagnostic records.

## Two fixed real inputs: what worked and what did not

The diagnostic uses the **first two original pilot IDs**, selected before viewing
their outcomes. Both remain in the report and the formal denominator remains150.

| Question ID | Official gold count | Typed wrapper | Ordinary canonical Neo4j compile | Ordinary Fuseki compile | Actual answer |
|---|---:|---|---|---|---|
| 2100061004000 | 10 | Traverse → Project(position1) | succeeds, incompatible with existing mirror encoding | rejected: RDF edge identity missing | unmeasured |
| 2100063002000 | 1 | Traverse → Project(position1) | succeeds, incompatible with existing mirror encoding | rejected: RDF edge identity missing | unmeasured |

These wrappers are `evaluation_only_controlled_reference` inputs. They do not
simulate successful NL interpretation. The anchor is at the other endpoint;
using the older answer-position default `last` would return the wrong entity.
Gold answer counts are reference metadata, not observed correct answers.

The genuine missing implementation is the **data-encoding adapter to ordinary
Traverse**. The existing Freebase loader uses raw RDF and Neo4j
`XgapRdfResource.iri` / `XGAP_RDF_RESOURCE_EDGE.predicate`. Ordinary Neo4j
compilation expects canonical labels/types/properties, while ordinary Fuseki
PathSet compilation requires declared edge identities. Successful Cypher text
generation therefore does not establish compatibility with the loaded graph.
No such text was dispatched to a backend.

Existing Freebase fact export, backend loading, fixed-path compilation and typed
answer comparison code already exist. Missing locally verified fact snapshots,
load receipts and historical observations are artifact/evidence gaps; they are
not evidence that those modules are unimplemented. Catalog grounding is neither
a fact store nor a solution to this compiler-encoding mismatch.

The frozen reference also constrains the anchor's annotated type whereas the
official SPARQL constrains its MID. Equivalence is not yet established. Preserve
both references and test against independent facts; do not silently rewrite gold.

## FinBench and the next engineering gate

No frozen FinBench workpack was found in the specifically inspected local paths
or Git objects. The known remote freeze/population locations are retained as
**unverified candidate paths**, with original workload identity
`63a8ef36bc7576033db93caa2aa486409bc90ecfc699385b61e7d02be4320a5f`.
Restore that workpack rather than regenerate query parameters or use new samples.
Its existing hash/bind alternatives use different partitions, not equivalent
replicas; P1's replica placement guarantee cannot simply be asserted for them.

Next INT-1 implements the smallest explicit raw-RDF/mirror encoding adapter for
the existing fixed resource-path fragment. It must produce real PathSet node and
edge identities, preserve direction/duplicates/constraints/answer position, and
reuse ordinary planning and coordinator operations. Start with tiny graph cases;
do not reload a large graph, add an algebra operator or rerun accepted A1–A3 gates.
The two one-source inputs cannot demonstrate useful execution-prefix replanning
after their only source has finished.

Forecast preparation/cost provenance, independent real answers, model LINK and
frozen E1–E5 remain unfinished. Job3804011 has no newer confirmed state in this
gate; the earlier read-only status request remains pending.

## Validation boundary

The seven original hashes are the recovery oracle; two fixed real input compiler
diagnostics check the integration boundary. No software regression suite, native
service, model call, data evaluation or catalog build ran. Two initial local import
typos were corrected before their respective recovery/diagnostic executions; they
did not issue external calls. Independent read-only review found no substantive
recovery-script defect. INT-0 is complete; the overall research Goal is not.

Reproduce recovery into a **new** directory, with `PYTHONPATH=src`:

```sh
python scripts/restore_grailqa_int_inputs.py \
  --dataset-root /Users/anthonyche/xgap-data/int0-grailqa-public-20260911/GrailQA_v1.0 \
  --ontology-root /Users/anthonyche/xgap-data/int0-grailqa-public-20260911/ontology \
  --output /path/to/a/new/int0-input-directory
```

Do not repeat an already verified recovery without a concrete artifact change.
