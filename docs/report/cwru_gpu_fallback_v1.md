# D206: explicit GPU fallback for the frozen Qwen3-32B interface

Status: software acceptance and the single-job resource transition complete.
Alternate job **3799649 is RUNNING** on gput069, with two L40S GPUs. It started
at **2026-09-10 04:17:42 Eastern / 16:17:42 Beijing**, three seconds after
submission. Actual model output and whole-run acceptance remain pending.
H100 remains the preferred resource for future eligible allocations.

## Goal and scope

The user authorizes compatible alternate GPUs when H100 is unavailable. Job
3799513 was pending, with the scheduler then estimating a September
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

Broad regression completed in original session 51749, exit 0: **2,908 passed /
38 skipped in 661.11s**, log `/tmp/xgap-d206-full.log`. Harness and all 22
examples passed, 23/23 entrypoints; session 94699 exited 0. Do not repeat these
successful checks without a new code change or unresolved concern.

The accepted producer `ada34316f11778f41d4b69560bc4d47e27d77d4e` is pushed.
An independently cloned exact bundle and operator package are retained at
`/Users/anthonyche/Developer/XGAP-deliverables/xgap-inline18-l40s-ada3431-v2.zip`.
Archive size is 3,464,379 bytes; SHA-256 is
`45d4cb60127996ff277e8406018089baad5e8db9350cc98591945ccbab9dba69`.
The v2 helper checks cancellation through the user's queue rather than relying
on an individual cancelled ID remaining queryable. The original v1 local ZIP
is retained and was not uploaded. Four process-boundary fixtures cover success,
an original already running, cancellation unconfirmed, and submission timeout;
each preserves exactly the allowed number/order of mutation attempts. These
fixtures make no real Slurm call. The v2 package was uploaded to `/home/hxc859`;
its actual server SHA-256 matches. The isolated checkout is exactly `ada3431`,
and catalog/tokenizer pins were completed before submission. See the
[receipt](../../experiments/artifacts/d206_gpu_fallback_20260910.json).

## Remote transition

The first `sbatch --test-only` accepted gput069 and estimated an immediate
start; its displayed prospective ID 3799639 is **not a submitted job**.
The switch helper was invoked once after exact terminal-input verification.
It checked unchanged inference pins, repeated the resource precheck, observed
3799513 still PENDING, saved its scheduler state, cancelled only the pending
original and confirmed cancellation before submitting the alternate once.
The returned real job ID is **3799649**. The original checkout, package and
submission artifacts remain intact. No experiment ran on the cancelled H100
allocation and no duplicate experiment was launched.

Actual `scontrol` reports RUNNING, zero restarts, gput069, two GPUs, eight CPUs,
64 GiB and a four-hour limit. Submission was 04:17:39 Eastern and start was
04:17:42. Slurm reports its default `Requeue=1`; the XGAP helper itself performs
no automatic retry and has an exclusive submission-intent guard. Retain both
facts rather than describing the scheduler setting as disabled.

The job log passes the 12,288-token budget and frozen runtime checks: Python
3.11.5, torch 2.9.0+cu128, CUDA 12.8, vLLM 0.11.1. It observes two NVIDIA L40S
devices with 46,068 MiB each and starts the pinned Qwen3-32B service. This is
actual allocation/startup evidence, not yet inference or scientific acceptance.

The new L40S entrypoint is
`scripts/slurm/run_grailqa_guarded_l40s.sbatch`; the ordinary guarded handoff,
model/tokenizer pinning and post-completion audit remain applicable to the new
specification. Output root is
`/home/hxc859/XGAP-inline18-l40s-ada3431/runs/cwru-grailqa-guarded-3799649`;
Slurm log is `slurm-xgap-grailqa-l40s-3799649.out` in that checkout.
After COMPLETED 0:0, run the alternate package's `audit.sh` once. On failure,
retain evidence and diagnose rather than rerunning the switch or experiment.

## Primary implementation evidence

- [NVIDIA L40S specifications](https://www.nvidia.com/en-us/data-center/l40s/)
  give 48 GB memory, BF16 support and no NVLink. Two cards are required to keep
  this 32B BF16 deployment without reducing precision.
- [vLLM 0.11.1 Qwen3 implementation](https://github.com/vllm-project/vllm/blob/v0.11.1/vllm/model_executor/models/qwen3.py)
  declares pipeline-parallel support and uses pipeline-rank-aware layers.
  Actual Pioneer startup remains the compatibility gate.
- [CWRU hardware overview](https://sites.google.com/a/case.edu/hpcc/hpc-cluster/hardware)
  is background inventory; live Slurm output is authoritative for availability.
