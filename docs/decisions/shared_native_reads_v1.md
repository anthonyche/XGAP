# Identical complete native reads within one plan

2026-09-14. Motivated by three exact duplicate read pairs in the saved native
cost diagnostic, not by a hypothetical general-purpose cache requirement.
Scope: runtime-plan normalization, the new practical strong domain, tiny tests
and one native gate. No algebra/operator, baseline, legacy default, model weight,
source-data, discrepancy or paper-population change.

The research question is whether avoidable identical source invocations can be
removed while retaining the same query answer. The factor is within-plan source
sharing; measured outcomes are actual call count, response bytes and independent
answer equality. Timing is recorded, but a new cold session is not a speed test.

Only zero-input REMOTE_QUERY nodes are eligible. Require an explicit, consistent
backend/source/snapshot identity and a known deterministic compiler's complete
artifact. Compare all node execution parameters, native text, language, compiler
descriptors, decoding/capability metadata and artifact values; ignore only its
invocation artifact_id. No text normalization or semantic guess. Decline unknown
compilers, file-backed artifacts, retrieval budgets, distinct backends or
bindings. Remote bind queries are never shared by this pass. Hash/config identity
is a declared snapshot contract, not a live-server immutability certificate.

Visit nodes by stable ID and retain the first eligible representative. Rewire
consumers of an identical later read to it, preserving all local operators,
schemas, field mappings and semantic operator provenance. If that would make a
consumer have duplicate input ports, leave the later read independent. Native
answer roots are also kept independent, so named root identities stay unchanged.
This conservative rule avoids inventing an alias operator or collapsing a direct
self-join into a unary node. Record every removed-to-representative mapping.

Under the same frozen snapshot and deterministic complete-query contract, each
removed read returns the same relation, including row multiplicities, as its
representative. Substituting that input for each consumer preserves its function;
induction through the unchanged acyclic DAG preserves every answer. Shared source
failure skips affected consumers and is reported; it never triggers a second
attempt. Runtime failure probability is not part of an answer-equivalence claim.
Existing roots-only retention waits for all consumers before releasing rows.

The pass adds no candidate combinations. For V runtime nodes, E dependencies and
B serialized artifact bytes, sorting/identity construction and consumer checks
are polynomial; a conservative bound is O(V*(E+B)+V log V) time and O(E+B+V)
space, including canonical identities and the output. Remote-call count cannot
increase. No latency approximation ratio or global-optimum guarantee follows.
Admission retains the old conservative pre-sharing call budget; this release
does not rescue a plan already rejected under that budget.

Enable in the new practical domain's feasible baseline and optional alternatives
before scoring; refresh actual plan features. The ordinary legacy one-shot domain
defaults to shared_native_reads=False and remains byte-for-byte unchanged. If
no pair qualifies, return the original plan. Both modes can use the reduction;
it changes physical work, not semantic authorization or model confidence.

Acceptance: independent five-node/eight-edge two-hop bag count14 with one actual
in-process SPARQL call; both strong modes' feasible fallback and roots-only
execution; exact candidate-count/legacy compatibility; failure propagation,
snapshot/descriptor/value/budget/backend separation; named roots/direct input
ports preserved. Then one new real native request on the frozen8-node/16-relation
fixture must return the four-row gold with11 source calls. No repeat of the
previous six-cell diagnostic, no fitting or result-driven selection.
