# Fixed-plan execution parallelism

2026-09-26. Independent preparation alongside submitted job 3886776; no changes
to its code, inputs, budgets or execution. No new method or backend measurements.

`scripts/prepare_ch6_parallel.py` reads the pinned small-real release, selection,
six manifests and sealed outcomes. It keeps all 48 × five method positions.
For each internal method that executed a final plan, it freezes that exact plan,
selected query and source identities for scheduler parallelism 1/2/4/8. It does
not replan or filter by correctness or observed speedup. Nonanswers and missing
artifacts retain explicit states. TS remains a fixed RDF reference; native TS
remains unsupported. These are within-query execution measurements, not query
throughput or end-to-end model/planning measurements.

`--artifact-root` plus `--original-prefix` relocate pinned archived files;
`--evidence-root` separately locates the run's `units/` tree. The output directory
must be new. Missing results stay pending, and a later archive produces a new
recipe instead of overwriting one. `execute_frozen` uses the existing scheduler
and checks source identities. Its caller must provide an already guarded,
observed source session and retain identical CPU/RAM, source snapshot, cache
protocol and time/call/row budgets across levels. Execution measures observed
overlap, answers and source/coordinator costs; static ready width is only a plan
descriptor, not observed parallelism.

Two boundary tests passed: a selected plan survives an unsuccessful outcome,
source identity changes are rejected, and nonanswers/missing artifacts are
explicit. An old 3885860 sealed core yielded its original 14-node final plan
without queries or replanning. The local small-release metadata preview yielded
240 positions: 192 pending internal outcomes, 24 TS RDF references and 24 native
unsupported positions. Every measurement remains null. The preview is at
`/Users/anthonyche/xgap-data/outputs/xgap-parallel-pending-20260926-v1/recipe.json`,
SHA-256 `f2f8f45bacc508cc321c8a02cc1ed436c866d656683cab5f55439c79ceba22cf`.
It is not a recovered 3886776 result or an executable server launch package.

Next: receive 3886776's sealed outcomes, freeze its actual selected plans, then
bind the independent parallel run to the existing guarded source-session runner.
No new graph service, model request, answer query or Slurm job was invoked here.
