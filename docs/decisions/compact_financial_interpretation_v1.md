# Compact graph intent lowered to the existing semantic DAG

Status: next implementation milestone, not implemented or accepted yet. This
corrects implementation within the approved one-shot goal; the research question,
two modes, estimator, physical domain and evaluation population remain unchanged.
The legacy full-SGP interface remains available under its existing profile.

## Evidence and representation

Financial v1/v2/v3 expose the burden of asking the model to author all source
reads, intermediate aliases, identity joins and grouped schemas. V3 passes syntax
and catalog grounding but cannot compile because identity/property columns collide;
downstream fields were never read. More per-question prompt tuning is not next.

The compact profile will declare semantic variables, typed nodes/edges, named
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

For q declared graph/field/filter items and s explicit source alternatives, column
assignment, coverage checks and join assembly must be polynomial in q+s. One path
bounded by B<=3 multiplies work by fixed B, not a product of many path choices.
A simple implementation may use O(B*(q*s+q^2)) assembly plus existing fragment
validation; audit actual code before claiming a tighter bound. Existing64-operator
and runtime work budgets remain. This is not a query-execution time guarantee.

Compiled candidates enter existing top-K grounding and estimated selection;
P(1+2J) physical domain/guarantees stay unchanged. One model response, no online
fit/probe/repair, one final plan. Record raw compact response and deterministic
lowering; charge lowering to online cost.

## Implementation and acceptance

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
