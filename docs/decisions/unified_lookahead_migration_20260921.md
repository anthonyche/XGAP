# Unified XGAP: manuscript-to-implementation migration

Implementation update: the [protected-seed first slice](../report/unified_lookahead_seed_20260921.md)
now implements the validation and guarded online-controller foundation. This
does not mark all migration items below implemented or evaluated.

2026-09-21. User supplied a revised Introduction, Preliminaries, problem
formulation, and fixed-depth planning algorithm. This records the new research
target and an inspection of code at `9d60598c041d9b7869e833e5b50cea63b243db68`.
It is a migration specification, **not evidence that the new controller is
implemented or evaluated**. The submitted manuscript was not modified. The
formal experiment Goal and its automation remain paused.

## 1. One system and one research question

Choose information acquisition, physical-plan construction and execution jointly,
under validation, interpretation-loss and resource constraints. Minimize the
declared cost of the realized trace, using an expected-cost model when supplied
for the request, otherwise worst-case cost. Both choices retain worst-case
semantic eligibility.

`Lambda` specifies which designated bindings may remain unvalidated; `epsilon`
specifies permitted interpretation loss. They are deployment settings of the
same controller, not separate Exact and Performance algorithms or a promised
speed hierarchy. `Lambda = empty` requires all designated validations.
`epsilon = 0` by itself need not imply that those validations were acquired.

The previous experiment supports stable completion of its frozen workload and
does not establish a reliable speed advantage of its Performance configuration.
It neither disproves every possible tolerance trade-off nor establishes the
effectiveness of this new algorithm. Keep the old measurements and method IDs.

## 2. New operational contract

```text
NL proposal + public domains -> full bounded family -> paid coverage confirmation
 -> actual state (validated bindings, evidence, descriptors, retained plans,
                  consumed resources, completed action count)
 -> construct/retain a bounded completion witness and reserve its resources
 -> enumerate eligible terminal pairs and supported local actions
 -> symbolic lookahead of at most D steps, rejecting loss of reserved completion
 -> choose Execute or the FIRST selected nonterminal action
 -> perform exactly that action, validate its actual response, update state
 -> discard hypothetical continuations and replan
 -> recheck actual eligibility and execute ONE final federated plan, or fail
```

There is no materialized complete policy over the full horizon H. Finite scores
at truncated leaves do not prove an executable continuation beyond D. In
general the bounded algorithm need not find a policy even when one exists.
However, consuming resources on optional actions until a KNOWN feasible
completion becomes impossible is an avoidable defect, not an acceptable use of
that incompleteness disclaimer. The guard below preserves such a completion.
Do not export `strong_plan=True` simply because a bounded lookahead returned an
action; any completion guarantee must cite its separate witness and assumptions.

Terminal eligibility is checked before it is compared with action values; it
does not force immediate execution if a cheaper predicted continuation exists.
Execution wins ties. At h=H, only an eligible terminal is allowed. At j=0 and
h<H, g ranks continuation; it is never an execution certificate. Empty or
conflicting candidate states remain invalid before evaluating that heuristic.

Every declared outcome participates, including probability-zero outcomes. An
infinite continuation rejects the action even under expected-cost ranking.
An unavailable binding response is an actual failure, not a fabricated normal
binding. Probe/metadata contracts can include an exhaustive `unknown` category;
it consumes an action without creating knowledge. Hypothetical responses never
reach the actual evidence ledger or live tools.

### 2.1 Required refinement: prevent validation starvation

The user identified a gap in the original truncated-leaf score on 2026-09-21.
This refinement changes the migration target; it is not yet implemented in the
runtime and is not claimed to be a guarantee already established by the draft.

**Concrete counterexample.** Set D=1, H=2, with two required sequential
validations costing 5 each, an available retained plan costing 1, and an
optional probe costing 0.1 that returns unknown and changes no knowledge.
The plan is not eligible until both validations finish. With g=1 at every
truncated leaf, the first validation scores 6 while the probe scores 1.1.
The controller probes, leaving only one action for two validations, then fails.
Validation, validation, execution was feasible initially, at cost 11.

Adding the remaining validation cost fixes that example, but is not sufficient
as a general safeguard. With the same two-step horizon, suppose terminal cost
is estimated as 100 until a one-time useful probe revises it to 1. Even if g
includes the exact remaining validation cost, the first validation scores 110
and the probe scores 11.1. The probe still destroys completion feasibility.
This also shows that suppressing repeated probes alone is insufficient.
Both deterministic examples were checked with a small local symbolic calculation;
they involve no model/backend calls and are not experimental measurements.

