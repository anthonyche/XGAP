# Compact graph intent lowered to the existing semantic DAG

Status: compact schema and deterministic lowering implemented; nine distinct new
local correctness/boundary checks accepted. Provider/ordinary-entry wiring is now
implemented with six new checks, including frozen-estimator compatibility of all
three generated financial domains. One actual compact financial NL-to-answer request now
passes in performance mode; [actual evidence](../report/compact_financial_nl_20260912.md).
This is a development boundary, not held-out quality or speedup evidence. See
[evidence](../report/compact_lowering_20260912.md). This
corrects implementation within the approved one-shot goal; the research question,
two modes, estimator, physical domain and evaluation population remain unchanged.
The legacy full-SGP interface remains available under its existing profile.

## Evidence and representation

Financial v1/v2/v3 expose the burden of asking the model to author all source
reads, intermediate aliases, identity joins and grouped schemas. V3 passes syntax
and catalog grounding but cannot compile because identity/property columns collide;
downstream fields were never read. More per-question prompt tuning is not next.

The compact profile declares semantic variables, typed nodes/edges, named
entity mentions, field predicates, projection, aggregation/distinct intent and
order. Fields refer to a variable and stored property, not an intermediate column.
A deterministic compiler allocates columns, derives property reads, enforces joins
and lowers to the existing operator vocabulary. Named mentions become ordinary
entity holes, bound by the frozen catalog with non-authoritative predictions.
The model supplies no resolved IDs, gold programs, physical choices or native text.

Keep edge identity until explicit distinct/aggregation so equal-valued parallel
edges do not disappear. Alias allocation and source routing are specified language
lowering, not response repair. Invalid intent fails with no second model call.
Semantic interpretation errors remain effectiveness outcomes.

## Source, semantics and complexity

Use frozen declared relation/property coverage only. Shared facts require declared
equivalence or conservative union; no gold operator_sources or observed costs.
Do not assume complete coverage from a successful sample. Physical replicas stay
choices for the existing planner; compiler-derived reads are not gold assignments.

Cover the approved financial families: conjunctive directed patterns, scalar/time
filters, sums/grouping and explicit pre-aggregation distinct keys; one finite path
component with lengths1..3, increasing edge times and no repeated node. Lower the
latter through existing finite union/join/filter semantics. No unbounded paths or
arbitrary optional nesting. Freeze the exact compact schema and independent meaning
before tests; this plan alone does not prove coverage or completion.

Let q count declared graph/field/filter items, S be the total explicit source
schema size and s the source count. One path with maximum B<=3 expands at most
B(B+1)/2 edge reads, not a product of independent path choices. With
U=O((q+B^2)*s) intermediate read units and F=O(q+B^2) columns, coverage scans cost
O((q+B^2)*S); the straightforward connected-unit scan and natural-join assembly
cost O(U^2*F*log(F+1)), a conservative bound including field sorting. Generated
DAG size/space is O(U*F+B^2). Existing parameter/program validation and downstream
fragment compilation are additional polynomial passes over this expanded DAG.
The existing64-operator limit rejects larger programs; it is an admission limit,
not a quality bound. These are lowering bounds, not execution-time guarantees.

## Frozen compact-v1 meaning (before test execution)

`compact_query.py` defines the shared finite wire/local schema. All query fields
are required: `nodes`, `edges`, nullable `path`, conjunctive `where`, `select`,
nullable `deduplicate_by`, `order_by`, nullable `limit`. Bounds are8 nodes,
12 explicit edges,32 predicates,16 output aliases, one homogeneous typed path
of1..3 hops,64KiB JSON, at most8 candidates and64 lowered operators. Unsupported
forms fail without clipping or repair. A top-K limit requires declared ordering.

Each node has a unique variable, type and optional named entity mention. An edge
has a unique variable, type, source and target node variables. References are
`{var, property}`; null property means canonical identity, never a model-authored
resolved ID. Technical identity literals are rejected; ordinary stored business-ID
properties remain legal. Output names are user-facing aliases; generated internal
columns cannot collide with them. Named mentions become normal entity holes.

Predicates compare property/identity references or literals via eq/ne/lt/le/gt/ge;
timestamp comparisons use the existing explicit millisecond contract. Required
node-property reads union all declaring providers, grouped by identical coverage;
explicit edges union all matching relation providers and reject partial required
attribute coverage. Every shared variable/field is an equality at joins. This
v1 profile assumes the frozen node properties are single-valued; conflicting values
across sources remain separate tuples, not silently overwritten authoritative data.

Path time windows apply to every edge, with individually declared inclusive bounds
and optional strictly increasing timestamps. ACYCLIC prohibits repeated nodes;
WALK permits them. The existing algebra's SIMPLE allows a closing endpoint repeat
and is not redefined or exposed by compact-v1. The result is DISTINCT(source,target,length) reachability,
without path identity or all-path bag output. Parallel-edge identities survive
ordinary patterns and only disappear at explicit projection/deduplication.

Before aggregation, nonnull `deduplicate_by` keeps DISTINCT tuples of the listed
node/edge identities plus scalar fields required by select. Every selected field
must belong to a retained variable. It does not pick an arbitrary value per key.
Nonaggregate selections are grouping fields; sum/count/min/max have an explicit
distinct flag, and only count may have a null field. Final projection is set-valued
under existing semantics. All ordering is on selected aliases. This covers the
three accepted financial meanings but is not unrestricted SQL/SPARQL semantics.

Compiled candidates enter existing top-K grounding and estimated selection;
P(1+2J) physical domain/guarantees stay unchanged. One model response, no online
fit/probe/repair, one final plan. Record raw compact response and deterministic
lowering; charge lowering to online cost.

## Implementation and acceptance

Provider wiring uses explicit `compact-graph-schema-v1` in the existing frozen
profile. The single response retains its raw compact envelope and per-candidate
lowering diagnostics. A failed lowerer emits an invalid candidate with no program;
valid siblings still face the ordinary full-SGP admission/output/identity checks.
Duplicate IDs stay duplicates and are rejected by that admission. An invalid or
over-cap envelope fails as a whole; neither the pool nor an individual query is
truncated/repaired. Lowering duration is online provider work. Legacy operator-ID
hard constraints cannot be mapped by compact-v1 and are rejected before dispatch.
The existing recorded response/replay protocol retains both raw and lowered forms.
Publication freezes both modes and uses no question/reference data. Native testing
chooses the new profile explicitly; it is never an automatic compatibility retry.

Allowed: compact schema/provider adapter, deterministic lowerer, small independent
intent/answer fixtures and targeted tests, financial publisher/runner integration,
current evidence docs. Leave native clients, baselines, estimator weights/training
and large-data evaluation untouched. No further v1/v2/v3 live prompt-tuning calls.

First implement the schema and three families' lowering on tiny data. Test actual
risks: alias direction/missing reads, entity-hole ownership, repeated-variable
equality, parallel-edge multiplicity, distinct and finite time/path boundaries.
Check independent expected answers, not just generated-text snapshots. Then
connect ordinary recorded NL for one necessary real boundary. Financial NL is
not complete until it actually executes and scores an answer.
