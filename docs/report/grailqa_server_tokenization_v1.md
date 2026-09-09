# GrailQA per-request server tokenization and next experiment gate

## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: plan and bounded engineering implementation
- Origin Date: 2026-09-09
- Verification Status: offline software verification only; live Qwen request
  lengths, token equality and semantic improvement remain unmeasured
- Version Label: grailqa_server_tokenization_v1

## Objective and hypothesis

Make the next explicitly authorized development18 run diagnose the output
contract, not silently confound it with a different tokenizer, oversized
request, dropped provider attempt or incomplete evidence. The engineering
hypothesis is that inference is delegated only after the exact current payload
passes local limits and its ordered token IDs match the running service's
tokenization response. This is not a hypothesis that the model must produce a
correct interpretation, and a negative outcome remains reportable.

The full study still requires the original EQ1–EQ5 on every retained primary
dataset. This gate does not replace semantic evaluation with software audits,
change the scientific questions or shrink the study to already passing cells.

## Implemented boundary

The explicit `--verify-server-tokenization` mode wraps each generation and
actual bounded schema-repair payload. It first uses the pinned local tokenizer
and existing input/output/context budgets; local refusal causes no probe or
inference. A passing request is projected to the job-local `/tokenize` route,
with the same model, complete messages and frozen non-thinking chat settings.
Full inference-payload identity is retained separately, including decoding
parameters that are not chat-template input. The ordered token sequence, its
length, and the frozen server context limit must agree. Comparing only lengths
would not suffice. Local files/template identity is revalidated after the probe.

