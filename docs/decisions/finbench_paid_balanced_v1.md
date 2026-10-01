## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Mode: run preparation within the existing approved R-C/E2 experiment plan
- Date: 2026-09-12, Asia/Shanghai
- Verification Status: protocol and order frozen before this experiment's outcomes
- Version: finbench-paid-balanced-20260912-v1
- Parent: 9d8cf2ebd79f79f8ea2c78b4bbcf13d94fde7b45

# Original48 prepared-plan cost comparison with balanced repetition

R-C asks when information acquisition is worth its total cost. This experiment
compares the existing fixed hash, fixed bind and paid full-plan acquisition
baselines on the original FinBench SF0.1 query population. The preceding
three-query pilot established execution/answer/accounting correctness but exposed
growing-ledger persistence overhead. Keep that pilot unchanged; do not subtract
estimated overhead from it or rerun it as a development gate.

The only prerequisite engineering change is lightweight durable persistence:
save each action result once, save a cost-only winner before fresh execution,
and update a small progress index without repeatedly serializing accumulated
answers. Measure persistence explicitly and include synchronous online work in
each method's wall time. Method-terminal summaries and full block sealing occur
outside that method's timing and are reported separately. The persistence sink
must never mutate the core record or its already-created execution seal.

## Population, methods and controls

All original48 IDs are included:32 seen-family queries and16 heldout-family
queries. The original f1-01/f2-01/f3-01 remain integration-exposed, including
F3-01's unchanged heldout-family label. None is relabeled as training. Preserve
every query/method/block slot after failure, timeout or non-execution. Incomplete
or failed empty answers do not become successful empty answers.

Each method starts from the same two prepared physical plans and public query
parameters. Candidate compilation and public-input validation happen once as
shared preparation. Fixed hash and fixed bind execute their designated strategy
once. Paid selection executes both complete strategies once as acquisition,
chooses by measured latency/bytes/strategy, persists the winner, then executes
it once afresh. It cannot use oracle contents or reuse a sampled answer as final.
All current acquisition, selection, execution and online persistence is charged.

Use the existing complete SF0.1 partition and unchanged source/archive identities.
Start actual Neo4j5.26.30 and Fuseki5.6.0 once in owned local state, load once,
and run six blocks in that allocation. No LLM, catalog build, new download,
Pioneer job or query warmup is involved. Databases retain evolving caches between
methods, questions and blocks. This is a mixed-cache workload sequence; it does
not measure isolated cold or controlled steady-state warm latency. Heldout-family
is a workload label, not a backend-cache condition or proof of memory transfer.

## Exact frozen order

The complete manifest is
`/Users/anthonyche/xgap-data/e2-finbench-balanced-20260912/orders.json`, SHA256
`b6f0d3dcb981b1f2c66a49fb8c601ce73dfec453f2a39911e3ef256d3912380e`.
It is a new protocol, not an edit to the original confirmatory authority or the
previous pilot's order. The schema is `xgap-finbench-paid-selection-balanced-v1`.

Every question appears once in each of six blocks. For each question the methods
cover all six permutations of hash/bind/paid. Thus every method occupies every
position twice; directed within-question adjacent method pairs are balanced.
At each of paid selection's three positions, its two appearances use opposite
acquisition orders. Merely alternating acquisition order by block parity would
not guarantee this condition and is not the design used here.

For original public index i and block b, permutation slot is (i+b) mod6, using
the ordinary permutations of [hash,bind,paid]. Acquisition direction is
[0,0,1,1,0,1][slot] XOR (i mod2), where0 means hash first. Each block's question
order is independently shuffled with Python Random(2026091201+b), then explicitly
stored in the manifest; execution uses those stored orders. Order validation
checks complete population and per-question balance before any query dispatch.

## Budgets and failure handling

Six blocks permit at most1,440 plan executions and2,880 query calls, including
864 final executions and576 acquisition executions. The workload still has48
question units, not864 or1,440 independent samples. Service start/load are separate
from query calls. Native work is bounded by800s plus100s cleanup reserve; combined
native/coordinator sampled RSS is limited to6GiB. Existing query/client deadlines
remain in force. Timeouts do not permit retry or replacement sampling.

Persist dispatch intent before each attempted call. First external failure,
unknown cost, durability failure or budget stop terminates remaining execution
for the whole campaign. Retain its received costs, mark unavailable costs unknown,
and preserve all remaining slots as not_attempted. A tool observation timeout
alone does not authorize restarting the process. After all blocks complete or
stop, seal execution records and the campaign index before parsing independent
answers once for evaluation. Cost-based decisions cannot see those answers.

## Analysis frozen before outcomes

Primary population is the original32 seen-family questions; report the two
exposed IDs explicitly. Original16 heldout-family questions are descriptive and
separate. A predeclared sensitivity view uses the30 unexposed seen-family
questions, without replacing the original32 table or changing denominators.

Aggregate six observed method wall times to their median within each question
and method. The two primary comparisons are paid/hash and paid/bind. Report
the geometric mean of per-question median-wall ratios; a ratio below1 favors
paid selection. For the32 seen questions, use10,000 query bootstrap draws,
stratified within the two fixed families, seed2026091212. A97.5% percentile
interval per comparison supplies a Bonferroni95% familywise interval convention
for these two comparisons. These intervals are conditional on this workload's
query-sampling assumptions and fixed families; overlapping graph data and the
single deployment limit generalization. Do not claim unseen-family coverage.

If any query/method lacks all six completed, exact observations, retain it in
the completion/failure table and report matched-pair coverage. Do not compute a
full-population ratio by treating failure/unrun latency as zero or silently
dropping it. A population speedup claim requires complete compatible pairs.
Also report per-query values, calls, logical bytes, acquisition costs, selected
strategies, and online versus post-method persistence. Scheduler times are a
separate decomposition, not a replacement for measured method wall or a sum of
parallel node times. No p-value-driven method or parameter search is planned.

## Scope and acceptance

This is a prepared-plan strong-baseline comparison. It does not exercise ordinary
P1/A3, memory transfer, LLM interpretation, ontology ablations, or scalability.
Hash and bind have different DAGs and are not P1 source replicas. The earlier
conditional2eta bound applies only to next-execution cost under a uniform error
assumption; neither this sample nor persistence engineering establishes that
assumption or a total-paid-cost approximation ratio.

Acceptance requires the changed tiny accounting/journal/driver checks, observable
durability and explicit cost scopes, complete original population accounting,
independently checked real answers, reconstructable method orders/costs and owned
service cleanup. Negative or inconclusive cost results remain results; they do
not justify changing the RQ, population or policies after observing outcomes.
