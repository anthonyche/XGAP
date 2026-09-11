# P1: polynomial planning and explicit quality guarantees

2026-09-11. Research design and proof obligations, **not an implemented planner
release**. Current source checkpoint: 7aad1dc. This decision preserves the
bounded semantic profile and existing experiment populations. It changes the
next engineering priority, not historical results.

## Objective and current defect

The system objective is measured query-to-terminal cost, including semantic
resolution, information acquisition, physical planning and execution, subject
to hard semantics and budgets. The physical selector currently optimizes a
**surrogate**: estimated root critical-path completion time, then transfer bytes,
remote calls and stable plan ID. This surrogate is not observed wall time.

`enumerate_semantic_plans` generates the Cartesian product of declared complete
equivalent replicas. For m source operators with k_i options it compiles
C=product(k_i) placements. `max_candidates=64` rejects larger products; it does
not provide a useful plan for arbitrarily growing m and k. Strictly, a capped
program may terminate in polynomial time by rejecting inputs; that is not the
required polynomial **solution-producing** planner. The selector's polynomial
scan of an already explicit candidate list does not fix exponential generation.

`FederatedPlanSelector.estimate` propagates max-ready-time, nonnegative local
latency, row counts and widths through a DAG. It does not model backend resource
contention or optimize arbitrary join order. The Python scheduler's behavior and
real endpoint timings must be measured separately. The present cost model is
explicitly uncalibrated. No global approximation ratio is currently established.

Do not label the XGAP-specific optimization problem NP-hard without a reduction.
Some current placement cases are simpler than general distributed query planning.

## Input and complexity contract

- q: a fully bound, validated semantic program; hard constraints never change.
- m: source operators; k_i: independently admitted local placement options;
  K=sum(k_i), k=max(k_i). Each option declares the same logical snapshot/identity.
- L: size of the explicitly represented local fragment alternatives, DAG edges,
  schemas and mappings; b: bit length of finite numeric inputs.
- The first optimizer profile uses the existing fixed finite path bounds.
  Complexity in an expanded IR is not complexity in an arbitrarily compact
  binary-encoded repetition expression. Admission/expansion itself must be audited
  and bounded before calling the whole pipeline polynomial.
- A feasible baseline p0 is supplied/constructed from independently admitted
  options. If global feasibility constraints couple options, this assumption
  must be re-established; a failed baseline does not prove no feasible plan exists.
- Local compilation and scoring must have documented polynomial bounds in L,b.
  No backend scan, LLM inference or path-answer enumeration is hidden inside a
  unit-cost local function. External acquisition counts and elapsed time are
  separate; a polynomial planner does not make all query execution polynomial.

## A. Exact Ptime subcase: independent source readiness

Assume:

1. Each source operator has one output into a fixed downstream DAG. Choosing its
   backend changes only that source block's ready time d_i(j).
2. Its output cardinality/width relevant to downstream work and downstream local
   durations are placement-independent. These are validated model assumptions,
   not inferred merely from a declaration that replicas are equivalent.
3. All combinations of independently admitted options remain feasible; there is
   no shared-backend capacity/contending-resource term or placement-coupled join,
   fusion, network edge cost or global execution budget violation.
4. The objective is the current nonnegative max-plus critical-path surrogate.

Algorithm: evaluate each local option once; choose
j_i*=argmin_j d_i(j), with deterministic ties; assemble and validate one plan.
Propagate readiness through the fixed downstream DAG.

**Claim A (model-relative exactness).** The resulting primary latency estimate
equals the global minimum over all product(k_i) placements under these assumptions.

Proof: each chosen source-ready time is no greater than its counterpart in any
other placement. By topological induction, max of predecessor times plus a fixed
local nonnegative duration preserves this inequality at every downstream node.
Taking max at the roots proves the claim. There is no need to enumerate joint
assignments. The proof is for the primary latency objective; arbitrary local ties
do not prove global optimality of all secondary byte/call tie-breakers.

Time is O(sum_i,j T_local(i,j) + L + K) with a topological DAG pass, plus
polynomial validation. Space is polynomial in L,K. If local options are explicit,
the selection step itself is O(K+L). This is **an exact special-case algorithm**,
not a novel approximation theorem and not yet an implemented replacement.

P1 first checks this assumption set against compiled fragments and model inputs.
Do not invent a complicated heuristic for cases where this argument suffices.

## B. Coupled model: bounded coordinate search with a certificate

For the more general point-estimate model, use the feasible baseline and a fixed
number of coordinate passes (v1 proposal R=2). For each operator, evaluate each
single replacement relative to the incumbent, and keep only a feasible
non-worsening plan. Cache local artifacts/estimates. Preserve p0 in the incumbent
set. Do not call the Cartesian-product enumerator from this path.

```text
p = p0
for pass = 1..2:
    for source operator i in a fixed order:
        best = p
        for admitted local option j of i:
            candidate = replace_only_source_option(p, i, j)
            if feasible(candidate) and score(candidate) < score(best):
                best = candidate
        p = best
return p, score(p), quality_certificate_if_valid
```

At most 1+2*sum_i k_i complete-plan evaluations are needed. Even a simple
whole-plan compile/score implementation costs
O(K*(T_compile(L,b)+T_score(L,b))) and polynomial storage. A fixed-pass count is
essential; “repeat until local optimum” alone supplies no polynomial bound.
Feasibility checks and any option-generation procedure are included in that
complexity obligation. No hidden exhaustive discovery of the starting point.

