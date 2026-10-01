# INT-4: explicit semantic projection to typed entity answers

Scope frozen on 2026-09-11 at parent ed2a7c3. This closes the deterministic
R-E/E1 boundary from a prepared meaning through ordinary P1 to entity answers.
It does not supply the still-missing answer position in the frozen GrailQA150
candidate format or change that semantic-only protocol.

Accept only an already bound, two-operator Traverse → Project program with one
root and exactly one projected field, `answer`. Its expression must explicitly
name a path node using `first`, `last`, or a positive one-based position. There
is no default answer position, inference from variable names, or lookup in a
reference query. Check numeric positions against the fixed one-to-three-hop
path before any backend call, including when the eventual answer is empty.
Preserve all constraints; existing compiler admission still applies.

The source and every declared replica must share the explicit resource-triple
encoding and snapshot. This is a deployment assertion, not proof that a remote
endpoint actually loaded the snapshot. Reuse the existing inference-leakage
check on the complete program, including metadata. No gold/reference input is
accepted by this adapter. Program, projection, source and encoding identities
are recorded before dispatch.

Use BoundSemanticExecutionTool and run_agentic_semantic_query with an empty
resolution registry: binding, ordinary polynomial placement, policies, backend
plugins and scheduler remain the same. No new optimizer, algebra, catalog,
provider or automatic retry is introduced. Keep the complete agent result and
failed tool observations. Successful final `answer` IRI strings must round-trip
through the declared namespace and canonical ID encoding, then become RdfTerm
bindings consumed by the existing AnswerProjection. Do not pretend that raw
strings were backend-native typed RDF results.

Finite answer limits reject overflow before normalization; existing native
resource-row limits retain their overflow sentinel. Failed or missing execution
never becomes an empty answer. A successful complete empty result is legitimate.
Report adapter end-to-end time including answer normalization and retain the
agent's separate planning/acquisition/execution accounting. There are zero model
calls in this prepared-meaning track. Typed execution success is neither verified
NL meaning nor official GrailQA EM/F1. Independent scoring remains downstream.

Allowed changes: one experiment adapter, its independent tiny tests, and current
decision/status/report/evidence documents. Frozen150/48 populations, existing
toy/model fixtures, the submitted08e4b3b package, and core operator/compiler/P1
semantics are unchanged. Acceptance is the new tests exercising actual ordinary
planning and compiled SPARQL on tiny RDF plus admission/failure cases. No new
native service is necessary: this changes only local entry/output conversion,
and INT-1 already accepted the unchanged native resource boundary. Do not repeat
INT-1/INT-3 or the original model/admission gates.
