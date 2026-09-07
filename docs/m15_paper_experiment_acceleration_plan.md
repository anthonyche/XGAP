# M15 Paper Experiment Acceleration Plan

Status: **OPTION C ACCEPTED; IMPLEMENTATION ACTIVE; PAPER RUN NOT YET AUTHORIZED**

Date: 2026-09-07

## Submission boundary

- Venue: ACM SIGMOD 2027 Research Track, Round 4.
- Abstract and COIs: 2026-10-10, 11:59 PM AoE.
- Paper: 2026-10-17, 11:59 PM AoE.
- Length: 12 pages excluding references.
- Official call:
  <https://2027.sigmod.org/calls_papers_sigmod_research.shtml>.

The schedule is governed by these dates. XGAP will not wait for every optional
product feature before beginning experiments. The first paper-candidate pilot
is targeted for Sep 10 and the confirmatory protocol for Sep 12.

## What “complete system” means

The implementation is paper-complete only when the same frozen system can:

1. turn supported natural-language requests and bounded ambiguity candidates
   into typed semantic graph programs;
2. preserve hard constraints and obtain user authority for impact-relevant
   meanings rather than silently selecting them;
3. compile multiple semantic interpretations into registered fragments for
   heterogeneous black-box backends;
4. select and execute cross-platform plans using catalog observations or
   historical memory, including a zero-current-query-profile method;
5. return a bounded semantic-cost frontier with exact provenance;
6. run on public data and query sets, compare against frozen baselines, and
   produce independently auditable metrics and statistics.

The current system is mechanism-complete for one controlled query family. It is
not yet paper-complete because general intake, public multi-family execution,
external ontology evaluation, and confirmatory comparison are not joined into
one frozen protocol.

## Capability matrix

| Capability | State | What the toy work established | Remaining paper gate |
|---|---|---|---|
| Agent environment, typed tools, memory, finite goal loop | implemented | allowlists, provenance, budgets, termination, no hidden retry | exercise across all paper methods |
| Semantic Graph Program and v0 operators | implemented as an IR | typed DAG, hard/relaxable slots, stable identities | admit F1--F3 public query packages |
| General natural-language intake | partial | one fail-closed controlled intake plus older GrailQA path | connect supported GrailQA/FinBench requests to the M15 program contract |
| Entity/predicate/type/source ambiguity | partial | bounded catalog/ontology/model candidates and authoritative entity clarification | evaluate accuracy/coverage by ambiguity type on public labels |
| Structural ambiguity and clarification | implemented for one case | two-level interpretation sets and two authority events | extend to the declared public family contracts without ad hoc rules |
| Semantic equivalence, Pareto, epsilon, K | implemented for one family | bounded frontier and one physical representative per interpretation | compare predicted/observed frontiers across families |
| Neo4j/Fuseki federation | implemented on real backends | native service lifecycle, fragments, exchange, joins, cleanup, audit | load public benchmark partitions and test scale |
| Physical strategy selection | implemented for two strategies | fixed, family-memory, profile, adaptive, and oracle controls | add path/aggregate candidates and stronger catalog baseline |
| Zero-current-query-profile family memory | implemented, development quality | real 231-plan pilot and paired 264-plan comparison | multi-family/cold-family generalization with frozen training split |
| Live LLM tool | implemented as a bounded proposal | one audited Qwen3-32B call; hard constraints preserved | semantic quality/cost study over a real query set |
| Ontology tool | partial | local one-hop contract and provenance | official Freebase evaluation; optional FIBO mapping and ablation |
| Local clarification UI | implemented locally | same authority state machine, no extra authority | optional; remote UI validation is not required for the paper |
| Streaming/cancellation and production deployment | incomplete | bounded in-memory execution is reliable | implement only if benchmark scale makes it necessary |
| Paper experiment protocol | incomplete | immutable runs, audits, failure preservation | freeze population, baselines, statistics, exclusions, scales, and seeds |

## What the toy example improved

The toy financial-risk workload was an engineering instrument, not the target
dataset. It improved reusable capabilities in five layers:

1. **Semantic correctness:** hard constraints cannot relax; entity identity
   needs authority; predicate and structural alternatives remain separate;
   unavailable meanings fail explicitly.
2. **Agent behavior:** tools are typed and costed; LLM output is bounded and
   non-authoritative; user decisions survive restart; memory carries source
   identity; the loop terminates.
3. **Optimizer behavior:** alternative federated plans are executable; profile,
   family-memory, fixed, adaptive, and oracle roles are separated; probe reuse
   and Pareto/epsilon/K reduction are observable.
