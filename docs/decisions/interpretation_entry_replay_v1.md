# T2-B: independent Interpretation entry and response replay

2026-09-11, frozen on174393d before implementation; accepted after focused, native and final broad gates.

The first common question entry accepts an explicit provider, a question and
permitted context, then validates one semantic DAG/source-assignment response
before invoking the existing frozen resolution/planning/execution chain. A
provider can leave typed holes; it cannot provide native queries or authoritative
entity resolution. Explicit caller hard constraints must survive unchanged at
their named operators. Ordinary NL meaning accuracy remains independently scored,
not inferred from structural admission or execution success.

Reuse DeterministicSemanticIntake as the first executable provider. Extend its
constraint template with an optional executable predicate without changing old
template behavior. The two tiny authored template families cover the existing
five B01–B05 questions; original graph, gold meanings, bindings, target queries
and expected answers remain frozen. This is controlled phrase-based intake,
not a general NL parser or a true-model quality result.

Keep a small provider request/response journal: exact input plus version context,
raw structured output (including invalid output), declared usage, or an explicit
provider failure. Replay consumes matching recorded calls once, with no fallback
provider and zero new external calls/tokens; historical usage is separate.
Changed input/version, exhausted or unused recordings are explicit errors.
This is a provider-boundary replay, not a claim of general backend transcript
replay or of a new model deployment. No automatic repair/retry.

Scope: semantic intake and new Interpretation contract, provider journal, new
question entry, tiny input templates, focused tests and existing native harness.
No new algebra/operator, backend optimizer, GrailQA build/scan, model transport,
historical benchmark rewrite, or additional guard/audit framework.

Acceptance: NL→typed program/constraints independently compared with old gold;
program→frozen resolution→native answers and independent targets; malformed
program, dropped/changed hard constraint, unavailable provider and missing
catalog stop before backend execution; replay a saved malformed response and
provider failure without re-invoking the source; version/request mismatch is
explicit; permanent old slice, focused/daily and one final full acceptance gate.
Real-model Interpretation, general tool/backend replay, legacy GrailQA runtime
migration and the full system/evaluation goals remain subsequent obligations.
