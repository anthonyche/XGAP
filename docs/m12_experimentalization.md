# M12 Experimentalization

Implementation status: M12-A, M12-B, and M12-C completed; M12-D not started.

## Scope

M12-A freezes the experiment contracts around the existing deterministic
XGAP pipeline. M12-B adds a configuration-selected live/runtime input path:

```text
DatasetBundle + ModelBundle + ExperimentSpec
  -> mock provider + controlled alignment (M12-A)
     OR live structured provider + bounded runtime alignment (M12-B)
  -> deterministic M10 validation and frozen c_sem
  -> existing M11 physical planner
  -> runs/<run_id>/ reproducible artifacts
```

The experiment layer may load and validate artifacts, materialize run
directories, and invoke existing interfaces. It does not redefine logical
operators, deterministic lowering, M11 search, the M11 GP estimator, or M9
compiler support.

## Object Model

M12-A defines versioned, deterministically serializable objects for:

- `DatasetBundle` and normalized `QuestionRecord` values;
- `OntologyGraph`, aliases, entities, mappings, schema snapshots, and
  optional gold alignments;
- `ModelBundle` and `PromptArtifact` values;
- `SemanticDeviationConfig` and per-slot alignment evidence;
- `GPProtocol`, calibration references, and feature-schema references;
- `ExperimentSpec`, baseline and ablation configuration;
- `ExperimentMetrics` groups and explicit unavailable `MetricValue` values;
- `ExecutionProtocol`;
- `RunArtifactLayout` and `ExperimentManifest`.

Artifacts carry schema versions. Immutable semantic content uses canonical
JSON with sorted keys and SHA-256 hashes. Semantic hashes exclude resolved
absolute local paths.

## DatasetBundle Contract

The conventional layout is:

```text
datasets/<dataset_id>/
  dataset.yaml
  questions.jsonl
  ontology.yaml
  aliases.yaml
  entity_catalog.jsonl
  backend_mapping.yaml
  schema_snapshot.json
  gold_alignments.jsonl
  fragment_support.jsonl
  backend_load/
```

`dataset.yaml` identifies the dataset, version, provenance, controlled versus
external status, required and optional artifacts, and backend-loading paths.
A bundle loader resolves these paths without embedding dataset logic in the
planner. Missing required files fail. Missing optional files are recorded as
unavailable and are not fabricated.

A normalized question records its ID, text, split, source benchmark ID,
fragment-support class, and optional gold answers, logical form/query graph,
ontology slots, and metadata. Optional gold fields use explicit availability,
not invented empty labels.

Fragment support is frozen to these machine-readable values:

- `xgap_supported`;
- `compiler_unsupported`;
- `representation_unsupported`;
- `dataset_mapping_failure`.

Unsupported questions remain in the bundle so later reports can distinguish
overall coverage from accuracy on the supported subset.

## Ontology Contract

`ontology.yaml` records ontology ID/version, classes, relations, optional
properties, directed subsumption edges, domain/range metadata,
`max_relaxation_hops`, and explicit sibling admissibility pairs or a rule
reference. M12-A validates this artifact but does not implement a general
ontology reasoner.

Aliases, entity catalog records, backend mappings, and schema snapshots are
separate versioned artifacts. A schema snapshot includes source, version,
optional timestamp, and a stable content hash. Gold alignments are loaded only
when genuinely supplied; backend mappings do not imply gold alignment.

## Frozen Semantic Deviation

For an admissible ontology pair, `h_T(x,y)` is the shortest directed
subsumption-hop distance appropriate to the relation. With positive dataset
radius `H=max_relaxation_hops`, normalized distance is:

```text
d_T(x,y) = h_T(x,y) / H
```

Pairs beyond `H` are unrelated unless an explicit dataset admissibility rule
says otherwise. Siblings must be incomparable, have a nearest admissible
common ancestor, and be explicitly listed or accepted by a referenced rule.

Directional penalties are fixed:

```text
exact          0
specialization (1/3) * d_T(answer, query)
generalization (2/3) * d_T(query, answer)
sibling        1 * d_T(query, answer)
unrelated      infinity
```

