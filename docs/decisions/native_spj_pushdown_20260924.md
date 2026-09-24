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
execution. The user subsequently pasted the worker receipt: one selected final
execution, one backend call, 5,050.138 ms, transaction memory limit reached
(536.9 MiB in use, 537.6 MiB limit, another 2 MiB requested). The observer
recorded a completed 311-byte response and no transport failure. Thus this is
native transaction memory failure, not HTTP timeout or response-budget failure.
Worker wall 7,696.819 ms and sampled worker RSS 39,690,240 bytes are separate
from source transaction memory. The emitted archive
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

## Necessary equality access repair

The first compiler wrapped every identity join and anchor equality in a total
nullable `coalesce` predicate. On a fresh tiny Neo4j 5.26.30 graph with declared
unique indexes, EXPLAIN of the unchanged failed query text produced six
CartesianProduct operators, seven NodeByLabelScan operators and no unique seek.
Adding the necessary raw equalities as conjuncts produced zero CartesianProduct,
zero label scan and seven NodeUniqueIndexSeek operators. This is local evidence
about expression visibility, not the full D2 optimizer plan or measured speedup.
No D2 query was executed during that diagnosis.

The compiler now records `necessary-positive-equalities-v1` and emits equalities
already entailed by mandatory positive conjunctions, while retaining every
original nullable predicate. If the original predicate is true, both operands
are nonnull and the emitted comparison is true; the new conjunct is therefore
redundant semantically. Extraction is disabled inside OR/NOT and for rejected
type comparisons. Physical variables are still independent; no unique logical
ID assumption is added. DISTINCT, final limit, source snapshot and all budgets
are unchanged. This does not imply bounded native execution memory.

Validation: 28 focused tests; six real Neo4j ordered-row comparisons (2/0/20/5/
64/44 rows) including duplicate IDs, parallel/reused edges, null disjunction and
negation. Source cleanup passed. Receipt `native-spj-tiny-v5/receipt.json` SHA-256
`9180be9b697db56d6a874f45262925f309ad09ad6345bdc04379ec45d1ff6a10`.
Local diagnosis under `spj-sargability-explain-v1/`: original plan SHA-256
`e4b944abc44d75681fb64e32e160aac1f5d33dbd5eb01a7f7a19b5672ee1cc61`,
visible-equality plan SHA-256
`b592b9a2a8619b0fa56e7d27528e1c9871e805c3de6048d1b8d55b7c8c39559e`.
All paths are under the local `ch6-release-boundary-20260924` artifact root.
Next gate: two bounded full-source EXPLAIN calls, zero result-query executions,
no optimizer feedback to the frozen online estimator. Keep transaction budgets
unchanged and investigate remaining source operators before another replay.

Frozen EXPLAIN-only handoff: exact source `f9a4837e6df0fe9a26d9fa8dc4829f3705d4cb88`,
package `/Users/anthonyche/Downloads/xgapaccessf9a4837.zip`, 14,428 bytes, SHA-256
`1aa460575634910539547f11be140345a3d34f16ab3a10dd0290cb265081f863`.
The stage requires `ef50ee3`, checks the old sealed failure archive, failed plan,
original cohort and prepared store pins, and refuses existing submission/output
directories. The driver compares the old and newly compiled unchanged program
using two EXPLAINs, no result-query executions, unchanged source/worker budgets
and node-local storage. Its evidence archive includes the sealed 3867410 archive.
Stage Python 3.6 syntax, driver syntax, shell syntax and bundle prerequisite passed.
The user supplied successful exact-source staging and submission **3867481**.
Running/terminal state and diagnostic outcome are pending; do not resubmit.
Journal `native-access-f9a4837/`, log `native-access-3867481.out`, output
`formal-native-spj-access-explain-v1/D2`, expected closed archive
`/home/hxc859/xgap-spj-access-explain-3867481.tar.gz`.
Successful EXPLAIN would not establish result correctness, execution latency,
memory safety or full-bundle admission.