This implementation targets the pinned **vLLM 0.11.1** contract: the chat
tokenization and completion paths obtain the engine tokenizer and use the
shared chat preprocessing path; structured response-format constraints affect
decoding, not an extra appended prompt. See the pinned
[tokenization implementation](https://github.com/vllm-project/vllm/blob/v0.11.1/vllm/entrypoints/openai/serving_tokenization.py),
[request definitions](https://github.com/vllm-project/vllm/blob/v0.11.1/vllm/entrypoints/openai/protocol.py),
[chat implementation](https://github.com/vllm-project/vllm/blob/v0.11.1/vllm/entrypoints/openai/serving_chat.py),
and [shared preprocessing](https://github.com/vllm-project/vllm/blob/v0.11.1/vllm/entrypoints/openai/serving_engine.py).

Equality proves only the observed **payload preprocessing at probe time**.
It is not global model-weight identity, process attestation, or an atomic
guarantee against a restart between the probe and inference. Accordingly
`remote_serving_parity_verified=false` remains truthful. The old explicit
unverified development option remains distinct; choosing both or neither
modes is rejected. Neither CLI flag supplies scientific execution authority.

Both new-runner inference and tokenization transports accept only their exact
numeric loopback HTTP route, refuse redirects and environment proxies, and
make no automatic retry. The inference response is bounded. The public literal
`local` credential placeholder is exempt from content scans only on those
exact loopback endpoints: it is not a secret of the unauthenticated frozen
job-local service. Genuine supplied credentials, including short values,
retain their outgoing-payload and response-echo protections. Authorization
headers are not persisted.

## Outputs, accounting and failure behavior

- `query_events.jsonl` durably records probe intent before the HTTP call and
  its result/error before inference. Receipts contain safe counts and hashes,
  not arbitrary endpoint errors or raw token sequences.
- `server_tokenization_checks.jsonl` and per-query diagnostics distinguish
  local refusal, endpoint failure, ID/context mismatch and matched probes.
- Each query has at most two probes and two inference attempts: generation
  and, only when the unchanged provider invokes it, one actual schema repair.
  Probe timeout is 60 seconds; model limits remain the frozen bundle's limits.
- For 18 queries the ceiling is 36 probes plus 36 inference attempts, not a
  requirement to spend all 72. These are **per-query** external calls; the
  generic job's startup health/model-readiness polling is outside that total.
  No graph-backend query occurs in this semantic development entrypoint.
- Probe elapsed time is reported separately but already included in the
  provider's end-to-end latency. Do not add it twice. Tokenizer initialization
  and overall inference wall time remain separately labeled.
- A failed probe is charged even when no inference follows. Fatal persistence
  or accounting failures retain the partial journal and unknown final totals,
  rather than claiming zero calls, resuming or retrying automatically.
- Final-status publication failure attempts a separate exclusive
  `run_failure.json`; no old file is overwritten. A journal `run_completed`
  event covers the inference/evaluation lifecycle only. Successful CLI exit,
  completed final status and no failure marker are all required; if storage
  cannot retain either status or marker, completion is unavailable.

All scientific outputs remain `paper_result=false`. Existing audits do not
admit this new manifest or journal merely because fields look similar.

## Explicit CWRU handoff, not a submitted job

New files `scripts/slurm/run_grailqa_guarded_preflight.sbatch` and
`scripts/server/run_grailqa_guarded_preflight.sh` leave every old launcher and
frozen spec/model/prompt unchanged. They require explicit `XGAP_REPO_ROOT`,
`XGAP_PYTHON` (offline control interpreter), `VLLM_ENV`,
`XGAP_GRAILQA_GUARDED_SPEC`, `XGAP_GRAILQA_GUARDED_SPEC_SHA256` (canonical spec
freeze hash), and `XGAP_GRAILQA_GUARDED_RUNNER_COMMIT`, within a Slurm allocation.

The helper validates the exact clean runner, unique18 development scope,
readiness, deployment and cache bindings **before starting the model**. It
requires regular repository-contained spec and deployment-contract files,
matching the unchanged environment collector's relative-path contract. It
requires a fresh direct `runs/cwru-grailqa-guarded-*` output, preserving prior
evidence and rejecting symlink/output aliases. Post-startup it rechecks the
runner and uses the frozen serving environment's exact `bin/python` and the
launcher's resolved snapshot revision for tokenization/inference. It reuses
the existing service lifecycle, skips the generic extra inference smoke,
forces offline cache use, and never submits, downloads, installs or resumes.

Presence of this entrypoint is not permission to launch it. The new prompt,
specification, extra tokenizer probes and exact finite development scope must
be reviewed and separately authorized before the remote job. The local
implementation has not sent these requests to CWRU or any model.

## Next experiment and repair sequence

1. **Deterministic repair verification.** Retain the original 18-query negative
   evidence. Replay parser/grounder cases, measure exact request fit on the
   existing server cache, then compare server preprocessing in the authorized
   small run. Do not enlarge budgets or invent missing anchors to get a pass.
2. **Output-contract development18.** Test the separately versioned contract
   clarification while holding model, questions, retrieval, grounding and
   metric definitions fixed. Report complete-output/anchor/reference validity,
   legal-candidate coverage, semantic matches, calls/tokens/latency and all
   failure categories. Report all18 and the five previously jointly reachable
   questions separately; zero candidates in the latter is not explained by
   the other13 retrieval/visibility misses. This is development, not a paired
   confirmatory efficacy claim against a historical run.
3. **Coverage intervention, separately versioned.** Address the eight local
   catalog misses, four retrieval misses and one prompt-visibility miss using
   inference-available sources only. Test catalog construction, entity/relation
   retrieval and budgeted prompt packing separately. Preserve hard constraints
   and forbid reference-answer injection. A successful catalog build/audit is
   not proof that every required term is covered.
4. **Fill both datasets' missing paths.** FinBench needs semantic query/reference
   and ontology evaluation, not only physical selection. GrailQA needs real
   federated execution, equivalent complete physical alternatives and answer
   correctness, not only semantic generation. Then apply matched controls and
   ablations to both, keeping zero-current-query profiling and acquisition costs
   explicit for methods that claim those properties.
5. **Freeze the comparison, then measure.** For both retained datasets cover
   semantic quality, epsilon/coverage tradeoff, planning/pruning, execution/data
   movement and robustness, with shared populations and per-query statistics.
   Do not treat development18 reused within150 as unseen test evidence. Preserve
   the admitted FinBench campaign; any new comparison gets its own protocol.

The detailed obligations are in
[RQ/dataset coverage](research_question_dataset_coverage_v1.md). The first new
semantic result requires a real small run; full-paper readiness additionally
requires these missing paths and frozen comparisons. No elapsed-time promise
is inferred from offline test success or scheduler completion.

## Offline verification

The final focused run passes **340 tests**, including strict server-token-ID
checks, real provider/parser wiring with synthetic responses, safe transport
boundaries, exact local tokenizer checks and the actual new shell helper with
offline process doubles. This includes **42 handoff cases**, **73 inference
transport cases**, **66 tokenization cases** and **15 strict runner cases**.
Both offline LLM-boundary examples, CLI help, shell syntax and whitespace
checks pass. The collected full repository suite passes **1,853 tests with
36 skipped in 524.53 seconds**. Skipped tests remain unverified. After
collection, only one module docstring's indentation and documentation changed;
no executable behavior or test case was changed.

Synthetic transports/tokenizers test safety, accounting and parser wiring;
they do not establish any live GrailQA improvement or actual Qwen request fit.
The shell tests do not exercise a real GPU, service PID cleanup or remote
filesystem. Compatibility with the existing launcher was also source-reviewed;
one external-spec-path mismatch was corrected before model startup. No old
launcher, frozen model/spec/prompt, original response ledger or FinBench result
was changed.
