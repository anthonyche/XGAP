# Native Match identity projection v1 — 2026-09-13

RQ: how much unnecessary representation transfer contributes to native one-shot
latency and memory. Factor: native Match wire representation. Outcomes: raw
source bytes, observed memory and answer equivalence. This is an XGAP compiler
improvement, not an estimator retraining, new planner or baseline modification.

Evidence motivating the change is the frozen first-eight native prefix: three
2GiB method-RSS interruptions; whole node/edge objects returned by edge Match;
two unrestricted transfer reads each transmitting 106,715,911 bytes in group 0.
Do not replay those full-data queries as development or change their results.

When the semantic backend declares an identity property, native Node/Edge Match
returns maps containing only that property, plus the already requested scalar
columns. Direct compiler callers without an identity declaration retain their
old whole-object query. RDF and the lower path algebra remain unchanged. The
binding normalizer and bind filter still access the same identity-property key.
Unknown/null/noncanonical identities remain failures; do not synthesize IDs,
filter invalid rows silently or relax source identity requirements.

For valid declared identities, the normalized row depends only on the returned
identity fields and selected scalar fields. Projection is outside the native
predicate/path subquery. Therefore normalizing and applying binding-set DISTINCT
after full-object projection or identity-map projection yields the same set.
Parallel edges retain their distinct canonical IDs. Each bind filter reads the
same property value before returning the same normalized rows. Compilation adds
only O(number of identity columns × identity-name length) rendering, at most
three columns per edge Match. Candidate construction, ordering, one-shot selection
and the documented Ptime planner bounds do not change. Neither ranking optimality
nor total execution speedup is implied.

Allowed scope: two Match compilers, their small shared rendering helper, semantic
compiler option wiring, dedicated focused tests and a tiny live boundary/report.
Forbidden: baseline changes, prompt/LLM tuning, catalog or model rebuild, oracle
selection, budget increases, modifying historical inputs/results, or broad
regression campaigns. Prove identity/parallel-edge/scalar/invalid-identity
behavior, direct legacy and RDF boundaries, and bounded-query wrapping. Then
execute a tiny real native primitive check and one affected dual-store slice.
Reuse frozen stores; no data reload or model call. Compare deterministic payload
bytes with the saved matching tiny run if input/query correspondence is verified;
do not call a one-run timing change a statistically established speedup.
