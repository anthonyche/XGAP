# M15-F2C14B Multi-Family Population Design Gate

Status: **OPTION C ACCEPTED; EXTERNAL-ARTIFACT REVISION IN PROGRESS; NO PAPER RUN AUTHORIZED**

This document freezes the decision boundary that must be crossed before XGAP
adds a second executable query family or compiles a multi-family campaign.  It
does not choose a domain, create a workload, authorize a CWRU run, or support a
paper claim.  Every artifact discussed here remains development-only with
`paper_result=false`.

The author selected **Option C** on 2026-09-07: three controlled financial
structures form the primary population and a separate standard-workload slice
provides external validation. The selection freezes population decision 1
only. It does not accept the original all-local synthetic P1 package as a paper
dataset. Under the accelerated SIGMOD schedule, P1 must be revised so that its
schema, data, and query shapes are traceably derived from public artifacts;
`datasets/financial_risk_dev/` remains a regression fixture rather than paper
evidence. The revised artifact and deadline contract is in
`docs/m15_paper_experiment_acceleration_plan.md`.

## Why this gate exists

F2C14A makes the current financial-risk family reconstructable: its typed
semantic DAG, native templates, instances, oracles, semantic alternatives,
physical candidates, split-safe views, and memory policy are hash-bound as one
package.  The remaining paper target requires at least three executable
families, 30--50 base instances, and one entirely held-out family.  Adding two
labels to the registry would not satisfy that target.  Each family must add a
real and auditable structural workload boundary.

Benchmark practice supports varying structure and selectivity rather than only
surface topic.  LDBC SNB separates neighborhood-oriented interactive work from
aggregation- and join-heavy BI work over a common domain.  WatDiv explicitly
varies query structure and selectivity, including linear, star, and snowflake
shapes.  FedBench emphasizes that federation experiments must expose source
distribution, interface and statistics differences, query expressiveness, and
domain variation instead of assuming one universal scenario.  These references
motivate the factors below; they do not make the author-level population choice.

Primary references:

- LDBC Social Network Benchmark: <https://ldbcouncil.org/benchmarks/snb/>
- Waterloo SPARQL Diversity Test Suite: <https://dsg-uwaterloo.github.io/watdiv/>
- WatDiv paper: <https://cs.uwaterloo.ca/~tozsu/publications/rdf/ISWC14-final.pdf>
- FedBench paper: <https://www.csd.uoc.gr/~hy561/papers/benchmarking/FedBench-%20A%20Benchmark%20Suite%20for%20Federated%20Semantic%20Data%20Query%20Processing.pdf>

## Operational definition of a query family

A query family is one compatibility class for family-local execution memory.
Members must share all of the following:

- typed semantic-operator DAG topology and operator kinds;
- binding-slot, hard-constraint, relaxable-constraint, and output schemas;
- backend ownership and registered native-template roles;
- coordinator exchange/join boundary and physical candidate space;
- semantic-deviation dimensions and family-memory feature schema.

Entity identifiers, dates, thresholds, preferred risk values, and selectivity
buckets create instances inside a family.  They do not create new families.
Changing path semantics, adding aggregation or ordering, moving a fragment to a
different backend, changing the output contract, or changing the admissible
physical strategies creates a different family and therefore a different
compatibility identity.

This definition prevents a family label from leaking measurements across
structurally incompatible tasks.

## Proposed research question

For executable federated graph-query families over black-box heterogeneous
backends, when can provenance-bearing family memory select semantic and
physical plans without profiling the current query, and what accuracy, regret,
and end-to-end cost are observed for seen families and an explicitly cold
entirely held-out family?

The held-out family is a boundary test, not an opportunity to silently perform
cross-family learning.  Its cold-start policy must be frozen before any result
is observed.

## Experimental factors

### Independent variables

- method: family-memory selection, current-query profiling, fixed physical
  strategies, and the frozen no-instance ablation;
- family role: seen family or entirely held-out family;
- executable DAG family;
- within-family selectivity bucket and result cardinality;
- controlled backend latency and transfer-cost condition, if included.

### Dependent variables

- exact answer and hard-constraint preservation;
- acquisition, planning, selected serving, and end-to-end latency;
- bytes moved, backend calls, coordinator work, and failed calls;
- physical-winner accuracy and latency/byte regret;
- predicted/observed semantic-frontier overlap for seen families;
- LLM, ontology-service, and current-query profiling calls, including zeros.

### Confounds that must be controlled or reported

- data scale, skew, selectivity, and cross-source join cardinality;
- backend placement, service version, warm-up, cache state, and execution order;
- native-template complexity and different ETL or identity-alignment effort;
- reuse of the same entity or threshold across train and held-out instances;
- oracle or evaluation-shadow leakage into selection;
- domain change being mistaken for DAG-shape generalization;
- allocation and node variability on CWRU.

