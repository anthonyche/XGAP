# GrailQA guarded development entrypoint and next experiment sequence

## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: plan and bounded engineering implementation
- Origin Date: 2026-09-09
- Verification Status: offline software integration; no new Qwen or backend
  measurement, no paper admission or execution authority
- Version Label: grailqa_guarded_development_entrypoint_v1

## What this repairs

The new `grailqa_guarded_preflight` entrypoint composes the existing semantic
inference/evaluation functions with the explicit local request-token guard.
It does not change retrieval, candidate normalization, grounding, semantic
constraints, metric definitions, or the previously recorded 18-query result.
Old preflight/paper entrypoints, prompts, model bundles and specifications are
unchanged. Selecting the output-contract draft remains an explicit decision.

Every query gets a fresh provider bridge. Before each generation or bounded
schema repair can reach transport, its query ID, check index, payload hash,
tokenizer identity and token decision are appended, flushed and fsynced.
Actual transport return evidence is also journaled before a response can
produce another request. A failed write stops execution rather than retrying.
Final invocation receipts retain the original transmitted requests, raw
responses, usage and latency. A local refusal is not a transmitted request.

The runtime stores each completed inference state before advancing to the next
query. Retrieval misses have no stale checks from the preceding query. A fatal
failure retains partial records and an incomplete status when persistence is
still possible; a missing final receipt means the complete call total is
unknown, not zero. No automatic resume or replacement run exists here.
For an incomplete run, `completed_inference_query_count` counts only the fully
journaled prefix whose state and completion event both finished. An interruption
between those writes can leave one additional state row without a completion
event; it is not silently counted as a fully completed query.

Checks/diagnostics are additional files. The frozen legacy failure taxonomy is
not rewritten: its empty-response classification may still say malformed
output, while `guard_diagnostics.jsonl` explicitly identifies local token
refusals. Both must be read together. Completion means all specified protocol
steps finished, not that candidate validity, accuracy, or scientific claims
passed. An all-negative development outcome can complete normally.

## Environment and execution boundaries

Before the first send, the new environment checker binds the current clean
runner commit, Slurm job and hostname to the recorded environment; binds the
exact spec bytes/freeze, prompt, model bundle, deployment contract and effective
provider parameters; and requires the explicit tokenizer snapshot to belong
to that model's frozen cache. Model/base-URL overrides, stale job environments,
wrong-model snapshots, changed budgets and unexpected serving parameters are
rejected. It performs no service probe or model call.

These are **record bindings**, not proof of the running service's tokenizer or
chat template. The existing environment record lacks that complete serving
attestation. Consequently the runner defaults to refusal. Its only currently
implemented execution mode requires an explicit
`--allow-unverified-serving-tokenizer` development acknowledgement and an
exact `--execute-development-spec-sha256` value (the spec's canonical
`freeze_hash` field, not its file-byte hash). The flag is not an author
receipt and has not been selected for a new CWRU run. It cannot satisfy the
pending parity prerequisite or authorize the 150-query paper experiment.
All outputs retain `remote_serving_parity_verified=false` and
`paper_result=false`; no strict-parity mode is fabricated.

The runner calls the normalized parser and the same `_infer_one` and
`_evaluate_preflight` implementations. The latter opens reference interpretation
content only after all inference states are complete. Earlier reachability
metadata remains an existing readiness gate, not a model input. This run still
has no graph-backend execution. The provider's existing at-most-one schema
repair is preserved; failed external actions are not automatically retried.

## Explicit entrypoints and artifacts

`scripts/server/check_grailqa_request_tokens.sh` is an **offline** helper, not
a scheduler submission or service launcher. It requires all six inputs:
`XGAP_REPO_ROOT`, `XGAP_PYTHON`, `XGAP_GRAILQA_TOKEN_SPEC`,
`XGAP_GRAILQA_TOKENIZER_SNAPSHOT`, `XGAP_GRAILQA_TOKENIZER_REVISION`, and
`XGAP_GRAILQA_TOKEN_OUTPUT`. It uses one existing interpreter and one existing
snapshot, preserves catalog/reachability overrides, enforces offline library
mode, and refuses existing/symlink outputs. It does not install or download.

`PYTHONPATH=src python -m xgap.experiments.grailqa_guarded_preflight --help`
describes the separate execution API. All paths, the exact runner commit,
tokenizer revision and development-spec acknowledgement are mandatory. There
is no implicit choice of a new bundle, catalog or specification and no new
Slurm launcher in this milestone. Do not reuse an old paper submission receipt
or treat the entrypoint's presence as approval to submit.

