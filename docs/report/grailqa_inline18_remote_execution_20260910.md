# D204: resume the frozen inline18 run through the restored portal

Status: original launch submitted Slurm job **3799513** once, then D206
cancelled it while still PENDING to perform the user-authorized GPU fallback.
Replacement **3799649 is RUNNING** on two L40S GPUs as of September 10 at
16:17:42 Beijing. See [current deployment](cwru_gpu_fallback_v1.md); the
observations below preserve the original launch history. Input catalog, model
revision and frozen spec were pinned before submission. The offline source
package is separately uploaded and hash-verified, but was never executed.
The D203 candidate/native-answer slice is complete at
882a54e; the broader system goal remains active.

## Frozen scope before deployment

Use the previously delivered, unchanged inline18 release to obtain actual
Qwen3-32B model results. A new OnDemand terminal became available this turn.
Read-only `squeue` returned no jobs; `sacct` since September 9 lists only the
preserved 3796877/3796878/3796968/3796988 jobs. The inline18 package and isolated
checkout did not exist at that initial observation.

The Chrome extension initially rejected local file access. The original
6,237-byte package was published as an immutable repository artifact; a proposed
server download was not attempted after GitHub authentication failures became
visible. The offline remedy and later restored upload are recorded below.

Allowed changes: this immutable handoff artifact and execution observations in
status/roadmap/engineering documentation. No production query/provider code,
frozen catalog/model/spec, source facts, old server working tree or scientific
population changes. Do not create another catalog or auditing milestone.

Acceptance: one verified package transfer, original prelaunch input pinning,
at most one `sbatch` invocation, actual job ID/state/log evidence, and preserved
terminal outcomes. Never resubmit after uncertain submission or external
failure. Poll the original job and inspect authoritative state. Keep raw model
outputs and failures; admit results only through the existing whole-run gate.

## Artifact identity

- Package: `experiments/handoffs/xgap-inline18-6b32b97.zip`.
- Bytes: 6,237.
- SHA-256: `fe56a9323d93f2f8a386b637f2511359a825d5b2502d30b9884b1f5df46525cc`.
- Execution commit: `6b32b973d4fd1a979b714570d3edcd2e684c1b07`.
- Isolated checkout: `/home/hxc859/XGAP-inline18-6b32b97`.
- Fixed v1 catalog: `/home/hxc859/xgap-data/freebase/grailqa-local-catalog-v1/preflight18`.
- Scope: 18 questions, at most 3 candidates and one repair per question;
  one H100, 8 CPUs, 64 GiB, four hours. No backend execution, catalog rebuild,
  model download or full-150 run is authorized by this package.

The package is byte-identical to the previously delivered local ZIP, whose
submission helper was reread before deployment. This is release transport,
not a new implementation requiring another full production regression.

## Observations

The supported terminal input is the iframe's visible `log` region; the
snapshot's textbox did not resolve as an actionable control. One long typed
read-only command stopped partway through; the visible prefix was inspected,
only the remaining suffix was appended, and the complete command was checked
before Enter. No partial command was executed, and no submission occurred.

The user subsequently uploaded the original ZIP and ran its launch helper in
the shared terminal. Three observed HTTPS clone attempts stopped at GitHub
authentication. No Slurm submission was reached by those attempts. The final
observed terminal returned to a prompt. The agent did not type into credential
prompts or handle passwords. The proposed anonymous raw-GitHub transfer was
not attempted after this new authentication evidence appeared.

## Verified offline transport remedy

Prepared `/Users/anthonyche/Developer/XGAP-deliverables/xgap-inline18-offline-6b32b97.zip`.
It contains a self-contained Git bundle with the original frozen branch/commit,
the unchanged audit helper, and a submission helper with only two transport
changes: check the bundle SHA-256 before cloning and clone its local path
instead of GitHub HTTPS. All execution commit, catalog, model, question, token,
resource and submission-count settings remain unchanged. The original package
and any conflicting server checkout are never overwritten or removed.

| Identity | Value |
| --- | --- |
| Offline ZIP bytes | 3,261,891 |
| Offline ZIP SHA-256 | `5e85c79352c25cb7f056df346fbc0c42d4470eb3058bf0291b36ce16a5340a61` |
| Source bundle bytes | 3,275,670 |
| Source bundle SHA-256 | `3c9ca1aaa4919a303177743e953be9d006d7b44368da27d070918aea6476d3e0` |
| Verified source commit | `6b32b973d4fd1a979b714570d3edcd2e684c1b07` |
| Verified tree | `19d8ed717a277f48785993a14a783e733ccad1dc` |