## Population alternatives

### Option A: one controlled financial domain, three structural families

Keep one synthetic financial world and add executable families that differ in
DAG shape, not wording.  A candidate inventory is:

1. the existing direct transfer-to-risk join family;
2. a bounded multi-hop counterparty/path family followed by cross-source risk
   filtering;
3. an aggregate exposure/ranking family using cross-source join, grouping,
   ordering, and projection.

Target 10--16 base instances per family for 30--48 total, with two seen
families and one entirely held-out family.

Advantages: strongest control of domain, generator, identity alignment, and
backend partition; isolates whether DAG shape and selectivity affect planning;
lowest implementation and audit risk.  Limitation: external validity is
restricted to one synthetic domain.

### Option B: three domains or imported benchmark slices

Construct each family from a different domain or from LDBC/WatDiv/FedBench-like
workloads, while preserving the Neo4j/Fuseki black-box federation boundary.

Advantages: visibly broader domain coverage and stronger face validity.
Limitations: domain, schema, ETL, alignment, scale, and DAG structure change
together; a reviewer cannot easily tell whether an effect comes from agentic
planning or benchmark integration.  Public benchmarks also do not directly
provide the exact heterogeneous Neo4j/Fuseki split XGAP needs, so the bridge
would still be an authored artifact.

### Option C: controlled primary population plus external validation

Use Option A for the preregistered primary 30--48-query experiment.  After that
protocol is frozen and executed, add a smaller, separately reported external
validation inspired by a standard benchmark shape or dataset.

Advantages: preserves causal interpretability for the main result while giving
reviewers an external-validity check.  The external slice cannot redefine the
primary endpoints or rescue a negative primary result.  Limitation: highest
total engineering cost because two evidence layers must be maintained.

**Recommendation: Option C**, staged as controlled primary evidence first and
external validation second.  If schedule risk dominates external validity,
Option A is the defensible minimum.  Option B alone is not recommended because
it entangles too many factors before the core mechanism has a multi-family
result.

## Concrete recommended primary package P1

This section turns the Option C recommendation into one author-selectable
package. It is still a proposal: none of the identifiers below is admitted to
the executable registry until the author explicitly selects P1 (or requests a
revision). The proposal deliberately reuses the current semantic-operator
vocabulary rather than creating a second algebra.

### Population and split

P1 uses one controlled synthetic financial graph with 36 base query instances:

| Family | Role | Base instances | Split |
|---|---|---:|---|
| F1 direct transfer-to-risk join | seen | 12 | 8 training, 4 held-out instances |
| F2 exact-two-hop counterparty-to-risk join | seen | 12 | 8 training, 4 held-out instances |
| F3 aggregate exposure ranking | entirely held out | 12 | 0 training, 12 cold-start evaluation |

The 12 instances in each family should be allocated before execution across
three selectivity buckets with four independently bound instances per bucket.
Entity IDs used for held-out instances must not appear in that family's
training instances. Semantic interpretations inherit the base-instance split;
they do not become additional independent base queries.

### F1: direct transfer-to-risk join

F1 is the existing executable package and remains a seen family.

```text
MATCH(person)
  -> TRAVERSE(direct transfer)
  -> ALIGN(company)
MATCH(company risk)
  -> ALIGN(company)
  -> JOIN(canonical company id)
  -> PROJECT
```

- Neo4j owns person, account, transfer, and company-reference traversal.
- Fuseki owns company risk classification.
- XGAP owns alignment, exchange, join, and projection.
- Entity identity, time bounds, amount bound, currency, and direct path shape
  are hard.
- Risk class and the declared transfer/payment predicate are the only bounded
  relaxable slots.
- Physical candidates remain `parallel_hash_join` and
  `risk_first_bind_join`.

### F2: exact-two-hop counterparty-to-risk join

F2 asks for terminal companies reached by an exact two-transfer account path
from a clarified person's account. It is not the old optional path relaxation;
its two-hop meaning is the exact family semantics.

```text
MATCH(person)
  -> TRAVERSE(exactly two account-transfer edges)
  -> FILTER(per-edge time, amount, currency, and simple-path constraints)
  -> ALIGN(terminal company)
MATCH(terminal company risk)
  -> ALIGN(company)
  -> JOIN(canonical company id)
  -> PROJECT
```

- Neo4j owns the account graph and exact-two-hop path enumeration.
- Fuseki owns terminal-company risk classification.
- XGAP owns terminal-company alignment, exchange, join, and projection.
- Person identity, a closed-open time window applied to both edges, currency,
  minimum amount on every edge, exactly two hops, no repeated edge, and the
  terminal-company output contract are hard.