4. **Real runtime behavior:** Neo4j and Fuseki are started as native services,
   loaded through external interfaces, queried as black boxes, joined at the
   coordinator, and cleaned up under Slurm.
5. **Experimental integrity:** commits, inputs, decisions, plans, calls,
   results, and cleanup are hash-bound and independently audited. The toy runs
   exposed real failures in Cypher batching, request timeouts, vLLM JSON-schema
   compatibility, Slurm script paths, and auditor assumptions.

It did not establish open-domain parsing, scale, semantic generalization,
ontology truth, user utility, or superiority over baselines. Those are the
public-artifact experiments now being built.

## Unified research story

Natural-language graph queries can have multiple plausible meanings, and the
facts required to answer them may be split across heterogeneous black-box graph
engines with no shared optimizer. Calling an LLM or profiling every current
query can itself dominate serving cost. XGAP optimizes a typed semantic graph
program at the coordinator: it preserves user authority over meaning, uses
catalog/ontology/model/clarification as bounded tools, compiles each admissible
interpretation into backend fragments, and uses family execution memory to
choose physical strategies without current-query profiling. The output is a
small semantic-deviation versus execution-cost frontier, not one silently
chosen meaning or an unbounded list of plans.

Ontology, LLM, UI, and federation are not four independent selling points.
They are tools and environment elements behind one authority- and cost-aware
query-optimization contract. Removing ontology or the LLM must leave the
deterministic federated execution core defined.

## Public artifact stack

### Primary physical evidence: LDBC FinBench v0.1.0

- Official benchmark: <https://ldbcouncil.org/benchmarks/finbench/>.
- Official datasets: <https://ldbcouncil.org/benchmarks/finbench/datasets/>.
- Specification repository: <https://github.com/ldbc/ldbc_finbench_docs>, tag
  `v0.1.0`, commit `d3ec7036bf6919df8cd3eeaa3a986048e779ea02`.
- Initial SF0.01 archive SHA-256:
  `888c8fbe06b68cc48de9f07fde8c0fd3295618fc41af13ae1aa216aaec1e0430`.

FinBench is generated, not customer data, but it is an external benchmark with
a financial schema, standard query shapes, generator, driver, and scale
factors. XGAP changes source placement and derives cross-platform queries, so
the result is named **FinBench-derived heterogeneous workload**, not a
conformant FinBench score.

The initial deterministic partition covers all 18 v0.1.0 snapshot tables, not
only the eight tables needed by the first direct-transfer slice:

- Neo4j: Person, Account, ownership, transfer, withdrawal, loan-flow, and path
  structure;
- Fuseki: Medium and selected organization/person semantic/control facts,
  blocked/risk categories, types, and pinned mappings;
- XGAP: identity alignment, exchange, cross-source join, final declared
  aggregation/ranking, provenance, and scheduling.

The committed partition generator verifies the exact archive before reading,
streams the snapshot without extraction, rejects orphan relationships, and
produces immutable Neo4j Cypher, Fuseki Turtle, and a source-placement manifest.
Stable entity IDs are the only cross-backend identity replication. Control and
classification fields (`isBlocked`, account/medium categories, and risk level)
are authoritative in Fuseki; graph structure, transfers, withdrawals, loans,
ownership, guarantees, investments, and numeric flows are authoritative in
Neo4j. The SF0.01 local admission contains 36,881 source rows, 160 batched
Neo4j statements, and 28,374 Fuseki triples with zero orphan endpoints. This is
a data/readiness result and remains `paper_result=false`.

### Semantic evidence: GrailQA v1.0

GrailQA supplies 64,331 natural-language questions, logical forms, and official
processed Freebase ontology files under CC BY-SA 4.0:
<https://dki-lab.github.io/GrailQA/>. Existing XGAP audit, 150-question pilot,
catalog, and reachability artifacts are reused rather than rebuilt. GrailQA
evaluates relation/type grounding and compositional semantic generalization; it
does not stand in for physical federation performance.

### Ontology interoperability: limited FIBO mapping

FIBO provides standardized financial concepts:
<https://edmcouncil.org/frameworks/industry-models/fibo/>. Only a pinned subset
for people, organizations, accounts, and loans is eligible. FinBench-specific
edge names and risk levels remain explicit authored mappings unless the pinned
ontology defines them. FIBO is optional for execution and has a removal
ablation.

### External federation validation: FedShop subset

