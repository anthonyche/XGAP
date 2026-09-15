# Matched fixed-information frontend for external federation methods

2026-09-15. Implements the missing common partially bound input route. This is
an explicitly named composition, not a new capability attributed to FedUP/FedX.
Do not alter their author implementation, global compiler, supported semantics,
answer normalization or frozen result denominators. No observed-output tuning.

The composition consumes exactly the practical request/profile used by the
corresponding XGAP mode: trusted structure, initial validated choices, optional
predictions, allowed acquisitions, candidate/outcome sets, authority provenance
and budgets. A profile explicitly supplies a pinned same-facts RDF mapping and
the fixed_action_order_v1 recipe. External compositions require all RDF sources.
No implicit lookup of a gold/reference file or another profile's bindings.

Algorithm: reuse the practical domain's terminal binding admission, without
generating a physical plan. At each step, stop if the current mode admits a
complete bound query. Otherwise try the next unused, locally available action
in the profile's frozen priority/estimate/ID order. Follow only a declared scoped
observation. A declared unavailable/error may continue to the next action in
that predeclared sequence; an unmodeled/malformed observation fails. Every action
has at most one invocation, within depth/action/resource limits. Missing usage
is unknown, while reservations remain separate. Once a query is admitted, compile
one global unresolved-source SPARQL query and submit it once to the selected
author method. Compilation/transport/semantic failure cannot trigger another
meaning, engine, action-order search, repair or retry.

This fixed sequence is a comparison mechanism, not XGAP's strong AND/OR search.
It neither enumerates contingencies nor claims a feasible continuation for every
outcome. The XGAP path still uses strong search. Both paths share binding/authority
semantics; model output never creates authority. All acquisition captures and
native responses are kept. Invalid/unavailable/time-limited cases remain outcomes.

With M<=128 explicit acquisitions, H<=32 depth and A<=4096 actions, sorting costs
O(M log M); at most min(M,H,A) invocations occur. Choosing from a linear sequence
and checking explicit outcomes is polynomial in the input. Typed binding and
the existing bounded global compilation are charged. Model/server work is not
hidden inside the local Ptime statement. No approximation or global optimum claim.

Names: fixed-info-exact-fedup/fedx and fixed-info-performance-fedup/fedx. A v2
study declares its method list explicitly; legacy v1 two-mode studies remain
unchanged. Source/method-host ownership, query guard, observation, scoring and
journal reuse the existing common path. The caller supplies the owned external
endpoint; the input request cannot choose or silently switch a method host.
The caller may provide a per-cell owned-resource callback so another idle author
host is not charged as the active method; the legacy fixed owned list still works.
For more than two methods rotate order by group index before outcomes; the
two-method case preserves its prior alternating order. No completed cell is
redispatched, and no reference pin reaches readiness/deployment/endpoint callbacks.

RQ: does joint strong information/physical planning improve query-to-answer cost
and quality relative to a fixed information workflow with established federation
planners? X: method/mode and predeclared information availability/budgets. Y:
correct completion, online time, acquisition/model/source costs and failure type.
Only common semantic support measures shared-support efficiency; native missing
operators are reported separately and not used as proof of optimizer speed.

Allowed changes: practical terminal-binding extraction, this fixed frontend and
worker, explicit method/study routing, mapping publication, focused tests/docs.
Acceptance: same-mode authority and provenance, all declared failure boundaries,
one final global query, costs/captures, wrong native responses preserved, old
strong/NL paths unchanged, explicit supervised dispatch. Develop on toy/replay;
do not launch a formal baseline/ablation campaign from this gate.

MaterialPassport: authorized research comparison integration; not author-native
NL support, a strong-policy certificate for the fixed frontend, or a paper result.
