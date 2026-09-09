# CWRU H100 + vLLM Experiment Backend

## Scope

M13-E2 makes the existing OpenAI-compatible structured-candidate boundary
deployable as a Slurm job on CWRU Pioneer. It does not change candidate
semantics, `PathPatternQuery`, logical lowering, `c_sem`, M11, the GP model,
reference equivalence, or backend compilation/execution. It does not run or
prepare a new 150-query pilot.

The frozen deployment condition is:

| Field | Value |
|---|---|
| Cluster / scheduler | CWRU Pioneer / Slurm |
| GPU request | `gpu`, `gpu2h100`, `gpu:1`, 8 CPUs, 64G |
| GPU | one scheduler-selected NVIDIA H100 NVL |
| Environment | `/home/hxc859/venvs/xgap-vllm` |
| Python / torch / CUDA / vLLM | 3.11.5 / 2.9.0+cu128 / 12.8 / 0.11.1 |
| Model | `Qwen/Qwen3-32B` dense |
| Serving | bfloat16, max length 12288, memory utilization 0.90 |
| Endpoint | `http://127.0.0.1:8000/v1` |
| Thinking | request-local `enable_thinking=false` |
| Structured output | unchanged M13-E1 JSON Schema |

The machine-readable contract is
`experiments/environments/cwru_pioneer_qwen3_32b_vllm.json`. Qwen3-30B-A3B
and system-library changes are outside this milestone.

Documentation reconciliation on 2026-09-09: the current committed deployment
contract and runbook serve 12,288 context tokens, reserving 8,192 input plus
4,096 output. The earlier 8,192 serving value in this table was stale. This
correction changes no deployment, model bundle, token budget, or recorded run.

The one-H100 environment (approximately 95.8 GiB VRAM) was manually validated
before this repository integration: model loading, `/v1/models`,
`/v1/chat/completions`, non-thinking mode, and JSON Schema output all worked.

## Execution Boundary

```text
Slurm allocation
  -> verify clean checkout and frozen runtime
  -> resolve one existing HF cache snapshot
  -> start loopback-only vLLM
  -> bounded /v1/models readiness poll
  -> tiny non-thinking JSON Schema smoke
  -> persist CWRU environment artifact
  -> run an explicitly supplied XGAP command/spec
  -> hash run artifacts and stop vLLM through an EXIT trap
```

The generic wrapper accepts an experiment spec and an argument-vector command;
it does not evaluate a shell command string and does not hard-code GrailQA. The
GrailQA wrapper first runs the existing M13-E1 offline reachability gate. A
failed gate exits before loading Qwen3-32B.

## Provider Integration

`ModelConfig.model_env` is an optional, hash-preserving extension. Existing
bundles omit it and retain their frozen hashes. The CWRU bundle uses:

```text
XGAP_LLM_BASE_URL
XGAP_LLM_API_KEY
XGAP_LLM_MODEL
```

The defaults remain loopback URL, local placeholder credential, and
`Qwen/Qwen3-32B`. The generic provider still assembles the exact request. The
CWRU bundle adds only the configuration-owned parameter:

```json
{"chat_template_kwargs":{"enable_thinking":false}}
```

The exact request record therefore contains model, messages, sampling bounds,
the strict XGAP JSON Schema response format, and the non-thinking setting.
Credential values are supplied only to transport and are not serialized.

## Model Revision

The launch script resolves `XGAP_MODEL_REVISION` or the shared cache's
`refs/main` to an existing snapshot hash. It uses no download API. The resolved
hash is passed to `vllm serve --revision`, written to `model_revision.txt`, and
included in `cwru_environment.json`. Multiple unreferenced cached snapshots
fail explicitly instead of choosing silently.

## Reproducibility Artifacts

Each CWRU job directory contains, as applicable:

- `job.log`, `vllm.log`, `vllm.pid`, and `model_revision.txt`;
- `vllm_structured_smoke.json` with the exact credential-free request;
- `cwru_environment.json` with git, Slurm, host, GPU, driver, Python, torch,
  CUDA, vLLM, model/revision, serving, spec, model-bundle, and prompt hashes;
- `results/` from the selected experiment;
- `artifact_inventory.json` and `run_status.json` written during cleanup.

The M13-E1 preflight additionally embeds the CWRU environment record in its
own `run_manifest.json` when `XGAP_RUN_ENVIRONMENT_FILE` is set.

## Verification Boundary

Normal pytest verifies provider payloads, schema preservation, non-thinking
configuration, timeout behavior, revision resolution, secret exclusion,
manifest fields, Slurm resources, scheduler-selected nodes, shell syntax, and
cleanup declarations. It does not allocate an H100 or start vLLM.

The remaining manual prerequisite is a clean CWRU checkout with the validated
shared environment/model cache and M13-E1 catalog-v2/reachability artifacts
that pass the offline gate.
