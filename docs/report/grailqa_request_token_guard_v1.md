# GrailQA request-token checking: implementation and measurement boundary

## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: plan; implementation of the existing engineering prerequisite
- Origin Date: 2026-09-09
- Verification Status: offline software tests only; Qwen request fit and live
  semantic effectiveness remain unmeasured
- Version Label: grailqa_request_token_guard_v1

## Purpose

The [inactive output-contract draft](grailqa_output_contract_revision_v1.md)
adds necessary serialization guidance, but its fixed 8,192-input + 4,096-output
reservation does not prove that an assembled request fits. This implementation
supplies the missing local measurement and a separate opt-in transport guard.
It is not a new model run, a repair of the old result, or a new scientific gate.

The zero-candidate diagnosis remains two independent problems: invalid output
contracts/structural references, and catalog/retrieval/prompt visibility. Token
checking prevents an overlong request from being sent; it does not fix either
problem or establish improved accuracy.

## Implemented components

| Component | Executable behavior | Does not establish |
|---|---|---|
| `LocalPinnedChatTokenizer` | Loads one explicit existing snapshot locally; records revision, tokenizer/config files, effective template and library versions; applies the actual chat template without truncation | Agreement with the separately running vLLM service |
| `ChatTokenBudgetGuard` | Checks exact assembled generation/repair payload, model, unchanged output reservation, measured input and total context; returns a payload-bound receipt | Semantic validity or permission to call a model |
| `TokenBudgetedCandidateProvider` | Privately wraps the existing provider; checks before transmission and records only actual delegate attempts | Activation of any old preflight/paper entrypoint |
| `grailqa_request_tokens` | Builds every frozen generation request through the existing catalog, prompt view and request factory, and inventories local counts without credentials or transmission | Future repair lengths, readiness, or full-150 authority |

The local tokenizer profile supports fast, tokenizer.json-backed text
tokenizers with a declared, recognized loading footprint. It includes Qwen's
vocabulary/merges files and optional model configuration in its identity.
Unknown footprints and slow-tokenizer fallbacks fail explicitly. Snapshot-file
symlinks may resolve only within the same model cache. No model weights are
loaded, no package is installed, no remote code is trusted, and no missing
tokenizer is downloaded.

The tokenizer renders `messages` with tokenization and the generation prompt
enabled, preserving the request's `enable_thinking` value. Schema text already
included in the user message is counted once. The structured decoding schema
is not separately appended. Unsupported tool, multimodal, truncation, or
template overrides are rejected instead of approximately counted.

Both successful and denied checks bind the complete request hash. The original
payload remains unchanged. No character-count fallback, context truncation,
reduced output reservation, increased context, or automatic retry is allowed.
Tokenizer files, template, and library identities are checked for drift.

## Call accounting and repair

The unchanged base provider records a request before delegating transport.
Simply raising in a transport wrapper would therefore count an unsent request.
The new adapter reconciles this only for its own exact typed denial, and only
when the base artifact contains the exact attempted prefix plus one refused
trailing request. A mismatch raises an accounting error rather than trimming
evidence heuristically.

- Initial refusal: zero generation calls, zero repair calls, no transmitted
  request records.
- Repair refusal: the actual first call and response remain; the unsent repair
  adds no model call or token usage.
- Transport failure after delegation: that attempted call remains counted.
- Valid bounded repair: the existing one-generation/at-most-one-repair policy
  remains unchanged; the full repair messages are checked before sending.

Check receipts remain separate from transmitted-request records. The adapter's
public last invocation and any raised provider error expose the same corrected
artifact. Responses, reported usage, request IDs and elapsed time are retained.
Sequential reuse resets state; overlapping invocations are rejected.

## Offline inventory entrypoint

From the checkout, `PYTHONPATH=src python -m xgap.experiments.grailqa_request_tokens --help` lists five mandatory
inputs: `--spec`, `--repo-root`, `--tokenizer-snapshot`,
`--tokenizer-revision`, and `--output`. There is no implicit new-draft or model
activation. The tokenizer path must name an existing cache snapshot whose
directory name equals the explicit 40-hex revision, not `main` or a moving ref.

Use the interpreter that already has the serving tokenizer libraries installed.
Select the same explicit catalog/reachability environment overrides as the
intended preflight. The command calls existing readiness without requiring
credentials, and passes only inference questions and retrieved prompt views
to the request builder. Reference reachability is retained only as gate
metadata. The model bundle and deployment contract must match their spec hashes.

Each frozen query remains in order, including missing-question/retrieval or
tokenizer failures. Over-budget counts are measured failures; missing inputs
are unavailable, never zero or estimated. Reports identify token fit separately
from readiness and always record zero external calls, no authority, and
`paper_result=false`. Exclusive output creation refuses existing files and
protected source, dataset, model, catalog and tokenizer locations.

Repair inputs depend on responses not yet generated. A successful generation
inventory is therefore insufficient to approve a later repair, and every
actual generation/repair still needs the per-send guard. This command neither
creates nor submits a remote job.

## Integration and remaining work

The existing provider, request factory, preflight/paper scripts, frozen bundles,
specs, schema and grounder remain byte-for-byte unchanged. The adapter is
available for explicit composition but is not silently installed into the old
entrypoints. Any reviewed new live path must bind it to the serving environment,
persist check receipts separately, and include its local work in end-to-end
accounting.

Before fresh model measurement, the server must establish that the pinned local
tokenizer/template/library configuration agrees with the actual serving path.
The current environment contract pins vLLM and model snapshot selection but
does not prove those additional parity facts. The inventory explicitly reports
`remote_serving_parity_verified=false`; passing it cannot manufacture parity.

The inspected local Qwen cache is absent. Tests include a tiny actual local
tokenizer roundtrip, but its five-token synthetic vocabulary is not the Qwen
tokenizer or a GrailQA token measurement. The actual 18-query input lengths,
whether the clarified prompt improves generation, the separate retrieval
repair, and all missing cross-dataset experiments remain unfinished.

See [research-question/dataset coverage](research_question_dataset_coverage_v1.md)
for the recorded FinBench evidence and the missing semantic/physical cells.
Do not infer new scientific selections, paper admission, or execution authority
from this engineering implementation.

The subsequent [guarded development entrypoint](grailqa_guarded_development_entrypoint_v1.md)
adds explicit record bindings and durable per-query/per-send journals without
changing the old entrypoints. It still cannot certify serving tokenizer parity
and defaults to refusing execution. No new model result or author approval is
implied by that integration.
