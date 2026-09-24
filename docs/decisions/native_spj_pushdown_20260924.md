# Bounded single-source SPJ pushdown

## Evidence and motivation

The downloaded 3867351 archive is 4,879,633 bytes, SHA-256
`76037e8d2ab5855796772152dba487a47975d60c955918384c0b101c3738f183`.
Its exact c517451 replay failed with `harness_response_budget`, not the previous
transaction timeout. The fifth request, incoming edges for 1,896 Movie keys,
returned 67,108,865 bytes in 13,476.367 ms before the 64 MiB body guard stopped it.
HTTP 200 and partial bytes are not a completed result. Worker guard was
30,545.897 ms; method/source peaks 274,198,528 / 1,641,586,688 bytes. Both were
below the unchanged limits. Owned processes and reconstructable copies closed.

The selected coordinator plan still transmits a large intermediate before the
complete query's DISTINCT/order/limit. Index access alone cannot remove this
network/materialization cost. The new alternative contracts a bounded positive
relational program into one source query. It is not a MovieLens/zigzag dispatch,
and no question ID, literal answer or measured winning plan is consulted.

## Admission and equivalence

`native-spj-final-topk-v1` admits a grounded single-root semantic tree of at most
64 operators / 128 KiB input, using Match, Filter, identity Join, field Project
and one final OrderLimit. Every required Match must already be placed on the
same Neo4j backend and retain its existing snapshot identity. Match requires
positive node/edge labels without entity-property constraints. Extra capability
requirements, unions, aggregation, paths and shared semantic DAG children are
declined. A rejected alternative leaves the protected original plan intact.

The frozen source schema must declare relevant scalar property types. This is a
data/encoding premise, not a type inferred from answers: nullable strings,
booleans, integers and finite numbers; the existing canonical local identity
contract also applies. Floating field-to-field comparisons and floating output
representatives are excluded. Numerical constants are integers within 2^53;
calendar-string timestamp conversion is excluded. Integer epoch milliseconds
are ordinary numerical values. Unknown/missing type declarations decline fusion.

Each source read gets independent native variables. Identity joins compare the
identity *properties*, so duplicate logical IDs do not justify silently merging
physical nodes. Separate MATCH clauses permit reuse of the same physical edge
in distinct semantic reads; a combined Cypher pattern could forbid that reuse.
All mandatory labels, directed edges and total nullable row predicates remain.
There are no intermediate LIMITs. Positive SPJ set boundaries may be delayed to
the final DISTINCT because no aggregation or intermediate order observes bag
multiplicity. Parallel edge witnesses therefore preserve the final set result.

The final output is identity/string/boolean/integer, has a limit of 1..1000,
and orders every projected column. This removes distinct-row tie ambiguity.
Explicit null placement is independent of sort direction. The real tiny gate
checks Unicode ordering, nulls, parallel/reused edges and duplicate logical IDs.
No source subset, interpretation or query result is approximated by this move.

## Planning and work estimates

`PhysicalMoves` yields one checked `native_spj_pushdown` neighbor, cached per
candidate and placement for the request. The new plan uses the existing remote
query runtime node, with one adapter call and the same response/time/RSS guards.
It enters the shared fixed-depth planner, retains the protected seed, and is
chosen by estimates. No source execution occurs while generating/ranking it.

The existing frozen source populations and endpoint degree moments score it in
declared work units. The new source-work branch charges full domain/edge scans
and a greedy connected-join intermediate proxy, plus final returned rows and one
call. A declared unique scalar equality supplies an estimated anchor; first
expansion uses mean degree and later expansions use size-biased degree. This is
a heuristic, not the actual native join order, a cardinality bound or latency.
Only final transfer is capped by LIMIT: neither scan work nor join work is capped.
Old unfused plan scores are numerically unchanged; the new branch/provenance is
versioned `native-spj-source-work-v1`. No fitting or current-query probes occur.

Compilation is polynomial in the bounded program/field representation. The
greedy work proxy uses O(M^2) edge choices, no permutation enumeration. The
change adds one neighbor, not a product of physical choices or deeper lookahead.
Native database execution itself has no new polynomial/data-size runtime claim.

## Verification and remaining boundary

- 25 focused compiler/work-model/shared-controller tests passed; the expanded
  native SPJ test also verifies one final selected plan and zero search calls.
- `scripts/check_native_spj.py`, receipt at
  `/Users/anthonyche/xgap-data/ch6-release-boundary-20260924/native-spj-tiny-v3/receipt.json`:
  four real Neo4j comparisons, exact ordered rows 2/0/20/5, successful cleanup.
  Each comparison uses the original coordinator and the new runtime path.
  Remote calls are 7/7/7/4 versus one. These are tiny correctness gates, not a
  large-data latency or scalability result.
- The unchanged D2 failed complete query compiles to 1,973 bytes, seven required
  Match reads, one final LIMIT 20; zero backend/model calls and zero reference
  answer reads. Artifact SHA-256
  `49fedf2a583cfd2a26a822529d08727435f6fc4f8e0d6eb0a7ed7e6729451c9b`.

The frozen single-case package has been submitted as **3867410**, exact source
`ef50ee3`, by the user. Its staging/submission output was also read directly from
the OnDemand terminal. The user subsequently supplied Slurm FAILED/2:0,
71 seconds, compt311, and attempted/audited=1 for the original failed case.
This is a failed singleton gate, not evidence of successful large-source
execution. The underlying error remains unclassified until raw evidence is read;
job elapsed time alone does not establish a query timeout. The emitted archive
is 38,301 bytes, SHA-256
`b9deacdce5cd1f9bda83147a4ee93d58be64d6f5c6fb231dfe9153363c5479ff`;
download verification is pending. Collect this existing evidence; do not submit
the package again. The gate checks
selected-plan evidence and executes only the unchanged original failure under
existing caps. Do not rerun the successful
prefix, change samples or raise limits. A successful singleton would still not
admit all D2 held-out cases or authorize the full formal campaign. Cross-source
fusion and aggregate fusion remain outside this initial physical alternative.

The frozen single-case package is now prepared from exact source
`ef50ee3898f5a6f22a6223543d3aa8834c836316`:
`/Users/anthonyche/Downloads/xgapspjef50ee3.zip`, 26,091 bytes, SHA-256
`7af7b9315fad48f9c0579ceeb12d448f135ea3f7205bcaad0c19218a13f10717`.
It requires existing checkout c517451, verifies the original cohort/store and
3867351 failed receipt, and creates a separate checkout/submission journal.
Before starting sources it performs zero-call symbolic selection for this one
case; if the frozen estimator does not select source contraction, it stops and
archives the diagnosis. Otherwise it runs the existing single-case gate, with
no changes to the full cohort, reference, source stores or caps. CPU batch on
compt311, 8 CPUs/24 GiB, 40-minute allocation and no requeue. Stage Python 3.6,
shell syntax and bundle prerequisites were checked locally. Journal:
`native-spj-ef50ee3/`; log: `native-spj-3867410.out`; final archive when closed:
`/home/hxc859/xgap-native-spj-3867410.tar.gz`. Neither 3867410 nor 3867351 should
be resubmitted. Submitted is not the same as successfully admitted.
