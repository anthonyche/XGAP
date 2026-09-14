# Practical strong planning v1 — current user-approved direction

2026-09-14. The user approved the practical two-mode brief and the review,
then clarified: the mathematical policy space is a finite-depth AND/OR tree;
the returned policy must be a **strong plan**. Prioritize producing a useful
feasible plan and improving measured performance. Do not claim global optimality.
The user will develop d(Q_tilde,Q_star) in the next theoretical stage. Do not
invent a replacement metric or turn LLM confidence into an epsilon guarantee.

This decision supersedes conflicting next actions in the historical one-shot,
precision/proxy-band, retrieval-budget, pause and acquisition-search notes. It
does not relabel or rescore any old experiment. Current implementation and evidence:
[milestone report](../report/practical_strong_planning_20260914.md).
P-S2 follow-up: [information adapters and native tiny evidence](../report/practical_information_native_20260914.md).

### P-S2 provider contract

Catalog acquisition requires pinned artifact provenance, a complete singleton
entity match and the existing provider's authoritative flag. A schema singleton
alone does not validate intent. Model proposals are bounded non-entity candidate
IDs with no authority. Empty/multiple/incomplete or non-authoritative catalog
responses lead to `unavailable`; malformed/version-mismatched/provider failures
lead to `error`. Both are declared AND outcomes; search cannot silently drop them.
Without feasible continuations, EXACT may correctly return no feasible plan.
Remote failures never trigger a hidden retry; a different action may run only
when it was already part of the returned strong policy's declared continuation.

The OpenAI adapter reuses the existing one-call/no-repair provider and pins its
safe configuration plus actual prompt hash. Tokens omitted by a paid provider
remain unknown, while reservations are separately recorded. Reservations are
checked against reported usage; no hard token certificate is claimed without
provider-side preflight. Provider input/output candidate caps share the existing
request contract; a multi-candidate output is unavailable, never first-item authority.

Capability lookup is local configuration admission with a hashed view of source
versions, backend adapters and languages. Per-operator capability validation
remains in the actual compiler. The view is neither live health nor a semantic
authority nor a hash of the entire backend executable/configuration.
The native tiny gate uses a trusted NL template, frozen catalog and a controlled
clarification continuation. Strongness covers declared outcomes, not all possible
file/server failures. The new profile's live model action remains unverified.

## Research question and evaluation boundary

Can XGAP reduce query-to-answer cost by choosing which information to acquire and
when to execute, while preserving required semantics and returning a policy with
complete continuations for every declared acquisition outcome?

Development X factors: ambiguity/outcome count, action depth, information cost,
state/action budget, exact versus performance, and estimator availability.
Y factors: strong-plan availability, time to first feasible policy, total planning
time, acquisition/model/remote counts, actual query-to-answer latency, independent
answer correctness, bytes and memory. A lower estimated score is not a measured
speedup. A no-plan or execution failure stays in the denominator.

No new ablation/scale/baseline campaign is authorized by this development decision.
Keep the approved FinBench -> same-facts RDF FedUP/FedX -> bounded FedShop priority.
Do not modify baseline algorithms, semantics, answers or outcome-driven settings.
Clarification-enabled end-to-end evaluation must expose the additional binding
information and its cost. Physical-planner comparisons use the same resolved query.

## Semantics, authority and scope

EXACT requires a complete typed query, all declared binding slots validated,
unchanged hard constraints, a plan implementing that query and admitted resources.
The initial release takes a trusted bounded query skeleton plus named entity,
predicate, type, scalar and source holes. A structure record is content-bound to
that skeleton. This is not proof that arbitrary model-generated NL structure is
correct. No singleton/model/catalog rank is automatically promoted to authority.
Evidence is supplied by trusted host/provider configuration with slot, candidate,
authority, source and version. It is not accepted from model-generated metadata.

PERFORMANCE may predict only explicitly allowed unvalidated slots. Validated
bindings and the trusted skeleton remain fixed. This is **uncertified performance**
while the discrepancy metric is deferred: output bound=null, status=metric_deferred.
Supplying epsilon is rejected instead of falsely claiming the constraint holds.
All actual operator semantics are complete for the selected query in v1. Existing
source-prefix truncation is excluded because no applicable error bound exists.
The policy/result fields reserve the future discrepancy interface; no metric,
probability calibration or answer-error guarantee is implemented in this stage.

Authoritative bindings do not establish the correctness of arbitrary NL parsing.
Catalog entity existence alone does not establish an ambiguous user's referent.
The response fixture contains only binding choices, separate from answer/query
oracles; it is read only when its clarification action is actually invoked.

## Finite-depth strong policy

An OR node chooses one acquisition action or a complete query/plan terminal.
An acquisition AND node includes **all** outcomes declared in that action's finite
model. A solved action requires a feasible strong continuation for every outcome.
An unknown/unavailable outcome without a continuation prevents a strong-policy
claim; a failure leaf is not a query answer. Runtime follows only the realized
branch and executes one final federated plan. One plan may make several distinct
source calls; those are not retries or competing-plan probes.

Strongness is relative to the declared finite transition model, source snapshot,
trusted authority providers and supported semantic/capability profile. It is not
a guarantee that a remote service can never fail. An unmodeled real outcome fails
visibly without retry or execution of another semantic interpretation.

Costs use existing frozen estimates. At an AND action, the v1 score is its estimated
cost plus the maximum child-policy score. This is a worst-outcome estimated
objective, not an expected cost with invented probabilities. Unknown estimates
stay unknown; they do not block feasible execution and are not treated as zero.
Costs compare equivalent physical plans within one query. Different meanings may
be compared only after the selected mode's semantic admission.

