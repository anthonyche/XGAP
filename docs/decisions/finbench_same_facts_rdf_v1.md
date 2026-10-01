# FinBench same-facts representation contract

Scope: ordinary XGAP financial input and the user-approved matched-RDF evaluation
track. Baselines are runnable and frozen; their wrong/unsupported results are not
repair tasks. This step does not alter the existing population or run SF0.1.

RQ addressed: can different execution environments receive the same financial
facts and query meaning, so later quality/cost differences are interpretable?
The current X-factor is representation (native property graph / RDF edge resources),
with exact answers, identity/multiplicity preservation and provenance as outcomes.
This is an engineering gate, not an efficiency or effectiveness experiment.

Allowed files are the FinBench representation adapter, explicit offline/tiny
scripts, new fixture checks and current evidence documents. The semantic core,
external methods, historical native partition, gold and evaluation populations
remain unchanged. Acceptance: same native scalar properties, injective identity,
parallel-edge preservation, canonical queries without source assignments, and
independent tiny answers for all three agreed financial families.

## Encoding and offline boundary

The input is the already verified `m15-finbench-source-partition-v2` JSONL/control
bundle. Each native batch and the partition files are hash checked. A new output
directory contains an identity-augmented native load, structural RDF, control RDF,
compiler mapping and a manifest. Original files are never changed.

Native node `xgap_id` is `entity_type + '_' + hex(UTF8(source_id))`; relationship
`xgap_id` is `edge_ + original_sourceKey`. Each relationship has its own resource,
class, source, target, label, source key and attributes. Parallel transfers are not
collapsed. The original source ID remains a property for output/query parameters.
Both RDF sources use the corresponding global IRI in the one-shot namespace.
Control attributes remain on their original source; source identity is replicated.
These technical identities are representation metadata, not new financial facts.

The RDF graph preserves the native partition's decoded scalar values. Integers
remain integers; existing floats become xsd:double with round-trippable lexical
values. Control booleans stay booleans; timestamps remain original strings.
This does not claim that native floats reproduce every raw CSV decimal exactly.
Full-evaluation numeric equivalence/rounding remains an explicit protocol check.

Preparation is O(input bytes + emitted bytes) time plus hash-table operations,
O(number of entity/edge identities) memory. It performs no search, model call,
backend call, answer read or cost measurement. It is invoked explicitly offline,
then frozen; runtime cannot start this materializer.

## Public fixed-semantics queries

The query generator consumes family + public parameters. It produces standard
SPARQL without SERVICE/source assignments and is independent of every baseline.
It is a fixed-semantics/gold interface, not a replacement for NL interpretation.

- Direct transfer/control: inclusive timestamps; blocked destination; company and
  account totals; preserve distinct transfer occurrences.
- Temporal path/control: one to three transfers; strictly increasing timestamps;
  no repeated accounts; blocked medium. Finite UNION of the three lengths retains
  the agreed semantics and DISTINCT projected answers.
- Risk ranking: closed/open timestamps; exact risk label; an account qualifies
  once even if several media match; sum incoming transfers by company, then sort
  total descending and company ascending before top K.

Output normalization keeps ordering and multiplicity. Only declared amount and
distance fields receive their prescribed numeric representation. The original
baseline output is not repaired or optimized.

## Remaining ordinary-core integration

`Match` currently exposes node properties; `Traverse` returns path identities;
`Project` supports field/path-node/path-edge/path-length, but not edge attributes.
Row comparisons currently use a scalar constant and numeric ordering, not another
field or a timestamp comparison. Thus the old prepared FinBench native templates
do not yet demonstrate that these three programs can be interpreted and planned
through the generic one-shot entry.

Next implement the bounded financial requirements through the existing semantic
layers: edge-property access and explicit field/timestamp comparisons, then three
gold semantic programs through ordinary deterministic planning/execution. Preserve
the ≤3-hop scope and polynomial planner; do not hide a family-specific template
dispatcher in NL inference or declare these queries supported before that gate.
This extends the ordinary core where the approved financial experiment needs it;
it is not baseline development or universal semantic expansion.