Implement the following three protections together.

**A. Score completion, not execution alone.** At a truncated leaf use a
nonrecursive completion estimate with separately logged components:

`g_complete(s) = estimated_required_validation + estimated_required_capability`
`                + estimated_required_plan_construction + estimated_execution`.

Compute the components for a specified bounded completion routine and its
retained plan choices, not unrelated minima that cannot be realized together.
Do not double-count an action that discharges multiple requirements. Its cost is
an estimate in the shared objective units, not a certified lower/upper cost bound.
No retained plan must not be interpreted as free completion: include the bounded
seed-construction work or mark completion unavailable. Omit neither mandatory
attestations nor requirements outside the lookahead window. The leaf score
remains a ranking heuristic, never execution authority or a resource certificate.

**B. Preserve a constructive completion witness.** Maintain W(s), a compact
recipe leading to eligible execution under every declared normal response,
together with certified remaining action bound L_W and resource bounds R_W.
An already eligible retained plan is a witness with zero remaining nonterminal
actions, but its execution resources must still be reserved. Otherwise a
supported fallback can use a fixed order of authoritative validations followed
by selection of a supported seed plan for the resulting candidate. Validate the
recipe by bounded local rules and scans over the explicit family; never search
the full policy space to obtain it or enumerate all combinations of responses.

Before allowing an optional action a, require a bounded check/repair of a witness
for EVERY successor s'=T(s,a,o), including unknown and probability-zero outcomes:

`1 + L_W(s') <= H - h_s`,

and the action's certified consumption plus the successor's reserved completion
must fit all remaining hard budgets. For cumulative resources this means
`r_s + r_a(o) + R_W(s') <= b_max`; for peaks use a sound peak-composition bound,
including retained live memory. Estimates, expected resource use and static
remote-node counts do not establish this inequality. The reservation includes
final execution and the bounded local work needed to carry out the fallback;
optional lookahead CPU/bytes cannot spend a reserved completion allowance.

If a successor loses its witness, reject that optional action. Store the checked
tail for the actual outcome. On a deadline or when no improving preserving
action fits, take the first action of the saved recipe without another optional
search. That recipe has a decreasing remaining-step rank and never depends on
optimistically repeating unknown probes. Execution wins ties; among tied
nonterminal choices prefer the saved completion action over optional work.

Do not discard protected seed plans or their evidence to satisfy the K-plan
retention cap. A compact recipe may refer to at most one protected seed per
remaining candidate; it must respect the same polynomial representation limits.
If no such witness can be constructed, report `completion_witness_unavailable`
or use an explicitly bounded required-action bootstrap; disable optional probes
until a witness exists. Neither outcome proves that no feasible policy exists.
An unknown required capability cannot be assumed supported to mint a witness.

This provides a CONDITIONAL guarantee: once a valid witness fits, preserved
snapshots, correct normal responses, sound bounds and execution contracts imply
that optional optimization will not consume the ability to complete. A service
failure, source-version change or broken certified bound is still an explicit
failure. This does not solve general policy feasibility or imply global
optimality. It preserves one cheaply constructed route, rather than searching
or storing the complete optimal conditional-policy tree.

**C. Suppress repeated no-progress work.** Memoize attempted probe identity,
parameters and the relevant semantic/capability/statistics/source fingerprint.
Unknown or unchanged information is not a knowledge advance. Increasing h,
appending a receipt or changing a timestamp alone must not unlock the same probe.
Retry only under a declared finite contract or a relevant knowledge/version
change, and reapply the reserve guard. Allow useful probes with some unknown
outcomes when all outcomes preserve completion; do not require every outcome
to reduce the semantic candidate set. Different probes can still consume slack,
so this rule supplements rather than replaces the reservation.

Log completion-witness identity, remaining reserved steps/resources, leaf-score
components, optional-action rejection reasons, no-progress suppression and actual
fallback activation. Charge only performed actions as trace work; checking the
witness and hypothetical branches is separately measured planning overhead.

## 3. Code inspection and required changes

