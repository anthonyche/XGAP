# D200: complete guarded inline development-run reconstruction

Status: **LOCAL SOFTWARE ACCEPTANCE COMPLETE**. No actual live run has yet
been admitted by this gate; no new model or answer measurement is claimed.

Implementation checkpoint (2026-09-10): all seven executable layers now exist
in the new guarded reconstruction, token evidence, accounting, evaluation,
run-input and whole-evidence modules. Focused tests: **184 passed in 17.39s**,
including actual offline catalog construction + runner output, 38 resealed
corruption cases, all-failure denominators, zero-call retrieval misses and the
sampling-number fix. Full regression completed with **2700 passed, 37 skipped
in 625.92s**. The harness and all 19 acceptance examples pass. The full suite
was observed to completion in its original session, not restarted. Logs are
`/tmp/xgap-d200-full.log`, `/tmp/xgap-d200-focused-all.log`, and
`/tmp/xgap-d200-examples.log`; the durable acceptance receipt is
`experiments/artifacts/d200_guarded_whole_evidence_local_20260910.json`.

The public entrypoint is `python -m xgap.experiments.grailqa_guarded_evidence`.
Required explicit arguments are `--run-root`, `--repo-root`, `--spec-path`,
`--expected-commit`, `--expected-spec-freeze-hash`, `--catalog-root`,
`--expected-catalog-hash`, `--expected-catalog-manifest-sha256`,
`--reachability-root`, `--tokenizer-snapshot` and `--tokenizer-revision`.
Capture the expected catalog manifest digest from the preserved v1 source
before launch and retain it separately: the canonical catalog hash excludes
SQLite bytes, whereas this manifest binds the actual database digest.
Do not copy an expected digest from an unadmitted run merely to make it pass.
The tokenizer must be locally available with the recorded files, template and
library versions. Audit on a compatible source checkout and preserve the
original absolute catalog/reachability/cache locations. No checkout switch,
network fetch, credential lookup or permissive CLI override is provided.
Write stdout into a fresh audit artifact outside the original run directory;
any exception returns nonzero and a redacted non-admission record.

After acceptance, the next milestone must be an actual bounded model/service
experiment and answer-execution progress, not another catalog rebuild or an
open-ended series of auditing components. The user explicitly challenged the
disproportionate catalog focus on September 10. Keep the original XGAP federated
execution objective central; the GrailQA catalog is a front-end adapter issue.

Scope amendment during actual-runner testing: allow the two continuous sampling
parameter comparisons in `grailqa_guarded_environment.py` to treat frozen JSON
integers 0/1 as numerically equal to ModelBundle's normalized floats 0.0/1.0,
while still rejecting booleans and nonfinite values. The original inline spec
otherwise fails before a first send. No spec bytes, values, budgets, inference
logic, defaults or scientific definitions change; add explicit regression cases.

## Goal and scope

Bind the D197 inline output contract and D198 provider-history component to a
complete independently reconstructed development18 run. Keep the preserved
v1 catalog fixed after D199's zero-gain comparison. Allowed changes are new
read-only evidence/reconstruction modules, their tests, an explicit audit
entrypoint/runbook, and status/decision documentation. Existing runner/spec/
model defaults, scientific populations, semantic definitions, budgets, raw
records and paper-authority gates remain unchanged.

Acceptance requires all of the following, not just a manifest comparison:

1. The exact producer commit, development spec, model bundle, environment,
   finite call limits and outer/inner terminal statuses agree. Required files
   are regular, no failure marker is present, and source snapshots are stable.
2. All question IDs/order/text and catalog identities agree with explicit
   inputs. Actual catalog retrieval and prompt construction reproduce every
   retained query context, including uninvoked retrieval failures.
3. D198 reconstructs original/derived response and repair histories. The new
   gate independently rebuilds candidate rows, typed/grounded outcomes,
   lowering capability and ontology scores with the shared pure semantic
   primitives, without calling the inference producer or another model.
4. The fixed local tokenizer independently recounts generation and repair
   payloads, including refusals. Retained server-probe receipts bind each
   projected request and token-sequence hash. This remains preprocessing
   evidence at probe time, not serving-process or model-weight attestation.
5. Query lifecycle, token/probe/transport ledgers and totals reconstruct
   exactly. Timing remains a recorded observation; no audit claims to rerun
   the original clock or turn work totals into a fresh latency measurement.
6. Only after inference reconstruction, references are opened for independent
   component matching, failure classification and metric aggregation. All 18
   failures remain in the denominator; the reachable subset is diagnostic.
7. Offline actual-runner fixtures and coordinated corruption cases pass,
   followed by the complete offline suite and all acceptance examples. A
   later exact-commit live development run remains separately observable.

The public gate must fail closed when tokenizer/catalog/source evidence is
unavailable. Synthetic dependency injection belongs only in offline tests;
it must not be exposed as a CLI bypass that admits a real run.

This gate may admit a complete **development** observation, including zero
semantic matches. It cannot authorize full150, prove the historical c_sem
anchor design, establish GrailQA answer correctness without backend execution,
or promote any result to a paper claim.
