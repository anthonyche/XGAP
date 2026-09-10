# D204: resume the frozen inline18 run through the restored portal

Status: IN PROGRESS; offline code transport verified locally, remote transfer pending. The D203 candidate/native-answer slice is complete at
882a54e; the broader system goal remains active.

## Frozen scope before deployment

Use the previously delivered, unchanged inline18 release to obtain actual
Qwen3-32B model results. A new OnDemand terminal became available this turn.
Read-only `squeue` returned no jobs; `sacct` since September 9 lists only the
preserved 3796877/3796878/3796968/3796988 jobs. The inline18 package and isolated
checkout do not yet exist on the server.

The Chrome extension's file chooser rejected local file access. Do not change
browser permissions or retry that upload. Publish the identical, already
reviewed 6,237-byte package as a repository artifact and let the authorized
remote shell download it from an exact Git commit. This uses no browser access
to local files. Verify its existing SHA-256 before extraction or execution.

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

The browser extension needs user-enabled file-URL access for agent file upload;
that setting was not changed automatically. A question asking whether the user
has enabled it is pending. If available, transfer this offline ZIP and continue
the single submission; otherwise the one remaining transfer step is a manual
upload. Do not repeat the failed HTTPS clone or request a GitHub password.

While transfer was pending, the two remaining old research reports were fully
read. `report_1.md` is an M6-era snapshot whose global absence claims are
historical. `kqapro_artifact_audit.md` reports an M13-B/M9-specific restricted
fragment; newer directed support does not retroactively validate KQA mappings,
execution or its old coverage counts. Keep the FinBench/GrailQA research plan.