FedShop provides 12 templates, 10 instances each, pre-generated federation
artifacts, reference source assignments, and federation-engine adapters:
<https://github.com/GDD-Nantes/FedShop/>. It is homogeneous SPARQL, so it is a
separate validation stratum. Its Sep 24 integration cutoff prevents it from
delaying or rescuing the primary result.

## Three primary query families

1. **F1 direct transfer-to-control join**, derived from FinBench Complex Read
   12 plus blocked/control facts. Strategies: transaction-first hash and
   control-first bound query.
2. **F2 temporal path-to-control join**, derived from Complex Read 1/5 with
   bounded paths and strictly increasing timestamps. Strategies: path-first
   hash and control-first bound path.
3. **F3 aggregate exposure/ranking**, derived from Complex Read 12 and the
   aggregate patterns of Complex Read 6/7. Strategies: aggregate-first hash and
   control-first bound aggregate.

Entity, time window, direction, path semantics, thresholds, aggregation
function, group key, ordering, K, and output schema are hard when present. Only
declared predicate and control/risk-category slots may relax. F3 is the proposed
entirely held-out family; its zero-profile cold-start fallback must be frozen
before results are observed.

## Baseline and ablation contract

Physical methods on the same semantic plan:

1. XGAP family memory, with zero current-query profile calls;
2. fixed transaction/path/aggregate-first;
3. fixed control-first bind;
4. catalog-cardinality heuristic using only pre-query statistics;
5. no-instance family median or declared cold-start fallback;
6. current-query dual profiling with acquisition cost included;
7. centralize-all deployment control with equivalent facts, if feasible;
8. post-execution oracle for regret only.

Semantic methods on the same candidate boundary:

1. deterministic catalog top-1;
2. bounded Qwen top-1 without user authority;
3. ontology-expanded proposal without clarification;
4. full XGAP selective route;
5. gold interpretation for evaluation only.

Ablations remove ontology expansion, clarification authority, equivalence
merging, epsilon/K pruning, or family memory one at a time. Single-database
learned optimizers such as Bao or Kepler are related work, not direct baselines
unless their actual code can operate on the frozen heterogeneous candidate
space; a local approximation must not use their name.

## Results the paper must report

- Semantic: candidate recall, selected-interpretation accuracy, hard-constraint
  violations, abstention, questions/request, LLM calls/tokens/latency.
- Physical: observed-winner accuracy, serving and end-to-end latency, bytes,
  backend calls, latency/byte regret, and acquisition cost.
- Frontier: gold-plan retention, predicted/observed Jaccard, returned K,
  semantic deviation, exact-answer rate, latency, and bytes.
- Robustness: family, selectivity, scale, warm/cold memory, allocation, cache,
  and failures.
- Reproducibility: versions, hashes, source placement, seeds, schedule,
  exclusions, every attempted run, and audit results.

Repetitions are repeated measures, not independent queries. Method order is
counterbalanced. Correctness gates every performance row. One primary contrast
per RQ, confidence-interval procedure, multiplicity handling, timeout, and
infrastructure-failure replacement rule are frozen before confirmatory runs.

## Accelerated execution schedule

| Date | Deliverable |
|---|---|
| Sep 7 | Option C, public artifact lock, exact SF0.01 inspection |
| Sep 8 | deterministic Neo4j/Fuseki partition and source manifest | complete locally; CWRU load verification next |
| Sep 9 | F1--F3 local templates, parameters, and exact oracles |
| Sep 10 | first CWRU SF0.01 paper-candidate pilot |
| Sep 11 | pilot audit and SF0.1 feasibility |
| Sep 12 | freeze population, scales, baselines, statistics, failures, and seeds |
| Sep 13--20 | primary confirmatory physical runs |
| Sep 18--23 | GrailQA semantic track and ablations |
| Sep 21--25 | combined frontier experiments |
| Sep 24 | FedShop integration cutoff |
| Sep 25--28 | external validation and approved missing cells |
| Sep 29--Oct 2 | audits, reruns under frozen rules, figures, result freeze |
| Oct 3--9 | paper and anonymous artifact |
| Oct 10 | abstract and COIs |
| Oct 11--16 | final paper and artifact dry run |
| Oct 17 | paper submission |

If SF1 is not feasible by Sep 12, SF0.1 becomes the maximum primary scale. If
FedShop is not ready by Sep 24, it is omitted rather than allowed to compromise
the primary evidence or writing schedule.

## Immediate loop

The official SF0.01 archive lock, safe single-attempt cache acquisition, and
streaming schema inspection are implemented. The next code milestone is the
deterministic source partition and load bundle. VPN is not needed until that
bundle and its offline oracles pass and one immutable CWRU command is ready.