**Claim B1 (baseline non-regression).** U=estimated_cost(p) ≤ estimated_cost(p0),
because the incumbent starts at p0 and is replaced only by a non-worse candidate.
This is a baseline guarantee, **not** a global approximation ratio or a guarantee
on observed latency. Arbitrary coupled costs can have arbitrarily bad coordinate
local optima: on two binary choices costs (00,01,10,11)=(M,M+1,M+1,1), 00 never
moves while optimum costs1. This abstract counterexample does not establish that
every such table is realizable by the current XGAP cost model.

### A polynomial lower-bound relaxation

For the same-topology subprofile, enumerate only the **local** option fragments,
not joint plans. For each homologous remote node, take independent minima of
latency, estimated rows and row width across every admitted local option. Feed
these relaxed values to the fixed DAG cost recurrence. Call the resulting cost LB.

Validity requires the node correspondence, all options' coverage, nonnegative
inputs, fixed coordinator parameters and componentwise monotonicity of each
cost/row/width recurrence. Current max, sum, min, products on nonnegative values,
fixed fractions, finite recursive powers, and global-count constants can be
checked for this property. Any topology-dependent alternative or nonmonotone
extension needs its own sound relaxation; do not silently issue this certificate.

**Claim B2.** LB ≤ OPT_est ≤ U. Proof: the relaxed source values are componentwise
no greater than those in any feasible placement; induction through monotone
recurrences lower-bounds every root cost. The returned feasible p upper-bounds
the optimum. Independent minima can describe an impossible mixed option; that
makes the relaxation optimistic, which is precisely why it is a lower bound.

Thus the algorithm can report:

- additive optimality gap ≤ U−LB;
- multiplicative ratio ≤ U/LB when LB>0;
- certified (1+epsilon)-optimality only if U≤(1+epsilon)*LB;
- if LB=U=0, exact zero cost; if LB=0<U, no finite ratio certificate.

This is an **instance-dependent a posteriori bound**, not a constant-factor
approximation guarantee. It can be loose or vacuous, which E4 must report. The
lower bound must cover the full declared optimization domain, not merely visited
candidates. The minimum cost among visited plans is an upper bound, not LB.

No unsupported general case may be sold as certified: execution may still use
an explicitly labelled baseline/heuristic, but the paper must state certificate
coverage and missing guarantees. The wider query-language profile is unchanged.

## Estimated objective versus reality and acquisition

If one can independently establish a uniform relative error event
(1−delta) C(p) ≤ C_hat(p) ≤ (1+delta) C(p) for every feasible p, delta<1,
and C_hat(p_alg)≤alpha*OPT_hat, then on that event
C(p_alg)/OPT_actual ≤ alpha*(1+delta)/(1−delta).
This follows by applying the two error inequalities to p_alg and an actual
optimal plan. **Such an error guarantee has not been established for XGAP**;
observed sample fit or memory TTL does not prove it. A probabilistic guarantee
requires a valid simultaneous coverage argument, not pointwise intervals alone.

Information acquisition has another budget A≤B_acq and at most J declared
actions, with one attempt per action and no automatic retry. The action policy
can stop when a valid quality certificate is sufficient, or stop at budget and
report the achieved gap. Selecting the next action by expected uncertainty
reduction per cost remains a heuristic until its model/guarantee is specified.
Bounded acquisition cost is not global optimality of the joint agent policy.

On a valid cost-error event, an execution-cost bound can be combined with an
additive B_acq+local-planning-overhead term. It does **not** become an unconditional
approximation ratio against a clairvoyant information-acquisition policy. LLM
interpretation accuracy likewise is measured independently, not covered by the
placement proof. Quality constraints cannot be relaxed to satisfy a cost bound.

The familiar greedy 1−1/e result concerns specified monotone submodular
maximization settings. XGAP's cost reduction/information value has not been
shown submodular, so that result cannot be borrowed by name. See the primary
[Stanford approximation lecture](https://theory.stanford.edu/~tim/w16/l/l15.pdf).

## P1 implementation and experiment gates

1. Extract polynomial-size local alternatives, document compiler expansion and
   option feasibility; retain the existing enumerator as a small-instance oracle.
2. Implement A for explicitly admitted cases. Implement B with the fixed-pass
   limit and sound certificate only for its checked subprofile. Emit search mode,
   input sizes, evaluations, baseline score, U, LB, gap, assumptions and coverage.
3. Connect actual planning to normal bind/plan/execute and the same static/memory
   experiment entry. Memory identity uses local problem/observation context, not
   a serialized exponential candidate set. No new storage framework.
4. For tiny exhaustive cases check A=OPT, LB≤OPT≤U≤baseline, stable feasibility
   and identical independent answers. Add specific nonseparable, zero-LB,
   topology-mismatch and invalid-assumption cases; no blanket regression.
5. Run only the P1 grid frozen in the research plan plus the affected toy vertical
   slice. Report optimizer scores separately from actual latency and real data.
   A proof is not replaced by these tests; tests check the code implements it.

Completion requires source integration and these evidence artifacts. This document
does not declare P1 done, general Ptime compilation proved, or the whole research
prototype complete. Selective-acquisition and full-agent obligations remain in
the research plan; a correct placement subroutine alone does not finish them.