|Component|Verified current implementation|Migration|
|---|---|---|
|Frontend/scope|`api.answer`, `semantic.intent_scope`, `agent.scope_authority`: bounded family, separate paid coverage reply|Reuse; expose one settings object instead of requiring a mode label; keep old entry behavior versioned|
|Loss|`agent.intent_certificate.TerminalContract`: finite family and exact rational weighted field discrepancy|Reuse distance/cache primitives; add designated-validation and Lambda checks independently of rho|
|Validation state|`FamilyState` stores observations/call/field counts; singleton consistency can satisfy epsilon=0|Store attestations or registered inference premises separately; candidate uniqueness is not automatically an authorized validation rule|
|Validation actions|`FamilyStrongDomain._actions` skips partitions with fewer than two groups|Allow required attestations even if they do not reduce the candidate set; otherwise singleton validation/set-cover cases cannot be represented|
|Search|`search_strong_policy` builds a complete feasible policy; `run_strong_intent` follows its saved children|Replace the current route with fixed-D value lookahead, completion-resource reservation and observed-response replanning; keep historical solver for frozen releases|
|Capabilities|`family_runtime` eagerly calls `lookup_practical_capabilities`; this is local configured-adapter lookup, zero external calls|Keep initial declarations as s0 evidence; add selected metadata actions for genuinely missing capabilities, without relabeling the old lookup as a live probe|
|Physical plans|`FamilyStrongDomain.terminals` prepares only certified candidates; `family_runtime.prepare` builds/scores a bounded neighborhood and keeps one plan|Build bounded seeds independently of interpretation eligibility; retain up to K plans per query; make one supported transformation a local action|
|Statistics/probes|Current primary route does not select statistics acquisition actions|Add bounded named targets, fixed exhaustive outcome categories, real selected invocation and dependent-estimate invalidation|
|Cost|`JointCostProfile` already compares information and execution in declared units|Include required completion costs at truncated leaves and selected local transformations; support outcome-dependent costs and request-fixed expectation/max backup; keep estimates separate from reserve certificates|
|Execution|Existing lowering, compiler, scheduler, row retention and recorded backend calls|Reuse; recheck mapping/capability/snapshot/budget witnesses against actual state before the one final dispatch|
|Evidence|Complete policy export plus observed path, compressed answers, independent scoring|Record per-round decision summaries and actual trace; label hypothetical values as predictions; preserve old evidence formats|

The compiler and runtime are reusable; the main replacement is the controller,
its state/action interfaces, and physical-plan retention. Existing physical
rewrites must be checked against the new one-transformation action contract;
wrapping the current all-at-once generator in a single action is not alignment.

The confirmed family Qs is filtered only by authorized evidence. Plan retention
may remove a physical plan but must not remove its query from Qs or from the
maximum-loss calculation. Retention preserves an available eligible plan and
keeps requirements explicit for other retained plans. A query may have no plan.

## 4. PTIME and guarantee boundaries

The manuscript gives coordinator work

`O((H + 1) * sum_{j=0..D}(A * Delta)^j * T_local)`.

This is polynomial when D is fixed independently of input size, and H, A,
Delta, K, plan representation length and local work are polynomially bounded
in explicit input size. A merely finite D that grows with the input does not
give this result. Parsing, outcome generation, loss evaluation, rewrite checks,
cost evaluation, arithmetic precision and cache-key construction must obey the
same representation bounds. Do not hide a recursive search in g.

The starvation guard extends T_local with polynomial construction/checking of
the compact completion recipe, resource reservation and no-progress lookup.
It does not enlarge D or require exhaustive horizon-H policy search. If witness
verification itself recursively enumerates a full outcome tree, the PTIME claim
has not been preserved. The new conditional completion guarantee and these
local operation bounds must be reflected in the algorithm/proof revision.

The full candidate family must be explicitly bounded before Cartesian
construction. Each action enumerates its complete finite outcome set; no
truncation of uncertainty to pass a budget. A probe's numeric response needs
fixed categories with a bounded count and an explicit unknown case.

Finite D is the algorithmic bound; cooperative CPU/state/byte guards are
additional operational limits. If a guard interrupts evaluation, report a
bounded fallback to an already eligible terminal or a failure, not the exact
argmin of a lookahead that was not completed. Bounded recursion alone does not
make arbitrary external callbacks polynomial or preemptible.

Successful execution can preserve hard constraints, supported physical semantics
and d(Q*,Q)<=epsilon under coverage, truthful authority, sound compiler rules and
fixed snapshots. It does not guarantee an answer on every feasible instance or
bound result-set F1. Planning time excludes waiting and backend execution;
request latency includes them and the coordinator overhead.