- Risk class and the declared transfer/payment edge predicate are the only
  bounded relaxable slots. One-hop, at-most-two-hop, path-total, and reachability
  interpretations are not silently admitted; they would require a separate
  author decision and compatibility identity.
- The two physical candidates are `parallel_path_hash_join` (enumerate the
  complete qualifying path side and join it with risk rows) and
  `risk_first_bound_path` (retrieve risk IDs first and bind terminal IDs into
  the registered Neo4j path template).
- Output fields are person, terminal company, the two transfer IDs,
  intermediary account ID, hop count, minimum edge amount, currency, and risk.

### F3: aggregate exposure ranking

F3 asks for the top-K companies by total qualifying transfer exposure from a
clarified person, restricted to a risk class. It is the entirely held-out
family because its grouping, ranking, and output contract are structurally
different from F1/F2.

```text
MATCH(person)
  -> TRAVERSE(direct transfers)
  -> FILTER(time, amount, and currency)
  -> AGGREGATE(group by company; sum amount; count transfers)
  -> ALIGN(company)
MATCH(company risk)
  -> ALIGN(company)
  -> JOIN(canonical company id)
  -> ORDER_LIMIT(total exposure descending, deterministic tie break, K)
  -> PROJECT
```

- Neo4j owns transfer filtering and per-company aggregation.
- Fuseki owns company risk classification.
- XGAP owns alignment, exchange, join, deterministic ranking, and projection.
- Person identity, closed-open time window, currency, qualifying-transfer
  amount bound, group key, `SUM(amount)`, `COUNT(transfer)`, descending ranking,
  deterministic tie break, K, and output schema are hard.
- Risk class and the declared transfer/payment predicate are the only bounded
  relaxable slots. SUM must not become AVG/MAX, and top-K must not be enlarged
  as a semantic relaxation.
- The two physical candidates are `aggregate_first_hash_join` (aggregate all
  qualifying companies, then join risk rows) and `risk_first_bound_aggregate`
  (retrieve risk IDs first, bind them into the registered aggregate template,
  then rank the semantically equivalent result).
- Output fields are person, company, risk, total exposure, transfer count, and
  deterministic rank.

### Cold-start rule

P1 freezes a fail-closed, zero-current-profile rule for F3: the family-memory
method must not borrow records from F1 or F2 and must select
`aggregate_first_hash_join`, the family-declared nonlearned default. This is a
declared limitation of family-local memory, not a claim that the fallback is
optimal. Current-query profiling remains a separately costed comparison method,
never a hidden fallback. If either F3 candidate is unavailable, the method
reports unavailable rather than changing semantics or profiling implicitly.

### Why P1 was the initial recommended decision

P1 creates three genuinely distinct optimizer regimes over the same backend
partition: selective direct join, path expansion, and aggregation plus ranking.
It therefore varies the conditions under which parallel versus bind-first
execution can win without confounding the primary result with a new domain or
ETL stack. Holding F3 out entirely makes the no-cross-family-memory boundary
observable. A later external slice remains separate and cannot redefine the
primary endpoints or rescue its result.

Author acceptance of **P1** would simultaneously freeze required decisions
1--4 below: staged Option C, the three DAG/ownership contracts above, F3 with
the fixed aggregate-first cold-start rule, and the 36-instance allocation. It
would authorize package and generator implementation, but not a CWRU run.
Inferential analysis and external-validation selection would still require
their later gates.

The author subsequently accepted Option C but required a public-artifact
primary workload on a submission-driven schedule. Therefore the 36-instance
allocation and the three DAG shapes remain useful candidate controls, while
the original locally generated financial world is superseded as the proposed
paper data source. The remaining physical decisions will be frozen against the FinBench-derived
package, GrailQA semantic track, and external-validation boundary described in
the acceleration plan. No result from the old toy workload may be relabeled as
a paper result.

## Required follow-on decisions

The author should decide these in order, one at a time:

1. population strategy: A, B, or C;
2. exact family DAGs, backend ownership, and hard/relaxable slots;
3. held-out-family identity and its zero-current-profile cold-start rule;
4. per-family instance counts and train/held-out-instance allocation;
5. primary estimand, inferential model, exclusion rules, and multiplicity plan;
6. whether and which standard workload supplies external validation.

No family generator should be implemented before decisions 1--3 are frozen.
No multi-family CWRU campaign should be compiled before all six are frozen.

## Acceptance gate for F2C14B

F2C14B may advance from design to implementation only when:

- the author selects one population option;
- at least three proposed families have distinct typed DAG signatures and
  declared backend partitions;
- the held-out family and cold-start behavior are explicit;
- the target remains 30--50 base instances without post-result family changes;
- primary and external-validation claims, if both exist, are separated;
- no automatic retry, oracle leakage, or hard-constraint relaxation is allowed;
- the inferential analysis is preregistered before the paper-scale run.