The ordering at equal normalized distance is specialization,
generalization, sibling. All ontology-anchored query slots have uniform
weight `1/|S(u)|`. Uncovered slots, missing anchors/mappings/evidence,
unrelated terms, and inadmissible sibling relations yield symbolic
`infinity`. Finite aggregate deviation lies in `[0,1]`.

The default epsilon sweep is:

```text
0.00, 0.10, 0.25, 0.50, 0.75, 1.00
```

Experiments may override the complete list. `epsilon=0` permits exact
ontology semantics only. M12-A does not introduce learned slot weights.

## ModelBundle Contract

The conventional layout is:

```text
models/<model_id>/
  model_config.json
  prompt.json
  structured_schema.json  # required by live structured bundles
```

Model metadata records provider, exact model identifier/snapshot, endpoint
type, temperature, top-p, candidate cap, structured-output mode, token limits,
optional seed support, version metadata, and prompt reference/hash. The
prompt artifact records system text, few-shot examples, schema/ontology
context policy, structured-output schema, and its content hash.

M12-A supplies a development bundle backed by the existing M10 mock provider.
M12-B adds `models/qwen3_max_dashscope_live/` with the fixed
`qwen3-max-2026-01-23` snapshot and
`models/qwen3_vllm_template/` as a configuration-only OpenAI-compatible local
endpoint template. API keys are read from configured environment-variable
names and are never written to artifacts. M12-B does not download, deploy, or
fine-tune models.

## ExperimentSpec Contract

`ExperimentSpec` is the single declarative input. Required-now fields identify
the experiment, dataset bundle, model bundle, backend set, semantic-deviation
configuration, epsilon sweep, `T_max`, `K`, candidate cap, budget policy,
cost-estimator configuration, GP protocol, baseline, ablations, random seed,
execution protocol, metrics, and output root.

Future references such as real calibration observations, server statistics,
and benchmark-specific execution metadata are
optional and explicitly unavailable until supplied. Invalid combinations
fail, including exhaustive oracle without controlled scope, single-backend
without exactly one backend, direct text-to-query without one backend, and
contradictory duplicate baseline/ablation switches.

## GP Experimental Protocol

M12-A serializes, but does not execute, this protocol:

```text
calibration workload
  -> sampled complete physical-plan executions
  -> D_0
  -> fit RBF GP hyperparameters once
  -> freeze hyperparameters for evaluation
  -> update posterior between tasks only
```

The target remains `log C_exec(Psi)` for executed complete plans. Partial
states receive no artificial observation labels. Calibration configuration
records split ID, sampling policy, plan count, seed, backend scope,
observation artifact reference, and repeated-measurement policy. Evaluation
uses the existing M11 feature-schema reference and explicitly missing
statistics. M12-C now implements D0 collection/calibration and the online
update lifecycle described below.

## Baselines And Ablations

Frozen baseline identifiers:

- `full_xgap`;
- `random_feasible`;
- `mean_only`;
- `no_pruning`;
- `no_online_update`;
- `single_backend`;
- `exhaustive_oracle`;
- `direct_text2graphquery`.

The direct baseline is a configuration boundary for one question, the same
base model bundle where possible, one direct native query, and one backend.
It does not use interpretation enumeration, ontology relaxation, physical
planning, GP learning, BnB, or Nash ranking. No direct-query live model is
connected in M12-A.

Frozen ablation switches:

- `no_uncertainty`;
- `no_pruning`;
- `no_online_learning`;
- `no_semantic_bound`;
- `cost_only`;
- `no_nash`.

M12-A validates and serializes these identifiers. Their full execution is
M12-D scope.

## Metrics

The versioned metric schema retains the three M12-A nullable groups and adds
an optional M12-B live-generation group:

- interpretation: top-1 interpretation accuracy, oracle@K, supported
  coverage, semantic deviation, mapping-failure rate, unsupported rate;
- physical planning: planning latency, generated/processed/pruned states,
  pruning ratio, search reduction, oracle regret, eta components, prediction
  error, confidence coverage;