## Algorithm: feasible first, cost-ordered completion, bounded improvement

The initial implementation deliberately uses lazy cost-ordered depth-first
completion to establish an incumbent promptly, then a bounded number of root
action improvements. It is not mislabeled as AO* or globally best-first optimal
search. The mathematical object remains the strong solution subgraph of the
bounded AND/OR tree.

1. Validate the root state and finite input profile.
2. At each visited state, attempt a complete terminal. Construct a minimum-call
   feasible source placement from independently admitted local replicas first.
   Preserve it even if the estimator is missing or optional strategy generation
   exceeds its own domain budget. Retain the estimated better equivalent plan
   when available; compiler/capability failures remain explicit.
3. At unresolved states, consider declared actions in frozen cost/ID order.
   Reserve storage for all their outcomes atomically before visiting children.
   A partial outcome subset can never count as a solved AND node.
4. Complete the children within shared global search budgets and per-path resource
   reservations. Do not reset the state/action budget per branch or repeat an
   already attempted action along the realized path.
5. Record the first complete root policy immediately. Spend only the remaining
   improvement-action allowance; replace the incumbent only by a preferred
   complete strong policy. Never discard a feasible incumbent for a partial one.
6. Return policy feasibility and search stop reason separately. No result means
   no feasible plan was found under this search; it is not a proof of INFEASIBLE.

No execution probe, model invocation, oracle response or training occurs during
tree expansion. The domain callbacks only bind, compile and estimate. GoalLoop
executes selected actions afterward, preserving actual observations and costs.

## Computation and solution bounds

Finite depth alone does not eliminate exponential trees. Explicit limits bound
retained states S, generated actions A, outcomes/action O, depth H and terminals
per state T. The supplied action list has at most128 actions and256 outcomes per
action; no candidate Cartesian product is generated. Limits themselves have
implementation maxima (S,A<=4096,H<=32,T<=256) and are serialized.

Let n include the explicit skeleton, binding values, declared actions/outcomes,
source descriptors and bit lengths. Let C(n) bound local admission, typed binding,
compilation, prediction and plan serialization for one state. Source construction
uses L explicit local alternatives and the existing polynomial neighborhood of
at most (1+L)*(1+2J+B) strategies, with B<=1 anchor candidate per placement.
Finite path expansion is admitted before compilation (existing work cap4096).

A conservative local bound is O(S*T*C(n) + S*M*O*n + A*O*n), where M is the explicit
action-list size. Retained policy/trace memory is polynomial in S,A,O and the
compiled plan size; no entire implicit depth-H tree is materialized. Catalog
preprocessing, LLM inference, remote query execution and output enumeration are
not hidden unit-cost operations in this local planning claim. The wall-clock
deadline is checked between local operations; uninterruptible compilation may
finish after that check interval. Transport timeout enforcement remains a provider
responsibility, not a new hard real-time guarantee by GoalLoop.

Semantic soundness: every returned terminal passed its mode's admission and
compiler checks. Strongness: induct on remaining depth; terminals are feasible,
and an action is selected only when all declared child policies are strong.
Incumbent retention: a found policy survives later deadline/resource/domain limits.
With known scores, accepted improvements do not increase the incumbent estimate.
Unknown scores carry no numerical non-regression guarantee; stable feasible
fallbacks are retained. No approximation ratio or global optimum is claimed.

Always returning a plan requires a feasible admitted terminal or a strong
continuation that can be constructed within the profile. Contradictory constraints,
missing authority, unsupported source capabilities and an insufficient outcome
budget are explicit boundaries. The useful guarantee is to preserve an available
feasible plan despite optimization failures, not to fabricate one for infeasible
inputs. A reusable supplied strong-policy seed is a possible later extension.

## Current implementation map

- `agent/strong_planning.py`: bounded strong-policy search and separate feasibility,
  stop reason, estimated score and counters; certificate fields remain false/null.
- `agent/practical_planning.py`: typed state/evidence/actions, exact/performance
  terminal admission, feasible physical fallback and optional estimated improvement.
- `agent/practical_execution.py`: demand-only clarification and GoalLoop policy
  follower, scoped observed binding validation, one final native-runtime dispatch.
- `agent/practical_question.py`, opt-in `question.py` route: existing Interpretation
  -> trusted-skeleton check -> strong planning -> actual runtime. Interpretation
  usage is subtracted from remaining action budgets; templates need zero LLM calls.

Existing strict APIs, old one-shot mode profiles, backend internals, source facts,
frozen estimators and baseline/shared frontends are unchanged.

## Remaining implementation gates

1. Extend the provider adapters for frozen catalog/capability/optional LLM actions;
   declare honest finite outcomes, authority scope and reserved/actual costs.
   Existing providers are reusable, but not all are wired into this new policy yet.
2. Improve useful plan availability within the supported profile and acquisition
   ordering on independent tiny counterexamples. Do not buy a strong-plan label by
   hiding unknown outcomes or silently truncating candidate domains.
3. Run a necessary live Neo4j+Fuseki tiny gate for the new route and record new
   versioned evidence. Prior native results validate reused components, not this
   new complete policy integration. No full dataset run during development.
4. Address later-hop full reads through a separately specified semantics-preserving
   binding-propagation candidate shared by both modes. It is not implemented here.
5. Integrate the user's future discrepancy definition, then freeze epsilon-enabled
   semantics/profiles and discuss the final campaign amendment before evaluation.
