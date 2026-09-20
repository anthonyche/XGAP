# T7: approved experiment delivery within 72 hours

Material Passport: experiment execution, existing approved RQ1–RQ5/E1–E20 plan,
research prototype, real measurements only. User authorized goal execution on
2026-09-20. Start: 2026-09-20 20:30 Asia/Shanghai. Target complete delivery:
2026-09-23 20:30; useful measured results should be available by 48 hours.
The app goal was created as ACTIVE on this authorization; the previous stale
paused-goal note in the T6 report is historical.

## Execution order

1. 0–8 hours: repaired live-model/native admission; freeze and run a new FinBench
   SF0.1 24-case development pilot. Seal selection before reference evaluation;
   no answer-nonempty selection and no reuse of T3 campaign results.
2. 8–24 hours: freeze FinBench formal configuration from its pilot; complete bounded
   Freebase/FedShop data and method admission; pursue unmodified ARUQULA+FedUP
   configuration/lookup/dependencies. An unresolved external method does not stop
   XGAP measurements on an independently admitted dataset.
3. 24–48 hours: execute admitted primary method/epsilon/ambiguity comparisons;
   retain all attempted failures, non-answers and censoring. Freeze remaining
   pilot-informed sample sizes before opening formal outcomes.
4. 48–66 hours: finish approved feedback/cost-contrast and scale comparisons;
   prioritize complete paired cohorts and source-coverage correctness.
5. 66–72 hours: seal measured tables, family-cluster uncertainty, figures and
   observed policy cases; check visual/metric provenance and publish reproducible
   report with every missing panel explicitly identified.

These are execution targets, not a promise that unresolved dependencies will
work. Scope remains the approved three datasets and E1–E20. Missing panels are
unfinished work, not evidence of completion or zero-valued results. Do not shrink
or change research claims to conceal them.

## Resource and integrity bounds

- Use the existing authorized Qwen service only; no new paid services. The first
  repaired admission allows two new generations in a new code/version directory.
- Each dataset's pilot has 24 unique base cases, 2 current modes, one initial
  measurement per cell; at most 48 NL model generations per dataset. Controlled
  cells make no model calls. Repeat/scan release is frozen after pilot, not automatic.
- Initial pilot process: 90 seconds per method, 1 GiB worker RSS observation,
  2 GiB owned sources RSS observation, 64 backend calls, 20 seconds/backend call,
  64 MiB/response and 256 MiB/phase; two-hour batch ceiling. Record censoring.
- Keep at least 6 GiB disk free; at most 8 GiB new retained experiment artifacts
  across the 72-hour effort. Prepare/serve datasets serially on this machine.
- Complete formal manifests must declare cell/model/time caps before launch;
  nested per-run budgets cannot silently replenish a study-wide resource budget.
- Only blocker fixes and focused contract tests. Preserve raw failures and code
  pins; new-version diagnostic attempts are separately labelled. No baseline
  prompt/search/repair tuning, no repeated broad regression, no advantage-driven
  workload selection or significance-driven sample extension.

The simulator remains private and metered. Operational query loss retains the
full declared coordinate denominator and is independent of answer EM/F1. Offline
reference/catalog/load costs stay separate. Native/RDF panels cannot mix speedups.

## Immediate output checkpoints

- Fresh model/native readiness receipt after representation fix.
- FinBench public request/family manifest, private intent/reference pins, disjoint
  pilot/formal grouping, sampling evidence, and 48 attempted paired pilot cells.
- Dataset and baseline capability table updated from actual setup/execution.
- Formal release and analysis ready per admitted dataset; never wait for a perfect
  general-purpose implementation before producing the first real results.