Local validation verified the complete Git bundle, performed a real independent
single-branch clone and detached checkout, confirmed the exact commit/tree and
empty working-tree status, and checked both shell scripts' syntax. No network
or model call was involved. The original ZIP remains identical and the harness
check passes. Production query/provider code is unchanged, so the already passed
D203 full regression was not repeated for transport packaging.

The user explicitly confirmed file-URL permission was enabled. After browser
reconnection, the agent uploaded the offline ZIP through the OnDemand file
chooser to `/home/hxc859` and verified its SHA-256 in a separate hpc6 terminal:
`5e85c79352c25cb7f056df346fbc0c42d4470eb3058bf0291b36ce16a5340a61`.
No settings were changed by the agent. The package has not been extracted or
executed: a fresh prelaunch conflict check found the target checkout now existed.

The user concurrently completed GitHub authentication in the original hpc5
terminal. Its clone and detached checkout succeeded, and a separate `rev-parse`
confirmed exact commit `6b32b973d4fd1a979b714570d3edcd2e684c1b07`.
At the latest observation, the original launch had not returned to a prompt;
its Python process (PID 1378524 on hpc5) was alive after 4:05 elapsed with 10.2%
CPU. Input pins and a Slurm submission had not yet been observed. The initial
agent-owned queue check was empty. Preserve this original running helper and
follow its outputs; do not execute either helper again, modify the checkout,
or interpret a completed clone as an actual model run. The offline ZIP is now
an intact fallback artifact, not the active launch route.

While transfer was pending, the two remaining old research reports were fully
read. `report_1.md` is an M6-era snapshot whose global absence claims are
historical. `kqapro_artifact_audit.md` reports an M13-B/M9-specific restricted
fragment; newer directed support does not retroactively validate KQA mappings,
execution or its old coverage counts. Keep the FinBench/GrailQA research plan.

## Actual submission and current experiment gate

The original helper completed input pinning at **2026-09-10T06:39:19.642365Z**
and recorded its single submission intent at **06:39:33.966284Z**. The user
terminal reports job **3799513**, `submission.stdout` contains that ID and
`submission_exit_code.txt` is 0. The agent did not invoke another helper or
`sbatch`. This supersedes the earlier prelaunch-process observation.

Observed `squeue` and `scontrol` state: PENDING, reason Resources, 0 restarts.
Resources are one H100 (`gpu2h100` feature), 8 CPUs, 64 GiB and a four-hour
limit. Slurm's server-local submit time is 2026-09-10T02:39:34, corresponding
to 14:39:34 Beijing. Its projected start is a scheduler estimate, not evidence
of execution. Keep the exact job ID and do not resubmit while queued.

Pinned inputs read from the actual remote record:

- Runner: `6b32b973d4fd1a979b714570d3edcd2e684c1b07`.
- Catalog: `fa07c25b60558f81faef4116c768115d6e9419015f5e3e455f927f62820308e8`.
- Catalog manifest: `fbe88846f8088d24df3d046980580e16ec3e716a6de952d83226645fcf52176c`.
- Spec: `0d3e89524b3422f7d8816e383b7ea7483265f61f531586a8a80a516edfa223e7`, original 18 question IDs.
- Cached Qwen revision: `9216db5781bf21249d130ec9da846c4624c16137`.
- Tokenizer identity: `30ddfe60f09d8f868d925fbb8a416966cfb36b7d8b930c4a19c9eb1192ab9960`.
- `automatic_retries=0`, `backend_execution=false`, `paper_result=false`.

Remote submission artifacts stay in `/home/hxc859/xgap-inline18-6b32b97`.
Slurm stdout/stderr:
`/home/hxc859/XGAP-inline18-6b32b97/slurm-xgap-grailqa-guarded-3799513.out`.
The original job was cancelled while pending and has no model result to audit.
Follow replacement 3799649 and use its separate
`/home/hxc859/xgap-inline18-l40s-ada3431/audit.sh` once after COMPLETED 0:0.
A failure requires diagnosis and preserved evidence, not resubmission.
