# Match row constraints and a complete recorded Interpretation cohort

2026-09-12, parent0b7c56c. R-E/LINK addresses a concrete mismatch between real
model output and executable conditions. This is bounded research-prototype work,
not new path algebra or general NL repair. Original five recordings and gold
remain immutable; no new model generation is planned for this milestone.

Previously Match/Traverse accepted path Condition AST constraints, while Filter
accepted binding-row conditions. Add one explicit semantic composition: a Match
named constraint with the row DSL's `op` discriminator applies to the normalized
binding rows produced by that same Match. Existing `kind` path constraints retain
their original native meaning. A predicate cannot carry both discriminators.
Each named constraint remains conjunctive with the other named constraints.

Compilation emits the existing native Match and NORMALIZE_NODE_BINDINGS, followed
by the existing COORDINATOR_FILTER when row constraints exist. No conversion to
path predicates occurs: row equality/null/numeric rules remain those of the
typed binding profile, including Boolean/numeric distinction. Row fields must
already be declared by Match's entity_field/properties; missing fields and
malformed predicates fail during local compilation before native observations.
No property is invented or fetched because it appears in a model filter.
Original semantic program, hard-constraint hash, source identity and ownership
are preserved. Entity resolution still requires the existing enforcing identity
contract. Traverse row constraints remain unsupported.

The new filter belongs to the same SemanticSourceFragment and semantic operator,
so ordinary capability admission, P1 local-option compilation/scoring, observation
cost and selected execution include it. Old Match without row constraints keeps
the existing runtime plan. The compiler adds at most one filter per Match and
checks the explicit condition tree/field set; no placement enumeration is added.
This is a finite language extension, not proof that the earlier model complied
with the old prompt. It supports semantics now instead of relabeling old outcomes.

The native runner gains an explicit recorded-cohort mode: keep the original five
IDs and exact recording contexts, call each recording once, retain parse/compile
failures in the denominator and execute admitted programs independently. Each
actual result is compared with the unchanged expected answer. No successful-only
subset is reported. Candidate-matrix checks, repeated native reference queries
and the old unrelated slice are outside this new cohort measurement; the affected
real-model native executions supply this milestone's external-boundary evidence.
Interpretation failures have an explicit prebackend zero-call branch. For other
outcomes use actual bind-plan-execute observation metrics, never the legacy
counter's default zero for missing metrics. Stop on external/backend failure or
unknown call count with remaining IDs unattempted; never retry. A swallowed
compile/execute exception with no phase/cost evidence is unknown, not free.
Keep old fail-fast development gates unchanged by default. Cohort completion,
strict-correct count and all-correct success are separate.

Acceptance: focused new compiler semantics (mixed path/row, typed values/null,
missing fields, old source-plan compatibility) and one affected ordinary-P1 tiny
slice; focused cohort bookkeeping/stop behavior; then exactly one fresh native
run over all five original v3 recordings, zero model calls. Preserve all failures,
all costs, source hashes, exact rows and service cleanup. Do not require all five
model interpretations to succeed before measuring a cohort's real outcomes.
