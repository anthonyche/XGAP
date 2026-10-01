# One bounded anchor fanout candidate

2026-09-13 continuation after real NL group6: both XGAP modes exceeded the
original2GiB observed RSS budget and received325,110,752 source bytes each.
All14 captured native requests were unbound. Coordinator reduction is exact
on tiny data but does not reduce those source responses.

Scope: runtime/physical_strategies.py, anchor_reduction.py (static admission
helpers), one_shot_planning.py (domain bound), focused tests, a necessary tiny
native boundary, and evidence/documents. No semantic language, common baseline
SPARQL, model prompt, frozen estimator weights/statistics, dataset or budget
change. Do not rerun old full-data questions. This is research-prototype work.

Add at most one complete candidate per placement: bind every proved target of
the existing single anchor reduction to its DISTINCT canonical keys, using
the existing REMOTE_BIND_QUERY adapter. This is a deterministic fanout, not
enumeration of subsets or combinations of local rewrites. Keep the coordinator
candidate and existing single-join alternatives. Do not combine this fanout
with those alternatives. A placement with no admitted anchor keeps the old
domain. The semantic input and final joins/filters/projections remain unchanged.

Each target must admit its native identity binding and a noncyclic dependency
on the existing key relation. All targets must be admitted to publish the
fanout candidate; no silent partial strategy. The key read happens inside the
one selected final execution DAG, not as an online planning probe. There is no
extra remote request slot, second final plan, automatic fallback or retry.
Empty keys skip bound calls; count/serialized SPARQL byte overflow fail
explicitly without truncation. The existing Cypher adapter does not claim an
additional serialized-byte bound. No uniqueness/selectivity of scalar values
is assumed from their name or from the evaluation answer.

For J joins and A in{0,1}, each placement constructs at most1+2J+A candidates.
The one-source-neighborhood size is D=1+sum_b(local_options_b-1), subject to
existing source call admission. The one-shot preconstruction bound is
D*(1+2J+A_upper), where A_upper is1 iff a necessary scalar-equality anchor
could exist syntactically; this is conservative before compilation. Reject a
domain exceeding the declared work budget before construction; never clip it.
With L compiled nodes/edges and n represented semantic operators, binding at
most n targets costs O(n*L + total generated query bytes); validation and
candidate construction stay polynomial. It adds no cross-product of choices.

Soundness follows the existing dominance/identity proof: rows outside the
anchor key set cannot survive any use of the target. Native binding removes
only these rows. Original final operators preserve multiplicity semantics
and hard constraints, including equal-valued parallel transfers. Exactness is
conditional on the existing snapshot/identity/scalar contracts and successful
completion within resource budgets.

Selection is the exact minimum of the frozen estimate over this declared
domain, not an actual-runtime optimum. If an independently justified uniform
additive estimation error epsilon held on this domain, actual regret relative
to its actual best would be at most2*epsilon; we do not have such an empirical
guarantee and do not claim it. Actual ranking and latency remain evaluations.

RQ: does using explicit anchor information at sources reduce transport and
enable bounded one-shot execution? X: coordinator-only versus the new source
binding on independent tiny facts; Y: exact rows, returned rows/bytes, calls,
bound enforcement, and frozen estimated selection. Compare only the two tiny
implementations needed for this new risk, then one native boundary. Record
missing real estimator support as a failure, never adjust weights to pass.

Eight selected checks first pass1.13s (six new cases plus two directly affected
legacy-domain/cycle checks). Tiny gold6 rows unchanged; the three first-hop
responses total24→12 rows, logical exchange9410→7286B with8 calls per execution.
Empty keys skip3 bound requests; count/byte overflow reaches no bound transport,
and one unsupported target rejects the whole macro candidate. Native query/data
correctness is not established by the in-process RDF evaluator.

Actual frozen tiny and full-RDF profiles can score the new candidate, with9
candidates/bound18 in these inputs. They still prefer coordinator: tiny fanout
estimate297.949ms; the saved full group6 plan predicts834.612ms coordinator versus
12842.692ms fanout. No data query or model call was rerun for that comparison.
This is a ranking concern, not permission to force the new plan in evaluation.

Next component gate executes only the predeclared fanout once on each existing
tiny deployment (Neo4j+Fuseki and two Fuseki instances). It records what ordinary
estimated selection would choose; it is explicitly not an estimated-choice or
paper comparison. Then inspect frozen selectivity/driver-size features before
continuing full NL, which would otherwise select the same source-heavy plan.

The88fe577 native component is accepted: one fanout execution each on the
existing tiny Neo4j+Fuseki and two-Fuseki deployments returns the same four
independent rows. Native14 calls/17157B/1210.506ms execution; RDF14 calls/26552B/
205.167ms execution. These are separate component measurements, not a same-run
speed comparison or an ordinary estimated choice. All services are terminal.

Post-seal source replay diagnoses one distinct actual anchor key from each
complete20409-row graph/control property response. The estimator assigns30000
bind-record units across the three targets; that term contributes11468.808ms
to the fanout-minus-coordinator prediction. No full question/model call/fit was
repeated. See equality_key_bounds_next.md for the next tiny, independently
prepared statistics gate; do not feed this exposed key observation into training.
