# D206: explicit GPU fallback for the frozen Qwen3-32B interface

Status: implementation and focused checks pass; broad regression and actual
alternate allocation are pending. H100 remains the preferred resource.

## Goal and scope

The user authorizes compatible alternate GPUs when H100 is unavailable. Job
3799513 is still pending, with the scheduler currently estimating a September
10 start at 09:29 Eastern / 21:29 Beijing. That estimate is not an actual start
or a promise. The latest live node observations show gput069 with two of four
L40S GPUs allocated, 24 of 48 CPUs allocated, and 176 GiB of host RAM allocated
out of 251,000 MiB. This is a potential two-GPU/8-CPU/64-GiB allocation, not a
reservation. Other usable L40S nodes observed have all four GPUs allocated;
gput067 is drained. The DGX node has all eight GPUs allocated.

Implement explicitly selected hardware profiles and a separate L40S deployment
specification. Keep the original 18 questions, catalog, prompt, model revision,
BF16 precision, context length, candidate/repair bounds and semantic metrics.
Allowed files are the GPU/serving/environment adapters, new deployment and
experiment files, shell entrypoint, tests and records. Do not edit the frozen
H100 spec or original remote checkout. No inference, catalog rebuild, fact load,
algebra change or experiment retry is part of configuration validation.

Acceptance requires actual shell arguments matching the chosen profile,
all visible devices validated before model loading, the complete recorded
experiment accepted under its own hardware contract, legacy behavior passing,
and at most one runnable experiment during a resource switch.

## Implemented profile

The separate `l40s-pipeline2-v1` contract requests two L40S GPUs on one node.
It retains BF16 Qwen3-32B and a 12,288-token context, using tensor parallel size
1, pipeline parallel size 2 and the local multiprocessing executor. The launch
checks all CUDA-visible devices through the serving interpreter: exactly two,
L40S name, at least 45,000 MiB per device and native BF16-capable architecture.
This does not guarantee remaining runtime capacity; vLLM startup/readiness must
still succeed. Device observations are recorded with the job ID, model name,
compute capability, per-device capacity, and parallel sizes. The old single
host-GPU observation cannot substitute for this two-device record.

The optional profile registry also describes H100 and 80-GB A100 single-device
configurations; the old unprofiled H100 contract and legacy result format retain
their prior behavior. Only the L40S alternate contract/spec is provided here.
The model launcher emits no extra arguments for the legacy contract. Empty
optional argument expansion is portable to the Mac's older Bash as well.

The new spec changes only experiment/run labels and the deployment contract
path/hash (plus the corresponding freeze hash). Its new freeze is
`645c31b2d86972d0eeb7df00820019d3f109302315eb1ace5fa19ac9da36aeff`;
contract hash is
`c5c21770a036aab7100704b11f526bc35de23543fe94dad8531c12bc74ec18b1`.
It remains semantic-only and has no paper admission. Different GPU/parallelism
results must be identified as a deployment change, especially for latency and
numerical reproducibility; do not pool them as identical H100 measurements.

The existing environment and whole-run readers accept the new explicit profile
only after validating every recorded device and parallelism field. They keep
the historical H100 requirement for legacy contracts. This does not attest a
remote process merely from a matching record. No tokenizer or model-output gate
is removed, and all failed question outcomes remain in the denominator.

## Validation

The first focused run had 245 passes and one launcher-test failure: the test
omitted the frozen model revision and hit an existing empty-array behavior in
Mac Bash. The corrected test pins the revision as the real handoff does. The
new optional parallel array was also made portable and a legacy actual-shell
case was added. Final targeted GPU/runtime/environment checks: **105 passed in
7.17s**. Actual shell tests use explicit CUDA/vLLM doubles; they verify arguments
and rejection before launch, not GPU inference. Both original and L40S profiles
also exercise the full offline 18-question runner and independent whole-run
reconstruction, including retained failures and corrupted records.

Broad regression is running in original session 51749, log
`/tmp/xgap-d206-full.log`. Harness and all 22 examples passed, 23/23 entrypoints;
session 94699 exited 0. Continue the original full-test session; do not restart
because an observation yields no output.

## Remote transition

Prepare and verify the complete new checkout and prelaunch pins before changing
3799513. Recheck its actual state and alternate resources at the transition.
If the original has started, follow it rather than dispatching a duplicate.
If it remains pending, preserve its scheduler evidence and cancel only the
pending original, confirm it is terminal, then submit the alternate once.
Any ambiguous cancellation/submission response must be inspected, never retried.
Existing packages, source and submission evidence remain intact.

The new L40S entrypoint is
`scripts/slurm/run_grailqa_guarded_l40s.sbatch`; the ordinary guarded handoff,
model/tokenizer pinning and post-completion audit remain applicable to the new
specification. Actual submission/start/inference acceptance remains pending.

## Primary implementation evidence

- [NVIDIA L40S specifications](https://www.nvidia.com/en-us/data-center/l40s/)
  give 48 GB memory, BF16 support and no NVLink. Two cards are required to keep
  this 32B BF16 deployment without reducing precision.
- [vLLM 0.11.1 Qwen3 implementation](https://github.com/vllm-project/vllm/blob/v0.11.1/vllm/model_executor/models/qwen3.py)
  declares pipeline-parallel support and uses pipeline-rank-aware layers.
  Actual Pioneer startup remains the compatibility gate.
- [CWRU hardware overview](https://sites.google.com/a/case.edu/hpcc/hpc-cluster/hardware)
  is background inventory; live Slurm output is authoritative for availability.