- end to end: execution accuracy, exact match, F1, backend and end-to-end
  latency, measurable data movement, success rate, error rate.
- live generation: generation/parse/candidate success, candidates per
  question, token usage, latency, repair rate, grounding success, unresolved
  anchors, hallucinated IDs, mapping failures, and semantic inadmissibility.

Unavailable metrics use an explicit status and null value. No metric is
derived from fabricated gold data. Metric computation is later M12 work.

## Execution Protocol

The versioned execution protocol explicitly records warmups, measured
repetitions, aggregation statistic, timeout, cache policy, backend reset
policy, isolated/concurrent mode, machine metadata policy, and Docker/backend
version recording. Development defaults use warmups and repeated measures;
one execution is not silently treated as a reliable latency estimate. M12-C
uses this contract for calibration; M12-D still owns full experiment-matrix
execution.

## Run Artifacts

The frozen layout is:

```text
runs/<run_id>/
  experiment_manifest.json
  questions.jsonl
  prompt.json
  model_config.json
  ontology_manifest.json
  candidates.jsonl
  validation.jsonl
  plans/logical/
  plans/physical/
  plans/search_trace.jsonl
  queries/
  results/raw/
  results/normalized/
  metrics.json
  cost_model.json
  feature_schema.json
  observation_snapshot.json
  baseline_config.json
  prompt_schema_view.jsonl       # live path
  llm_requests.jsonl             # live path, exact sanitized outbound payloads
  raw_model_responses.jsonl      # live path
  query_slots.jsonl              # live path
  grounding.jsonl                # live path
  live_diagnostics.json          # live path

  calibration_manifest.json     # M12-C calibration path
  calibration/<backend>/
    calibration_manifest.json
    calibration_plans.jsonl
    execution_measurements.jsonl
    D0.jsonl
    feature_schema.json
    cost_diagnostics.json
    queries/
  cost_models/<backend>/model.json
  cost_model_registry.json
  posterior_updates.jsonl
  online_observations.jsonl
```

The artifact-layout contract labels each path required-now,
optional/future, or generated when available. The development runner creates
the complete directory structure but writes future artifacts only as explicit
status records, never fabricated observations or benchmark results.

The manifest records run timestamp, Git commit/dirty state, spec/dataset/
ontology/model/prompt/backend/estimator/feature/semantic versions and hashes,
seeds, execution protocol, and locally available machine metadata. Missing
CUDA/GPU/Docker/backend-version metadata remains explicitly unavailable.

## M12-B Runtime Boundary

For every supported live task, deterministic lexical/alias retrieval builds a
bounded `PromptSchemaView` from the DatasetBundle ontology, aliases, entity
catalog, backend mappings, and schema snapshot. The view records ontology and
schema hashes, only prompt-visible terms/entities, query-slot anchor
candidates, domain/range data where available, backend mapping hints,
retrieval provenance, and configured limits. The full ontology is not dumped
into the prompt.

The structured response chooses one query-side ontology anchor for every
visible slot and supplies separate ontology-term realizations for every
candidate. IDs must be prompt-visible, slot coverage must be exact, and
every realization must reference a real, kind-compatible `PathPatternQuery`
component. Required backend mappings must exist. These records are converted by
`FileBackedRuntimeAlignmentProvider` into the existing M11
`OntologyAlignmentContext`; the frozen M12-A directional ontology-hop scorer
then computes `c_sem`.

Gold answers, gold logical forms, gold alignments, and evaluation labels are
evaluation-only. The runtime loader copies only ontology, alias, entity,
mapping, and schema artifacts and does not retain the gold-bearing
DatasetBundle. Recursive anti-leakage checks guard prompt and inference
artifacts.

`OpenAICompatibleStructuredCandidateProvider` performs one generation call,
allows at most one syntax/schema repair, and persists safe invocation,
latency, usage, request-ID metadata, and every exact sanitized outbound payload
in `llm_requests.jsonl`. Empty ontology/schema context fails before network
I/O. It accepts only controlled grounded `PathPatternQuery` JSON. It never
generates native query text and is not used by deterministic lowering,
physical planning, capability checks, compilation, or cost estimation.

