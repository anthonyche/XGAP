# D207: detect unhealthy CUDA devices and exited model servers

Status: software acceptance complete. Full regression in session 60312 exited
0: **2,922 passed / 38 skipped in 673.86s**, log `/tmp/xgap-d207-full.log`.
No corrected job has been submitted; no actual healthy GPU launch is inferred.

## Observed failure and scope

Actual D206 job 3799649 acquired two L40S GPUs on gput069 but failed during
engine initialization with `CUDA error: uncorrectable ECC error encountered`.
Its first GPU inventory already reported three volatile uncorrectable ECC
events on GPU 1. Device-name, memory and architecture queries succeeded; those
queries do not exercise a CUDA kernel. After the API process exited, the old
readiness checker continued until its deadline. The job ultimately finalized
FAILED / 1:0 at 16:34:57 Beijing without producing any question result. Preserve
its complete checkout, package, logs and six run artifacts.

D207 changes only the CUDA startup and model-readiness boundary and its tests.
The model revision, BF16 precision, context, 18 questions, frozen v1 catalog,
semantic prompt/candidate/repair budgets, existing algebra and native backends
remain fixed. The explicit L40S deployment spec/contract hashes are unchanged;
the new source commit identifies this operational correction.

## Implemented behavior

After every CUDA-visible device passes the explicit profile's capacity and
architecture checks, the launcher allocates one BF16 value on each device,
writes zero with a CUDA operation, and synchronizes that device. A CUDA failure
identifies the device and stops before the model daemon starts. Each small
tensor is released, including when a kernel/synchronization fails. This runs
only for the explicit GPU profiles; legacy unprofiled launch arguments and
dependency behavior remain unchanged. A successful tiny operation does not
guarantee that a GPU will remain healthy or have sufficient model/KV capacity.

The shell readiness entry now requires its launcher-written positive PID and
passes it to the bounded checker. Each polling iteration verifies that process
still exists; on Linux, zombie/dead process states also fail immediately.
An exited process stops before another HTTP poll or sleep. A live process still
must expose the exact requested model, and the existing readiness deadline
still applies. The general Python/API readiness entry can omit PID tracking
for compatibility; the owned-process shell workflow cannot silently omit it.
Permission and observation errors are not converted into healthy status.

## Validation

Focused checks completed in session 17451: **51 passed in 20.58s**. Cases
exercise allocation, kernel and synchronization errors on the second device,
healthy per-device order, actual launcher rejection before daemon creation,
legacy launch behavior, dead-server polling, exact model identity, invalid PIDs,
a real owned child process exit, Linux zombie parsing, and the actual readiness
shell preserving the retained error log. CUDA/vLLM responses in these tests are
explicit stand-ins, not actual GPU results. Harness and all 22 examples passed
in session 10429, 23/23 entrypoints. Broad acceptance passed **2,922 tests with
38 skips in 673.86s**; the original session 60312 was closed with exit 0.
Skipped/live behavior remains unverified. See the durable
[acceptance receipt](../../experiments/artifacts/d207_startup_health_acceptance_20260910.json).

The independently prepared submission helper is exercised as actual Python
code with controlled subprocess responses. Seven cases pass: normal, another
active XGAP job, changed predecessor state, excluded node returned by test-only,
rejected resources, uncertain submission, and a previous submission intent.
Only the normal/uncertain cases attempt submission, once each; no case cancels
any job. These are fixtures and do not establish a real scheduler submission.

## Corrected deployment gate

Prepare a fresh exact-commit checkout and distinct package. Verify the bundle
and server archive hashes and compare input pins against the original frozen
run before submission. Preserve 3799513 CANCELLED and 3799649 FAILED as terminal
predecessors; refuse another active XGAP job or a previous submission intent.
Use explicit `--exclude=gput069` and `--no-requeue` on both test-only and the
single real submission. The environment-only exclusion attempt still selected
gput069 and is not an accepted way to exclude it. A read-only explicit test
estimated gput070 at 17:30:23 Beijing; this is not a reservation or health proof.

The new helper gives cold startup a finite **1,800-second readiness bound**
instead of the previous 900 seconds, recorded in its submission intent. The
observed prior startup spent several minutes importing and initializing its
API/engine/workers before the hardware error, so a dual-worker cold start needs
separate headroom. Dead-process detection prevents this longer bound from
masking an already exited daemon. The overall four-hour allocation and all
question-time/inference settings remain unchanged. This bound is an engineering
choice, not measured startup speed or a scientific result.

Only after full software acceptance and verified transfer, invoke the new
helper once with its explicit corrected-deployment argument. Inspect uncertain
responses rather than retrying. Once the new job is COMPLETED 0:0, use its own
existing whole-run audit once. On failure, retain the complete failure before
making another engineering decision. H100 remains preferred when available;
actual hardware identity must remain attached to any L40S result.
