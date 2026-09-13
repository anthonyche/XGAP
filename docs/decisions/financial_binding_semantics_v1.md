# Financial binding profile: edge Match and explicit time comparison

The timestamp lexical boundary below is superseded by
[calendar millisecond v2](financial_timestamp_v2.md): zero to three fractional
digits, padded only for comparisons. Historical v1 artifacts/scores stay intact.

2026-09-12. Necessary XGAP core work for the approved FinBench research track.
RQ: can the ordinary bounded program preserve financial edge multiplicity and
time constraints while estimated planning selects one executable strategy?
X: node/edge access, parallel edges, field comparisons, finite path length 1–3,
and source placement. Y: independent answer equality, admitted plan count and
actual calls. Tiny checks establish correctness, not performance superiority.

## Scope and acceptance

Allowed: semantic parameters/binding, edge compiler, row normalization/filter,
entity-bind strategy, workload descriptors, tiny financial programs and tests.
Forbidden: baseline changes, new algebra operators, large-data development,
online probing/fitting/retries, alteration of old artifacts/answers or model weights.
Acceptance: new-risk validation plus three gold financial programs through ordinary
planning and selected execution. Actual native evidence is recorded separately.
No historical successful gate needs repetition.

## Exact bounded meaning

An edge-form semantic Match uses `edge`, optional `source`/`target` node
descriptors, `entity_field`, `source_field`, `target_field`, and `properties`
(output alias to edge-property name). It is mutually exclusive with node Match.
It reads stored directed edges, equivalent to Selection(Edges(G)) followed by
binding projection. Each edge identity remains distinct even with equal endpoints
and values. Endpoints and edge identity are canonical resource IRIs. Missing
properties are null; the RDF encoding requires functional scalar properties and
one stable reified resource per edge. Plain resource triples are not admitted.
Existing path predicates refer to this one-edge path; row predicates refer to
declared binding outputs. No implicit property-fetch request is introduced.

Filter retains legacy scalar truth by default and admits an exclusive `right_field`
instead of `value`. Both referenced fields must exist before execution. Explicit
`value_type: timestamp_ms` admits only valid fixed-format local-calendar strings
`YYYY-MM-DD HH:MM:SS.mmm`, with the same source time convention on both sides.
After format/calendar validation their lexicographic comparison equals chronological
comparison. This is not timezone conversion or arbitrary ISO-date support.
Missing/invalid values make the comparison false (including ne); boolean NOT
complements that truth exactly as before. Legacy ordering of strings remains false.
Project may carry a finite scalar `literal`, needed to label fixed-length branches.
OrderLimit accepts explicit `limit: null` for a complete sorted result, while an
absent limit remains invalid. F1/F2 must not invent a large arbitrary answer cap.

Three fixed branches of up to three transfers implement the development temporal
path query via ordinary joins, strict adjacent timestamp comparisons and all-pairs
account identity inequalities. These programs are deterministic gold inputs, not
substitutes for NL interpretation. Preserve edge keys until aggregation/distinct
projection so parallel transfers are not collapsed prematurely.

## Planning and versioning

Edge Match exposes three canonical identity columns to the existing single-bind
rewrite. The native filter binds the actual corresponding endpoint or edge,
while the original coordinator join stays. Exclusivity and lineage checks remain.
The domain is still P(1+2J); no combined rewrites or Cartesian enumeration.
Compilation is polynomial in explicit program size; each edge Match emits one
constant-length structural pattern plus linear property/constraint text. Per-row
comparison is linear in condition size, with fixed-length time parsing. Join/result
execution can be expensive and is not included in the planner Ptime claim.

Edge Match is a one-edge path workload for the existing frozen v2 descriptor
features, with its actual output-column count and normalization nodes. This
extension is declared in prediction provenance; transfer is uncalibrated. No
weights, feature dimensions or training records are changed, and unavailable
estimates remain unavailable. Parameter contract advances to v2; new wire schemas
receive new hashes. Old records retain their original code/schema identity and
must never be silently repinned to this version.
