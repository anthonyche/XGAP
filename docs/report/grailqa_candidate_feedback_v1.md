# GrailQA bounded candidate-contract feedback

## Scope

D194 is a local implementation repair, not new model evidence or permission
to run full150. It adds an explicitly selected `typed_grounding_one_repair_v1`
policy to the guarded development runner. Historical runs and the default
`schema_only_v1` behavior remain unchanged. It requires D193's
`grailqa_canonical_semantic_grounding_v2` contract.

The same candidate parser, canonical grounding checks and typed semantic
validator assess a structured response against its exact request/prompt view.
Existing parser, envelope-shape and additional provider validators still run
first; this is not partial acceptance of malformed JSON or an invalid AST.
If at least one candidate passes, preserve the response and its siblings
without a quality retry. If none passes, send deterministic contract errors
through the provider's existing, shared one-repair budget. JSON/schema repair
and candidate-contract repair cannot each consume a separate extra attempt.
Transport errors and timeouts never trigger a repair.

No answer, gold interpretation, semantic-score threshold, ranking outcome or
logical lowering availability is used in feedback. A valid IN interpretation
does not become a repair trigger merely because M5 cannot execute it. This
does not implement that missing capability or establish answer correctness.

## Evidence and budgets

The initial response, repair payload and repaired response are retained in the
original invocation/event ledger. A separate candidate-feedback record is
durably written before a resulting repair may transmit, and binds the task,
request, exact prompt view and source structured-response hashes. A failed
feedback journal write is fatal; it cannot be caught as a repairable model
error. Unexpected internal assessment failures also stop without repair.

Each error detail is limited to 256 characters with an explicit truncation
flag. This only bounds the diagnostic text: the original response and complete
assembled repair request are never silently shortened. The same local and
serving-tokenization guard checks the whole repair request, including feedback.
A denied repair retains the original attempt cost and records the refusal.
Existing additional provider validators remain in the shared validation chain.

The new frozen development spec is
`experiments/specs/grailqa_semantic_preflight_contract_feedback_v1_cwru_qwen3_32b.json`,
with canonical freeze hash
`c1f86af67c91863ea4f22fb9425ff016e8a1a322c4787a14f33b887cf6fbb0d5`.
Only experiment/run identity, the explicit repair policy and the freeze hash
change from D193. The same 18 questions, model, prompt, catalog selection,
8192-input/4096-output token limits, timeout and at-most-two model attempts per
question remain. Existing tokenizer probes are charged separately. There are
no backend calls, new automatic retries, full150 authorization or paper result.

The policy is bound in the two-phase prelaunch record, run manifest, query
states, metrics, status/failure records and provider diagnostics. The completed
runner also exports `candidate_feedback.jsonl` from the durable per-question
records. Unknown or mixed policies fail before model startup/evaluation
reference reads. All questions, including failed or refused repairs, remain
in evaluation denominators. Final candidate evaluation concerns the final
response; earlier rejected responses remain diagnostic evidence, not extra
candidate samples or uncharged attempts.

The existing `api_call_completed` / `provider_success_rate` fields mean a
response accepted by the active provider contract, not merely HTTP transport
completion. With this opt-in policy they additionally require a typed/grounded
candidate. Do not compare that rate to the schema-only historical rate as a
pure infrastructure improvement. Transport responses, all attempted calls,
repair refusals and feedback defects remain separately visible in the ledgers.
Feedback assessment/journaling time occurs inside the existing provider
latency interval; do not add it again to end-to-end time.

## Read-only diagnosis, not an accuracy result

Uploaded job 3796877 `query_states.jsonl` has SHA-256
`f207a5d4e3563e391274ebc0109ce2906a5ea2a007b27f4b362823c1bd887c18`.
The existing replay helper verified the 18 request/response/view identities;
the feedback callback then assessed the 17 available structured responses.
Fifteen contain no typed, prompt-grounded candidate. Two contain four such
candidates in total and therefore do not request repair. The remaining query
has no structured provider response. No gold/reference content was read,
no model/backend was called, and the source bytes were unchanged.

Candidate-local issues comprise 33 slot-grounding errors, three actual
AST/declaration mismatches and two nonvisible AST terms; another three
responses fail shared grounding. These counts reproduce contract defects,
not their eventual repair success. The policy cannot recover terms absent
from the prompt, resolve unimplemented execution semantics or prove recall.
Do not claim those problems fixed from offline tests.

## Current CWRU boundary and next gate

The user installed PyArrow **25.0.1** in
`/home/hxc859/venvs/xgap-core/bin/python` and submitted CPU catalog-comparison
job **3796988** using the unchanged producer
`e39b98e109870f8910c1f2ec98348965bd272f30`. The user subsequently reports it
still running; completion and coverage improvement have not yet been supplied. Preserve the
failed 3796968 run and old catalog. Do not switch that checkout during the
active job or resubmit it automatically.

First obtain its terminal status and audited old/new coverage comparison.
Any next GPU test needs the chosen spec/catalog, exact code and bounded scope
explicitly identified; code publication is not submission. No full150 or
cross-dataset EQ1–EQ5 obligation is waived. Existing accepted FinBench
physical evidence is unaffected.

## Offline acceptance

Focused candidate/guard/runner/handoff tests: **334 passed**. Full default
offline suite: **2360 passed, 36 skipped in 595.67 seconds**. The LLM boundary,
semantic audit and M15 selective-resolution offline examples, guarded CLI
help, shell syntax and `git diff --check` pass. No new model, backend or
scheduler submission was used in this verification. Skips are not passes.