The output directory must be new and outside protected source/input trees.
The initial manifest is immutable; final status is separate. Artifacts include:

- `run_manifest.json`, `readiness.json`, `environment_binding.json`, and
  `tokenizer_identity.json` before inference;
- append-only `query_events.jsonl` and `query_states.jsonl` during inference;
- the familiar retrieval/request/response/candidate/component/semantic/failure
  files and metrics after all inference, plus `token_checks.jsonl` and
  `guard_diagnostics.jsonl`;
- `run_status.json` distinguishing completed protocol from incomplete work.

The new manifest schema is deliberately not the old audit schema. A future
admission path must reconstruct the new journal; old audit success cannot be
borrowed. A transport-attempt event is pre-delegation intent, not proof that the
remote endpoint received it. Complete invocation receipts establish the normal
attempt ledger; incomplete runs require explicit reconstruction.

A narrow credential-value boundary refuses an outgoing payload containing
the current API key before sending. A response echoing that key is rejected
after the charged call without persisting its unsafe body or requesting repair.
Safe diagnostic events retain the failure boundary. This does not rewrite a
raw response into a purported valid result or promise a general secret detector.

Provider latency already includes token checking and pre-send/transport
journaling; do not add those costs twice. Tokenizer initialization is reported
separately. Inference wall time includes all per-query journaling, but does not
claim to be model-only latency or full service-startup-inclusive job time.

## Offline verification

The five new test modules pass **150 tests**, covering environment bindings,
durable provider journals, runner lifecycle, the unchanged real inference /
grounding path with synthetic fixtures, and the offline shell helper. Both
`examples/llm_boundary_demo.py` and
`examples/m15_llm_resolution_provider_demo.py` also pass without network use.
These checks establish software behavior, not GrailQA candidate recall or a
successful live repair.

Full repository regression: **1,615 passed, 36 skipped in 510.28 seconds**.
Both CLI help checks, shell syntax validation, and the staged whitespace check
also pass. Skipped tests are not counted as verified behavior. No remote job,
model request, backend measurement, artifact download or installation was made
for this milestone.

## Experiment sequence after engineering verification

1. **Measure the exact 18-query request fit on the existing pinned server
   tokenizer.** Resolve the actual serving parity gap; do not substitute
   reservation arithmetic or synthetic counts. Any unverified-parity diagnostic
   mode requires an explicit scope decision, not silent activation.
2. **Test only the output-contract clarification on the same development18.**
   Keep the query population, retrieval, prompt visibility, model and grounding
   fixed. Report provider completion, anchor/reference validity, validated
   candidates and semantic matches separately, including the five jointly
   reachable queries. Preserve failures. If candidates remain zero, inspect
   the concrete remaining failure instead of immediately scaling to 150.
3. **Repair coverage as a separate intervention.** Distinguish absent local
   catalog terms, retrieval misses and prompt exclusion. Change one identified
   construction/retrieval/packing mechanism in a new version; no gold injection,
   weakened validation or invisible expansion of token limits. Repeat the same
   development population and report both all-query and reachable-subset results.
4. **Complete both primary datasets' missing experimental paths.** FinBench
   still needs evaluated semantic inputs/ontology references and semantic
   controls. GrailQA still needs real federated placements, equivalent competing
   complete physical plans, answer correctness and physical controls. Reuse the
   core abstractions without relabeling the existing semantic-only runner as a
   backend experiment.
5. **Freeze and run the full cross-dataset comparison.** For every retained
   dataset, cover original EQ1 semantic quality, EQ2 epsilon tradeoff, EQ3
   planning/pruning, EQ4 execution/data movement, and EQ5 robustness. Bind
   shared populations, baselines, ablations, failures, query-level statistics
   and independent audits before measurement. Disclose development overlap in
   frozen150; selecting or repairing on those18 is not unseen test evidence.

The complete coverage obligations and baseline gaps remain in
[research-question/dataset coverage](research_question_dataset_coverage_v1.md).
The admitted FinBench physical campaign is retained. It supports its precise
profiling-cost comparison, not an isolated instance-memory advantage over
fixed-A/family-global selections or a complete semantic research conclusion.

There is no new experimental result from this integration. Fresh small-run
turnaround depends on authorization, tokenizer/serving validation and CWRU
availability; formal complete-study timing additionally depends on the missing
cross-dataset execution paths and scientific choices. No unsupported calendar
promise or deadline-driven deletion of required experimental cells is made.