The terminal 2*eta statement is conditional on uniform additive estimation
error for a fixed Q and the actual eligible retained set: if P_hat minimizes
estimated cost and P_best minimizes true cost, then

`c(P_hat) <= c_hat(P_hat)+eta <= c_hat(P_best)+eta <= c(P_best)+2*eta`.

It is not a whole-policy approximation ratio, a guarantee over discarded plans,
or an established property of the current estimator. A rank-only estimator is
still usable for physical ordering, but cannot by itself supply additive
acquisition-versus-execution values or justify an absolute-error eta. Use a
declared numerical work model for that comparison; wall-time regression is not
required. Keep missing calibration visible.

The four supplied sections do not contain the referenced appendices. The
weighted-set-cover reduction is plausible precisely because required validation
is independent of candidate uniqueness; its full reduction and the detailed
local-generation bounds still require review against the actual appendix and
implemented generators. This note does not certify those proofs.

## 5. Integration order and small acceptance cases

1. **State and terminal contract.** Add Lambda, mandatory validation records,
   capability requirements, statistics versions, plan pools and cumulative/peak
   resources. Test singleton-but-unvalidated, authorized unique inference,
   contradictory evidence and hard constraints. Do not treat the number of
   static plan nodes as a certified upper bound on batched remote calls.
2. **Pure lookahead and online controller.** Fixed D, finite nonrecursive g,
   expectation/max, zero-probability dead branch, execution tie, H boundary,
   unknown-response consumption and replan after the actual observation.
   Reproduce both starvation examples above, then require completion with the
   reserve guard. Test exact step-budget fit, token/remote/byte exhaustion,
   probability-zero reserve violation, unchanged unknown probe, a useful probe
   that preserves slack, protected-plan retention and deadline fallback without
   replanning. Missing witnesses must not emit false strong-policy or general
   infeasibility claims. Do not assert guaranteed completion outside the stated
   witness, authority, source and resource assumptions.
3. **Shared physical and information domain.** Seed plans before validation;
   enumerate single legal rewrites; cap/deduplicate plan pools; test preservation
   of an executable incumbent and of all semantic candidates. Add actual
   metadata/statistics adapters and dependency-based estimate invalidation.
4. **One complete tiny vertical slice.** Frozen simulated authority and the
   existing compact frontend/compiler/runtime. Test cases where information is
   worth acquiring and where it is not; one case in which a probe changes the
   physical preference without changing Q; exactly one final execution.
   Pure symbolic search must make zero external calls. Validate the changed
   external boundary on the smallest necessary real backend case when resumed.
5. **Batch and writing alignment.** New profile/algorithm version, per-round
   evidence, action costs versus measured overhead, result/discrepancy scoring,
   followed by a new pilot/release. Never reinterpret the 96 old executions as
   fixed-lookahead results. No broad regression or full-dataset development loop.

In observed resource reporting, add cumulative calls/tokens/bytes, take maxima
for peak memory, and separately record selected local-action work and hypothetical
lookahead work. Do not bill all imagined branches as performed calls. Runtime
guards and estimated resource quantities do not become certified admission
bounds by renaming them.

## 6. Consequences for Chapter 7

The central comparison becomes unified XGAP versus a sequential
interpretation-then-physical-planning pipeline and faithfully integrated external
methods. Within declared supported inputs, measure whether joint decisions lower
end-to-end cost at adequate answer quality/coverage. Include cases where the
sequential approach is sufficient and preserve unfavorable outcomes.

Lambda/epsilon are contract-sensitivity factors, not two headline methods.
Lookahead D, uncertainty/action cost, estimator quality, plan-pool size and data/
source scale are candidate factors. Reuse the existing metric/plot machinery,
but revise and freeze the Chapter 7 matrix before another formal campaign.
Do not silently erase the old 20-figure plan or claim this note has executed it.

## Source identities

These are SHA-256 hashes of the user's four original attachments. Full draft
text remains in the original local attachments and is not copied into Git here.

|Section|SHA-256|
|---|---|
|Introduction|`e2e0c9712a3498de8451ab152e9cae863785f29406e90816e19f05272ad86df1`|
|Preliminaries|`c542d81b453d4d1b17a62c6e649de110782713382786d5a23afa50e298883856`|
|Problem|`341636ccaa3ab0e1293d3b60e795fa003666b218c2537a22713436a1b5199853`|
|Algorithm|`860b870766c9ab25d5678df641dd2f1a329f33611631c37f97b70e347de40544`|