The zero-shot prompt defines the semantic roles of source/target, path
composition, edge direction, labels/properties, selectors/restrictors, depth,
and typed component references. It asks for semantically distinct candidates;
few-shot examples remain empty. Deterministic validation still does not claim
natural-language interpretation correctness.

## Phase Boundary

M12-A implements contracts, validation, deterministic hashing, a controlled
financial-risk development bundle, a mock ModelBundle, and an offline runner.
M12-B implements the bounded live provider and runtime alignment path. M12-C
implements backend-local cost calibration and the online posterior lifecycle.
These phases do not implement model downloads/LoRA, a full ontology reasoner,
executable baselines, ablations, matrix scheduling, final datasets, plots, or
tables; those remain M12-D and later dataset work.

## M12-A Development Artifacts

The controlled bundle is `datasets/financial_risk_dev/`. It contains 20
explicitly synthetic development records and reuses the repository's native
financial-risk backend loaders. Three controlled candidate alignments are
provided for two integration questions; unavailable external-style gold
fields remain null with explicit availability metadata.

The offline model bundle is `models/mock_path_pattern_dev/`, and the single
development configuration is
`experiments/configs/financial_risk_xgap_dev.json`. M12-A intentionally does
not add a random baseline config because random baseline execution belongs to
M12-D.

The controlled invocation is:

```bash
PYTHONPATH=src python -m xgap.experiments.run \
  --config experiments/configs/financial_risk_xgap_dev.json
```

The accepted run planned two questions and three candidates successfully and
materialized 27 files under `runs/m12-financial-risk-xgap-dev/`. Reference
logical query artifacts were emitted; raw and normalized backend result
directories contain explicit `not_available` status records because M12-A
does not execute the server experiment.

Final verification: 15 focused M12-A tests passed; full pytest reported 313
passed and 2 skipped; the M12-A demo and `scripts/run_acceptance.sh` passed.

## M12-B Development Artifacts

The live development configuration is
`experiments/configs/financial_risk_qwen_live_dev.json`. It uses the same
financial-risk development DatasetBundle, the DashScope Qwen ModelBundle, the
file-backed runtime alignment provider, the reference evaluator profile, and
the explicitly uncalibrated M11 development-prior GP. It is not a final paper
benchmark or calibrated cost experiment.

The live invocation is:

```bash
export DASHSCOPE_API_KEY=<secret>
export DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
PYTHONPATH=src python -m xgap.experiments.run \
  --config experiments/configs/financial_risk_qwen_live_dev.json
```

`DASHSCOPE_BASE_URL` is optional and defaults to the China (Beijing)
OpenAI-compatible endpoint recorded by the ModelBundle. DashScope API keys are
region- and billing-plan-specific. Use the endpoint matching the key:

```bash
# China (Beijing)
export DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# International (Singapore)
export DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1

# US (Virginia)
export DASHSCOPE_BASE_URL=https://dashscope-us.aliyuncs.com/compatible-mode/v1
```

A workspace-specific endpoint may be supplied instead. Coding Plan keys are
for supported interactive coding tools and must not be used as an XGAP
experiment-backend credential. The resolved endpoint is recorded in the safe
live-provider manifest; the key is never persisted.

Default tests do not perform this network call. The optional smoke test also
requires `XGAP_RUN_LIVE_LLM=1`. Offline fake-HTTP integration exercises the
same provider, grounding, semantic, M11 planning, and artifact path.

Latest M12-B audit verification: 23 focused tests passed and 1 gated live test
was skipped; the combined M10/M12-A/M12-B suite reported 45 passed and 1
skipped; full pytest reported 336 passed and 3 skipped; the M12-A
mock runner planned 2/2 questions; the fake-HTTP integration passed; and
`scripts/run_acceptance.sh` passed. A real DashScope run subsequently completed
one question with one generation call, no repair call, and three candidates.
The end-to-end audit in `docs/report/m12b_llm_boundary_audit.md` found that the
historical run did not persist its assembled request and accepted one invalid
class-to-edge component reference. The current fixes address both issues; a
credentialed post-fix smoke then passed in 33.64 seconds. It made one
generation call, no repair call, persisted the exact sanitized request with a
matching invocation hash, validated kind-compatible component grounding, and
produced one selected physical plan. M12-B can now be frozen at this boundary;
this single-question smoke does not establish general NL interpretation
accuracy.

