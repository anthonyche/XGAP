# Bounded XGAP scope and the two meanings of semantics

2026-09-11. User clarification during typed-binding acceptance. This document
states current capability boundaries and proposes a finite acceptance scope.
It does not add a runtime limit, change algebra, remove benchmark obligations,
or declare all combinations accepted.

## Interpretation and executable meaning are separate

Interpretation maps a natural-language request into a semantic program with
entities, schema, sources, predicates and constraints. An LLM may help with this
mapping, but its output must pass deterministic validation. Wrong entity or
missing year constraint is an interpretation/binding failure.

Executable meaning specifies what a valid program returns. Logical lowering,
native compilation and coordinator execution must preserve that meaning. A
wrong integer SUM, join equality or shortest/filter order is an implementation
failure even when the LLM produced the correct program. Missing operators are
an expressiveness boundary. An LLM cannot make an unavailable operator exist.

Current status therefore must not conflate:

- A request outside the declared query language.
- An incorrect interpretation of an in-scope request.
- A compiler/runtime bug for a valid in-scope program.
- A valid program that exceeds an explicit operational budget.

## Current executable core, with evidence boundaries

The modern semantic DAG has nine operator kinds: Match, Traverse, Filter, Join,
Union, Aggregate, OrderLimit, Project and Align. Existing fixtures verify specific
compositions, rather than all conceivable operator nestings.

| Area | Implemented profile | Boundary |
|---|---|---|
| Sources | Read-only property graph/RDF plugins; declared identities, mappings and logical snapshots | Equivalent replicas and property views are explicit assertions; no arbitrary partition discovery |
| Paths | Rel/Seq/Alt, OUT/IN/UNDIRECTED, Optional path expression, finite Bounded and finitely bounded Plus/Star; finite nested scopes | Explicit finite bounds and expansion budgets; no promise of unrestricted recursive query execution |
| Path rules | WALK, TRAIL, ACYCLIC, SIMPLE, SHORTEST; ALL/ANY/k/shortest selectors through audited algebra | Existing scope/selector and node-domain/edge-identity rules apply; not arbitrary native language semantics |
| Predicates | Entity/label/property tests, supported scalar comparisons, AND/OR/NOT, null tests at the binding layer | Numeric positions in path conditions require fixed-length paths; row ordered comparisons remain numeric; arbitrary functions are absent |
| Bindings | Projection, set union, equality join, internal semijoin and explicit identity alignment | Path Optional is not relational LEFT OUTER JOIN; no blanket claim for general correlated OPTIONAL/NOT EXISTS or bag semantics |
| Aggregates | Grouping; COUNT(*), COUNT(field), SUM, MIN, MAX; DISTINCT; typed numeric equality | Finite JSON scalars and explicit RDF values; no arbitrary aggregate/UDF, window or temporal-interval algebra |
| Ordering | Scalar order, explicit null placement and positive finite limit | Numeric/string/Boolean/RDF families follow the declared binding contract; no arbitrary object comparison |
| Control | Budgeted typed tool use, binding and declared-source candidate selection | Controlled-provider success does not establish real-model interpretation accuracy |

Historical focused-binding/reference operators remain separate from the modern
native semantic-DAG profile. Their existence is not evidence that every such
operator is connected to this native path. The binding value profile separates
Boolean and numeric values; PathSet atomic equality retains its audited rule.
The optimizer must not move predicates across these layers without a proven
equivalence. Current operator names alone are not an adequate semantic contract.

## Actual implementation budgets

These are code guards/defaults, not measured scalability guarantees:

- A compiled fixed/expanded path may have at most64 edges (`directed.MAX_EDGES`).
- Native path expansion defaults to at most128 branches.
- Normal semantic enumeration defaults to64 candidates,128 unique observation
  calls,16 remote execution calls per plan and parallelism4. Callers can supply
  smaller applicable budgets; the typed toy gate uses4 candidates and8 observations.
- Recursive expressions require finite repetition bounds or an explicit
  `max_depth`. The latter can count repetitions of a multi-edge child, so it
  must not be described as universally equal to the number of graph hops.
- The system does not yet enforce a universal intermediate-row/memory cap or
  offer accepted general streaming execution. An output LIMIT does not bound
  the intermediate work. These gaps cannot be hidden by reporting the other caps.

## Proposed first system contract

XGAP can target **read-only, typed, finitely bounded graph queries over declared
heterogeneous sources, composed with supported relational operations**. Specify
an actual expanded-edge bound L, supported recursion/position forms, scalar
domain, source/identity assumptions and independent call/branch budgets.

Development fixtures can use a small L (for example3) while retaining smaller
branch/candidate budgets. This is a suggested workload setting, not a newly
enforced universal3-hop limit. Evaluation must declare its bounds in advance,
include depth/branch/source variation relevant to the research claims, and retain
coverage and unsupported-rate denominators. Do not select a bound after seeing
which benchmark questions succeed. No selected dataset is removed by this note.

T1 should close against a finite, independently specified profile: every included
form has a defined answer, compiler/runtime correctness checks and a maintained
vertical slice. A genuine missing included capability must be fixed. An explicitly
excluded query class is documented as outside the profile, not an endless backlog.
The profile must be specified independently of compiler acceptance; “whatever
compiles” would make correctness/coverage claims circular.

Tests retain two chains: NL→gold semantic program for Interpretation, and gold
program→logical/native plan→expected answer for deterministic planning/execution.
Run both together only after their isolated contracts are verified. The LLM is
optional for the second chain.
