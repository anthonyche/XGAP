# D198: inline provider evidence admission

The independent, read-only gate in `grailqa_inline_evidence.py` reconstructs
the provider boundary from retained query states, request/response ledgers,
transport events, and candidate feedback. It does not send a model request,
read a reference answer or catalog, load a tokenizer, or execute a backend.
The input bundle must explicitly select `inline_grounding_v1` and the retained
provider configuration must match it, including the endpoint and timeout.
Ambient model and endpoint environment overrides cannot alter the audit.

## What is admitted

Each invoked query retains its outcome, including failed repair, first/repair
token refusal, and first/repair transport timeout. The auditor verifies:

- exact invocation copies, task and provider identity, contiguous generation
  and repair requests, the at-most-two attempt boundary, and checked payload
  identities before the journaled transport attempts;
- one terminal transport event per attempt, raw response equality, provider
  request IDs, and usage totals recomputed from provider-reported envelopes;
- the initial request rebuilt from its inference question, retrieval identity,
  visible prompt view, endpoint contract, and explicitly selected model bundle;
- every materialization receipt, including earlier failed wire structures,
  against the original response and exact request/payload identities;
- typed/grounded feedback independently recomputed with the existing pure
  validators, including its detail, index and source representation;
- each repair body rebuilt from the original wire content and reproduced
  validation error, with no repair after a valid candidate or transport error;
- the final consumed materialized body, the failed/successful provider outcome,
  extracted ledger copies, and per-query state seals.

The auditor rejects rehashed derived bodies, dropped or reordered history,
changed feedback, a substituted repair request, missing transport evidence,
incorrect call counts (including booleans), and inconsistent state copies.
The run reader checks the five input files' byte hashes before and after the
audit. Its CLI writes only to standard output; no source tree is rewritten.

## Scope and remaining gates

This is **provider evidence admission**, a component of the planned independent
whole-run verifier. It is not the full new-protocol experiment admission gate.
The report always declares `whole_run_admitted=false`, `paper_result=false`,
`semantic_metrics_verified=false`, `token_counts_recomputed=false`, and
`server_identity_verified=false`. Uninvoked queries are listed separately and
are not admitted by this component. An empty provider subset is rejected.

An initial token refusal has no transmitted request or materialization. Its
zero-attempt record and retained refusal are checked, but its complete payload
cannot be reconstructed from current failure-state artifacts; that limitation
is explicit per query. Token-check ordering and hash bindings are verified,
not the tokenizer's numerical correctness or server parity. External errors
have only an error-type event, so their exact remote cause is not attested.

The journal provides consistency evidence, not cryptographic authenticity.
Coordinated rewriting of all source observations is outside this gate. The
whole-run gate must still bind the producer commit, frozen spec/population,
catalog/retrieval provenance, environment and lifecycle, serving-tokenizer
receipts, candidate/semantic metrics and evaluation-only reference boundary.
No existing preflight, paper admission, bundle, spec or launch default is
silently redirected through this new gate.

## Use

Run from an independent checkout after retaining the complete guarded output:

```sh
PYTHONPATH=src python -m xgap.experiments.grailqa_inline_evidence \
  --run-root /path/to/guarded-output \
  --model-bundle models/qwen3_32b_vllm_cwru_grailqa_inline_v1
```

Exit 0 means the retained provider subset passes this gate. Exit 2 means
missing or inconsistent evidence. Both failed and successful model outcomes
can have valid evidence. A caller must also check the claim boundary and use
the separately frozen model-bundle hash required by its experiment protocol.

## Local acceptance

The new suite has 41 tests covering ten legitimate outcome paths, 25 corruption
cases, read-only file/CLI behavior, state seals and ledger extraction. The
focused regression has 215 passing tests. Full regression passes **2587 tests,
with 37 skips, in 596.33 seconds**. The harness and all 19 acceptance examples
pass. Exact source and log identities are recorded in
`experiments/artifacts/d198_inline_evidence_local_20260909.json`.
All fixtures are synthetic; no model quality,
catalog coverage, remote service, or paper result is claimed.