## M12-C Cost Calibration And Online GP Protocol

M12-C freezes independent backend-local calibration as the default policy:

```text
complete Neo4j plans -> repeated Cypher execution -> D0_neo4j -> Neo4j RBF GP
complete Fuseki plans -> repeated SPARQL execution -> D0_fuseki -> Fuseki RBF GP
```

The canonical raw cost is positive execution latency in milliseconds and the
GP target is `log(execution_ms)`. Calibration cases are controlled complete
plans from a dedicated calibration split; they contain no evaluation answers,
gold logical forms, gold alignments, future observations, or hidden cost
features. M11 feature names, ordering, explicit missing flags, schema version,
and schema hash are reused without redesign.

Each selected plan is compiled through the existing M9 boundary and executed
through the existing M7 backend client. The runner persists every warmup and
measured repetition plus its aggregate. Timeout, backend failure,
non-positive latency, insufficient repetitions, unsupported compilation,
feature failure, fit failure, serialization failure, online-update failure,
and unavailable cross-backend measurement have explicit status identifiers.
Only a successful full repetition batch creates an `ExecutionObservation`.

The existing RBF family is calibrated with a deterministic bounded grid over
positive length scale, signal variance, and observation-noise variance using
exact negative log marginal likelihood. The prior log cost is initialized
from D0. Repeated log-latency variance informs a positive execution-noise
floor. This execution noise remains distinct from posterior predictive
variance. Feature normalization is `none` and is frozen explicitly.

Evaluation uses `BackendCostModelRegistry`, an immutable mapping from backend
ID to calibrated estimator snapshot. `OnlinePosteriorLifecycle.begin_task`
returns the exact `D_(q-1)` snapshot. No update method is available during the
task. `complete_task` validates successful persisted execution evidence and
atomically appends the whole K_q batch after execution. Neo4j observations
update only the Neo4j model and Fuseki observations only the Fuseki model.
Hyperparameter hashes must remain unchanged. Append-only observation and
posterior-update records are sufficient to replay D0, D1, and later snapshots.

The development workload and config are:

- `experiments/calibration/financial_risk_complete_plans.jsonl`;
- `experiments/configs/financial_risk_gp_calibration_dev.json`.

Offline pipeline check, using explicitly fake deterministic measurements:

```bash
PYTHONPATH=src python -m xgap.experiments.calibrate \
  --config experiments/configs/financial_risk_gp_calibration_dev.json \
  --offline
```

Real server calibration, after loading the financial-risk data and checking
both services, is:

```bash
XGAP_RUN_BACKENDS=1 PYTHONPATH=src \
python -m xgap.experiments.calibrate \
  --config experiments/configs/financial_risk_gp_calibration_dev.json
```

The optional live pytest additionally requires `XGAP_RUN_CALIBRATION=1`.
Ordinary pytest never contacts either backend. Local M12-C completion used the
offline deterministic path and therefore does not claim that real Neo4j or
Fuseki calibration values were collected on this machine.

M12-C does not implement a joint backend-aware GP, cross-backend movement-cost
learning, distributed execution, new compiler coverage, baselines, ablations,
experiment-matrix scheduling, new KGQA datasets, semantic-deviation changes,
or new LLM/ontology behavior. Those boundaries remain M12-D or later work.

Local completion verification reported 9 passed and 1 gated live calibration
test in the focused M12-C suite, 345 passed and 4 gated live tests in full
pytest, and a passing `scripts/run_acceptance.sh`. The offline demo produced
two fake D0 observations and one calibrated artifact per backend. Real server
calibration remains an explicit operator command and was not claimed from the
local completion run.
