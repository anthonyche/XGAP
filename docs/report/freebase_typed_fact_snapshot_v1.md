# D201: typed Freebase facts for executable answers

Status: **LOCAL SOFTWARE AND ONE-SHARD DATA ACCEPTANCE COMPLETE**.
This is the fact-data step of H4, not a new catalog
intervention. The fixed-v1 inline18 operator package remains pending server-side
execution; do not resubmit or reinterpret historical model runs.

## Goal and frozen scope

Read all six columns of explicitly selected, source-manifest-bound archival
Parquet shards and export their RDF facts without the catalog adapter's
predicate/language restriction. Preserve resource versus literal identity,
lexical values, datatype and language. Stream reusable N-Triples parts under
explicit finite input, row and output budgets. An exceeded budget, malformed
row, changed source or unsupported term stops the build with partial output
preserved; no truncated snapshot is labeled complete.

Selection is an explicit shard list or all shards in the supplied source
manifest. There is no question, reference, gold answer, model prediction,
entity-candidate list or hop expansion input. A partial shard selection is
described as partial; even all supplied-manifest shards do not by themselves
establish completeness relative to the original Freebase release. Duplicate
fact occurrences may be serialized; RDF graph set semantics deduplicate them
at load time. Recorded counts are occurrence counts, not distinct graph sizes.

Allowed: new `freebase_facts.py` and `freebase_fact_snapshot.py` experiment/data
adapters, their tests, a runnable example and documentation. Reuse the existing
RDF term/answer contracts, directed compiler and backend client/loader interfaces.
Forbidden: changing the historical catalog adapter or frozen inference inputs,
new algebra operators, gold-derived fact selection, silent skipping/coercion,
automatic external retries, or claims of a new real-backend/model measurement.

## Acceptance

1. Actual Parquet data retains ordinary and typed numeric/date literals, language
   literals, arbitrary legal IRI objects and all predicates, with row provenance.
2. Fresh chunked N-Triples artifacts reproduce the input RDF terms through an
   independent RDF parser. Complete selected shards are consumed, input hashes
   and byte counts are checked, and budgets/errors cannot produce false success.
3. Exported parts pass through the existing HTTP loading/client boundary and an
   actual independent SPARQL engine. XGAP's emitted directed query combines an
   entity anchor, graph relations and numeric-year filtering and returns exact
   typed answers; a nearby negative case returns a successful empty answer.
4. Focused tests, full offline regression, harness and 19 examples pass. The
   new example reports its fixture scope explicitly and makes no network call.

This does not complete H4 or the system objective. Real Neo4j/Fuseki loading,
dataset-owned property-graph encoding and cross-backend plans for the actual
inference candidates remain required. RDF data is not silently coerced into
Neo4j scalar properties: multi-valued predicates, literal datatypes and resource
identities need an explicit dataset mapping at that next boundary. No full-source
scan is launched merely to test this implementation.

## Implementation and observed results

The two new modules and runnable offline demo are implemented. The 52 new
tests include real Parquet, chunked N-Triples parsed by RDFLib, input mutation,
budget exhaustion, preserved failures and an HTTP loading/query integration.
The latter executes XGAP's emitted directed query over a synthetic institution,
author and paper graph with integer-year filtering. The correct paper is
returned; old years, another institution and an untyped string-year decoy are
excluded. The nearby empty-answer case is a successful empty result. Focused
regression is **203 passed, 1 explicitly live-gated skip in 4.47s**. Full
regression completed in its original session with **2752 passed, 37 skipped
in 609.22s**. The harness, all 19 acceptance examples and the new offline demo
pass. No production source changed after these runs.

A separate actual-data experiment selected `default/data/0000.parquet`, the
first frozen inventory entry, before examining data and without question or
reference inputs. The 14,984,726-byte download matches frozen SHA-256
`f1b21a5869da41938818a3f0f2ef2ead92fd5df978c2d5bf6fbaad31d3f650b1`.
All **3,247,670 rows** of its five row groups were consumed into **13 N-Triples
parts, 420,940,219 bytes**. Export took **98.57 seconds**, with **125,272,064
bytes** peak process RSS on this Mac. Download and verification are separate
costs; this is one construction observation, not a controlled speed comparison.

| Object term category | Occurrences |
|---|---:|
| URI resource | 541,677 |
| Language literal (`rdf:langString`) | 2,603,948 |
| Ordinary/string literal (`xsd:string`) | 91,515 |
| `xsd:date` | 1,681 |
| `xsd:gYear` | 6,089 |
| `xsd:gYearMonth` | 2,760 |

An independent check reads the original six Arrow columns and parses every
output part through RDFLib's streaming N-Triples parser. With lexical
normalization disabled, all counts, part byte/hash checks and the complete
ordered RDF-term stream agree at digest
`96aca67e31c1254387580000abfd21ef5dd163b84553f3eb6e04dfe9c4c66c78`.
It preserves duplicate occurrences and distinguishes URI, lexical value,
datatype and language; it does not estimate unique RDF graph size.

The initial ad-hoc verifier parsed all parts but failed its final digest
because it classified RDFLib language literals' absent `.datatype` attribute
as xsd:string. Diagnosis on the first actual language literal showed that its
value/language and exported text agreed; its RDF datatype is implicitly
rdf:langString. A separately retained v2 verifier applies that representation
rule and passes. No production code, source or exported fact was changed or
re-exported. The original failed verifier/log remain alongside the correction.

This actual shard experiment validates data conversion, not GrailQA answers.
The compiled answer test uses a synthetic integer-year fixture. The real
date/gYear/gYearMonth values are preserved; their comparison semantics and
Neo4j/Fuseki dataset mappings remain part of H4. This one-of-964 selection is
not claimed representative or complete. No real backend or model was called.

The durable acceptance/observation receipt is
`experiments/artifacts/d201_typed_fact_snapshot_20260910.json`. Actual source,
parts, plans, the failed and corrected verification scripts, and raw receipts
remain at
`/private/var/folders/78/2hb19nqj0jv_l0vgmp084ht80000gn/T/xgap-d201-source-b2ymubis`.
The compact repository receipt is not a copy of the 421 MB fact data.

## Run the implemented path

Offline synthetic fact-to-answer example:

```bash
PYTHONPATH=src python examples/freebase_typed_fact_demo.py
```

For real source data, use `python -m xgap.experiments.freebase_fact_snapshot`
with explicit `--parquet-root`, `--source-manifest-path`,
`--expected-manifest-sha256`, fresh `--output-root`, `--max-input-bytes`,
`--max-output-bytes`, and `--max-rows`. Optional repeatable `--shard` chooses
complete manifest entries; omission selects all entries. `--part-bytes` and
`--batch-size` control chunking, not query selection. This requires the existing
optional `parquet` dependency, while the example additionally uses `test-sparql`.
Reuse completed facts for subsequent queries instead of rebuilding them.
