# Unified XGAP: manuscript-to-implementation migration

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
 -> enumerate eligible terminal pairs and supported local actions
 -> symbolic lookahead of at most D steps
 -> choose Execute or the FIRST selected nonterminal action
 -> perform exactly that action, validate its actual response, update state
 -> discard hypothetical continuations and replan
 -> recheck actual eligibility and execute ONE final federated plan, or fail
```

There is no materialized complete policy over the full horizon H. Finite scores
at truncated leaves do not prove an executable continuation beyond D. In
particular, this algorithm need not find a policy even when one exists; it may
consume its horizon and fail safely. Do not export `strong_plan=True` simply
because a bounded lookahead returned an action.

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

## 3. Code inspection and required changes

|Component|Verified current implementation|Migration|
|---|---|---|
|Frontend/scope|`api.answer`, `semantic.intent_scope`, `agent.scope_authority`: bounded family, separate paid coverage reply|Reuse; expose one settings object instead of requiring a mode label; keep old entry behavior versioned|
|Loss|`agent.intent_certificate.TerminalContract`: finite family and exact rational weighted field discrepancy|Reuse distance/cache primitives; add designated-validation and Lambda checks independently of rho|
|Validation state|`FamilyState` stores observations/call/field counts; singleton consistency can satisfy epsilon=0|Store attestations or registered inference premises separately; candidate uniqueness is not automatically an authorized validation rule|
|Validation actions|`FamilyStrongDomain._actions` skips partitions with fewer than two groups|Allow required attestations even if they do not reduce the candidate set; otherwise singleton validation/set-cover cases cannot be represented|
|Search|`search_strong_policy` builds a complete feasible policy; `run_strong_intent` follows its saved children|Replace the current route with fixed-D value lookahead and observed-response replanning; keep historical solver for frozen releases|
|Capabilities|`family_runtime` eagerly calls `lookup_practical_capabilities`; this is local configured-adapter lookup, zero external calls|Keep initial declarations as s0 evidence; add selected metadata actions for genuinely missing capabilities, without relabeling the old lookup as a live probe|
|Physical plans|`FamilyStrongDomain.terminals` prepares only certified candidates; `family_runtime.prepare` builds/scores a bounded neighborhood and keeps one plan|Build bounded seeds independently of interpretation eligibility; retain up to K plans per query; make one supported transformation a local action|
|Statistics/probes|Current primary route does not select statistics acquisition actions|Add bounded named targets, fixed exhaustive outcome categories, real selected invocation and dependent-estimate invalidation|
|Cost|`JointCostProfile` already compares information and execution in declared units|Include selected local transformations; support outcome-dependent costs and request-fixed expectation/max backup; distinguish numerical preferences from calibrated latency|
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
   Include a case where a finite heuristic leads to later failure; it must not
   emit a false strong-policy or infeasibility claim.
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
