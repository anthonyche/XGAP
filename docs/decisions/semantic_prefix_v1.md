# A2: execution-prefix adaptation over polynomial placement

2026-09-11, scope frozen at parent3387309. R-C/E2/E3 mechanism gate. The old
AdaptiveFederatedExecutor already executes common prefixes, but requires explicit
candidate tuples. A2 connects prefix execution to the ordinary P1 local-option
domain without constructing the Cartesian product. It preserves the semantic
program and original full-plan call budget.

Input: a prepared P1 problem, complete initial point-estimate snapshot (explicit,
exact-context memory, or normal bounded cold acquisition), and a policy choosing
one whole input-free source fragment. The default prefix is the cheapest source
fragment in the initially selected plan, ties by source ID; an explicit eligible
source ID may be used for a frozen experiment. This ordering is a heuristic,
not a theorem about optimal probing or parallel execution. Existing ReplanPolicy
provides finite factor thresholds and zero/one replans. A1 refresh/static modes
are mutually exclusive with this first prefix policy.

1. Select the initial placement using P1. Execute the chosen complete instrumented
   fragment, including its exchange/normalization/local operations, once. All its
   inputs must be inside the fragment. Failure stops without continuation/retry.
2. Keep the completed source's backend fixed. Use observed remote results to
   update matching keys in the complete snapshot. Repeated keys use the last
   node in stable lexical node-ID order; all raw node observations remain in the
   trace. Keep memory read-only after this partial update.
3. Define residual cost by setting every completed node's ready time to0, rows
   to its actual result count, width to max(1,output_bytes/max(rows,1)), and future
   calls/bytes to0. Apply the unchanged monotone cost recurrence to remaining
   nodes. Keep prefix wall time separately; it is sunk, not future latency.
4. Restrict that operator's domain to its completed backend and use the initial
   selected full plan as the residual baseline. On threshold breach with one
   allowed replan, use P1 with the residual selector; otherwise continue initial
   placement. No-replan has the same prefix and observations but skips reselection.
5. Before continuation validate successful complete results, ancestor closure
   and exact runtime node definitions, including backend/artifact/key, against
   the selected full plan. Reuse scheduler initial_results; execute only remaining
   nodes. Local scoring views may omit the prefix; full candidate/LB views must
   contain it entirely. Never weaken full-plan validation for local views.

For fixed completed states the remaining recurrence stays componentwise monotone.
The local-option minimum relaxation gives LB≤OPT_remaining. A feasible selected
continuation gives U≥OPT_remaining. Starting from the initially selected plan
proves U≤cost_remaining(continue_initial) in this same updated model. Independent
cases retain P1's exact proof: the completed source is a singleton with constant
output states, and invariant downstream work for other consumed sources remains
required. The general branch keeps two coordinate passes and its conditional
instance gap/ratio; changed topology gets baseline-only. Guarantees concern the
restricted remaining placement domain and primary model cost, not a globally
optimal full query, prefix choice, acquisition value or actual wall time.

Prefix choice, domain restriction and result-stat extraction are polynomial in
represented fragments/results; residual P1 has at mostK local+2 full scores in
the exact case, or1+2K full scores otherwise. K now counts restricted local options.
These are feasible-candidate/local-score counts, as in P1's trace; the certificate
also needs at most one relaxed-DAG scoring pass. Two additional full scores record
the initial and selected residual costs. Prefix choice scores at mostm fragments.
Thus one initial P1, one optional residual P1 and this instrumentation remain
O(K*(T_compile(L,b)+T_score(L,b))) plus polynomial prefix/stat/trace work; no
iteration-until-convergence or hidden product-sized oracle is involved.
No data scan or native execution is a unit-cost planning operation. Actual output
and trace materialization incur their own output-size cost. One prefix and one
continuation do not make arbitrary graph evaluation polynomial.

Accounting: final scheduler results already include the prefix node results.
Overall calls/bytes equal final totals, not prefix+final; new continuation calls
are final minus prefix. On failed prefix use prefix totals only. Report prefix,
planning and continuation times separately and current end-to-end wall time.
Do not subtract prefix calls from the full-plan budget while the DAG still includes
those nodes. Keep old/updated snapshots, fixed placement/domain, proposed residual
certificate, executed residual score, threshold reasons and reuse IDs distinct.

Acceptance: a two-source tiny query changes only its unfinished placement;
replan/no-replan both match independent gold with no duplicate prefix calls;
B04 can finish its sole source with zero residual model cost. Tiny residual
oracles check bounds. Corrupt/incomplete reuse and prefix failure must stop;
no exhaustive call is permitted in the ordinary path. Run only affected tests
and one relevant native slice. No large datasets or broad regression. Acquisition
stopping/value, actual model LINK and real-data comparisons remain obligations.
