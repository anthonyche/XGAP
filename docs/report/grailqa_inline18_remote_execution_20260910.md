# D204: resume the frozen inline18 run through the restored portal

Status: IN PROGRESS. The D203 candidate/native-answer slice is complete at
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
