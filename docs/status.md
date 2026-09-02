# XGAP Status

## Current Milestone

M13-E3 remains **IMPLEMENTATION READY**. M13-E3B.4 is complete after the real
CWRU audit-only rerun. With entity and schema ranking unchanged, exact
role-aware relation endpoint evidence raised effective Type prompt coverage
from 4/18 to 12/18 and joint prompt reachability from 1/18 to 5/18 (27.78%).
The unchanged 0.20 engineering gate passed with
`live_preflight_allowed=true`; explicit Type Top-4 coverage remained 4/18.

M13-E3B.5 is **LOCALLY IMPLEMENTED; CWRU 18-QUERY LIVE PREFLIGHT RERUN
PENDING**. It
wires the passing query-local `preflight18` catalog and `audit_summary.json`
into the existing Qwen3-32B preflight through an explicit artifact profile.
Readiness now validates the exact frozen IDs, catalog and audit hashes, row
hash, prompt bound 4, and relation-endpoint contract before a provider call.
Structured requests carry that endpoint contract, and metrics report both all
18 questions and the 5-question jointly reachable subset. Top-50, Top-4, gate
0.20, ranking, ontology, model parameters, and pilot150 remain unchanged.

The first CWRU E3B.5 submission, Slurm job `3741724`, verified the catalog,
audit, row hash, endpoint contract, model bundle, and credential and passed the
unchanged gate at 5/18. Qwen was not loaded because readiness additionally
required the physical `reachability.jsonl` row order to equal the spec order.
M13-E3B.5.1 removes only that invalid ordering requirement: query-local
artifacts must contain the exact unique frozen 18-ID set, while row order is
irrelevant. Missing, extra, duplicate, hash-mismatched, or contract-mismatched
records still fail closed. The second CWRU submission, Slurm job `3763061`,
then passed readiness, verified the frozen runtime, started Qwen3-32B on an
H100 NVL, and passed the strict JSON-schema serving smoke. Evaluation stopped
before metrics because the shared first-failure classifier did not yet accept
the documented query-local stage `reference_not_in_local_catalog`.
M13-E3B.5.2 adds only that missing taxonomy member, retaining fail-closed
behavior for every unknown stage. The third submission, Slurm job `3763119`,
completed and wrote all 17 expected run artifacts, but all 18 provider calls
were rejected before generation with HTTP 400. The frozen bundle requested
4096 output tokens for prompts of 4146-4590 tokens while vLLM served only an
8192-token context window. Consequently provider and structured-valid rates
were both zero, no candidate reached parsing or lowering, and the reported
zero Candidate Recall is not a model-quality result.

M13-E3B.5.3 repairs only that deployment-budget contradiction. The unchanged
bundle budgets of 8192 input plus 4096 output now run against a 12288-token
vLLM context window. A fail-fast check verifies the bundle, spec, deployment
hashes, and exact token arithmetic before loading Qwen3-32B. Prompt contents,
Top-50, Top-4, candidate cap 3, model generation parameters, retrieval,
grounding, `c_sem`, and downstream planning remain unchanged.

The fourth submission, Slurm job `3763174`, validated that repair: vLLM served
12288 tokens, 17/18 provider calls succeeded, all five jointly reachable calls
succeeded, and malformed output fell to zero. However, every successful call
returned the shortest schema-valid value `candidates=[]`. The frozen vLLM JSON
Schema had no `minItems` on the candidate array, so strict guided decoding was
allowed to terminate without attempting an interpretation. No candidate
reached type checking, lowering, or `c_sem`; zero Candidate Recall is still not
a model-quality result.

M13-E3B.5.4 repairs that candidate-generator contract without adding examples
or gold information. The CWRU schema and prompt now require between one and
the frozen cap of three candidates. Generated candidates remain subject to all
existing parser, type, grounding, semantic-admissibility, and equivalence
checks, so this does not make any candidate valid by construction.

The fifth submission, Slurm job `3763298`, loaded the corrected bundle and
again reached 17/18 provider success with zero malformed responses, but vLLM
0.11.1 still emitted `candidates=[]` for every successful call. This proves its
guided decoder did not enforce the declared array `minItems/maxItems`; XGAP's
provider boundary had also trusted those constraints without checking them.

M13-E3B.5.5 adds deterministic candidate-array cardinality validation at that
provider boundary. It reads `minItems/maxItems` from the active bundle schema,
rejects violations, and invokes the already frozen single repair call. Bundles
without those declared constraints retain their prior behavior. Parser,
retrieval, grounding, semantics, lowering, model parameters, and experiment
bounds remain unchanged. One final CWRU 18-query resubmission is pending.

## Completed

- M0 Project Skeleton
- M1 Data Model
- M2 Core Algebra
- M2.5 Logical Plan Infrastructure
- M3 Recursive Algebra
- M4 SolutionSpace Algebra
- M4.5 Semantic Audit
- M5 GPC-Lite Pattern AST And Lowering
- M5.5 Pattern-Lowering Audit
- M6 Bounded Focused Quantified Pattern Semantics
- M7 Backend Infrastructure
- M8 Backend Capability Profile + Compiler Boundary Preflight
- M9 Minimal Compilers For Backend MVP
- M10 LLM Planner Boundary + Structured Candidate Interface
- M11 Ontology-Bounded Physical Planning
- M12-A Experiment Artifact Contract + Dataset Bundle
- M12-B Live LLM + Ontology/Alignment Artifacts
- M12-C Cost Calibration + Online GP Protocol
- M12-D Baselines/Ablations + Server Experiment Runner
- M13-A GrailQA Paper Artifact Feasibility Audit
- M13-B KQA Pro Paper Artifact Feasibility Audit
- M13-C GrailQA Paper Vertical Slice + Minimal Fragment Expressiveness Upgrade
- M13-D Local Preparation for Server-Executed GrailQA Semantic Pilot
- M13-D Frozen 150-Query Server Pilot Execution
- M13-E1 Local Offline Reachability And Interpretation-Contract Repair
- M13-E2 CWRU H100 + vLLM Experiment Backend (local implementation)
- M13-E3B.2 Query-Local Entity Retrieval Contract Repair
- M13-E3B.3 Ontology-Aware Schema Ranking Repair
- M13-E3B.4 Relation-Endpoint Grounding Contract

## In Progress

- M13-E3 real CWRU construction of query-independent Freebase catalog v2
- M13-E3 all-35,439 coverage and frozen-150 offline reachability audit
- M13-E3A download and empirical validation of the frozen archival source
- M13-E3B.5 query-local artifact wiring and CWRU 18-query live preflight
- M13-E3B real CWRU query-local pilot150 build, after reviewing preflight18

## Next Planned Milestone

Leave the running global M13-E3/E3A job untouched. Pull the M13-E3B.5
deterministic candidate-cardinality repair on CWRU,
run `scripts/server/check_cwru_grailqa_preflight_ready.sh`, and submit exactly
the frozen 18-query Qwen3-32B Slurm preflight. Review overall Candidate Recall
and the separately reported jointly reachable 5-question subset before any
larger experiment. Freebase rescanning, prompt-bound changes, embeddings,
pilot150, RQ2/RQ3, full M13 disambiguation, and M14 remain outside this step.

## M13-E3 Freebase Catalog-v2 And Reachability Audit

M13-E3 reuses the M13-E1 extraction semantics, SQLite/FTS5 catalog,
deterministic entity/relation/type retriever, three bounded relation-hop pools,
prompt construction, and fail-closed 0.20 gate. M13-E3A adds explicit
`google_rdf_gzip` and `hf_archival_parquet` source modes with no fallback. The
current CWRU artifact freezes `CleverThis/freebase` revision
`dbb1931c2698295653effe9b980a02ab29f004e0`: 964 Parquet shards, 32,476,432,840
bytes, 3,130,753,066 rows, and six nullable string columns. The adapter streams
shard by shard, row group by row group, into the unchanged triple extraction
logic; it never reconstructs the full N-Triples dump.

The archival inventory records immutable URLs, LFS SHA-256 values, Git blob
IDs, sizes, the verified conversion revision, and schema fingerprint. Local
verification rejects missing, extra, truncated, or altered shards. A real
first-row-group smoke of frozen shard `0000` found MIDs, English canonical
names, aliases, type memberships, and English literals. N-Triples/Parquet
fixtures produce identical catalog rows and retrieval candidates.

M13-E3A.1 makes archival downloads compatible with CWRU's older system curl.
The shared shell helper always uses `--retry` and `--retry-delay`, discovers
`--retry-all-errors` through `curl --help all`, and passes it only when the
installed binary advertises support. No curl upgrade, sudo, alternate
downloader, or weaker integrity policy is required.

The offline audit now reports entity/relation/type/joint catalog coverage over
all 35,439 supported GrailQA train/dev questions and the frozen 150 separately.
For the pilot it reports Recall@1/5/10/20, per-slot relation recall, at-least-one
versus all-required relation recall, prompt truncation loss, deployed joint
prompt reachability, Q/path-length strata, and first-stage loss counts. Six
compact JSON reports reference the hashed external query-level artifacts.

The local fixture workflow is complete, but real catalog counts and metrics are
deliberately unset. M13-E3 calls no LLM, does not tune the M13-E1 retriever, and
does not alter `c_sem`, Nash ranking, PathPatternQuery/algebra semantics, M11,
GP, compilers, backend execution, or the M13-E2 provider boundary. See
`docs/report/freebase_catalog_v2_cwru_runbook.md` and
`docs/report/grailqa_freebase_catalog_v2_reachability.md`.

Direct CWRU requests to the documented Google Freebase objects returned HTTP
403 on 2026-08-19. The archival transport is Freebase data, not a new ontology
or replacement knowledge graph. After the unchanged audit, the separate
evaluation-only compatibility artifact reports missing pilot/supported MIDs,
missing ontology relations/types, and JointCatalogCoverage.

## M13-E3B Query-Conditioned Local Freebase Catalog

M13-E3B adds a separate, gold-blind grounding experiment over the same frozen
E3A Parquet source. For each question, contiguous normalized text spans are
matched exactly against English Freebase canonical names and aliases, then a
frozen maximum of 50 ranked MIDs is enriched with public type memberships. A
batched scan maintains independent candidate maps, and the persisted
`question_id` plus question-text hash controls the Catalog-v2 entity allowlist.
Candidates selected for one question are therefore unavailable to another.

The source is scanned at most twice: name/alias matching, followed by
name/alias/type enrichment restricted to retained MIDs. Relation/type terms,
domain/range, reverse relations, and hierarchy continue to come from the
frozen GrailQA ontology. No factual edge, k-hop snapshot, embedding index, NER,
LLM call, semantic change, or retrieval tuning is included.

Construction accepts only the inference question artifact and rejects records
containing gold/reference/logical-form/answer fields. SQLite/FTS construction
runs under node-local staging and the complete validated subset is copied to
an output-adjacent path before atomic publication. Evaluation is a separate
phase that first persists retrieval, then opens references and reports local
catalog loss separately as `reference_not_in_local_catalog`.

The implementation, fixture tests, CPU Slurm job, 18/150 frozen configuration,
comparison utility, and report are ready. The real CWRU `preflight18` build
retains 865 unique entities and 900 assignments in an approximately 14.4 MB
SQLite artifact after about 45 minutes. Its first audit reports entity catalog
coverage 10/18, entity Recall@20 0/18, relation Recall@20 8/18, type Recall@20
6/18, and joint prompt reachability 0/18. These are diagnostic engineering
results, not paper metrics. The global E3/E3A job and its staging/output remain
independent and unchanged. See
`docs/report/grailqa_local_freebase_catalog.md`.

M13-E3B.1 fixes the first real CWRU preflight failure without changing the
catalog policy. Parameter 8 of the `query_entity_candidates` INSERT is
`source_shard`; the Parquet adapter supplies its safe relative path as a
`PosixPath`, which SQLite cannot bind. The materialization boundary now maps
only `pathlib.PurePath` values to path strings, preserves supported SQLite
primitives unchanged, and rejects unknown parameter types. The same provenance
is string-normalized for JSONL output. The local-catalog sbatch script now runs
`module load Miniconda3` before invoking Python.

M13-E3B.2 fixes the contract defect exposed by that completed build. Catalogs
whose manifest declares `requires_query_entity_filter=true` now return only
the current question's persisted candidates ordered by local rank and MID,
with the persisted lexical score. They no longer pass that universe through
the global FTS scorer. Global Catalog-v2 retrieval is unchanged. Offline audit
now writes `entity_retrieval_before_after.json`, `relation_diagnostics.jsonl`,
and `type_diagnostics.jsonl`; relation/type retrieval itself is unchanged.
The real post-fix CWRU audit measured entity Recall@1/5/10/20 of 3/7/8/8 over
18, entity prompt coverage 7/18, and joint prompt reachability 1/18. This closes
E3B.2 while preserving the 0.20 gate, prompt limit 4, top-50 construction,
ontology, and model path.

M13-E3B.3 repairs the generic relation/type ranking boundary. It
aggregates all bounded descriptors by schema term before any Top-k, ranks with
the frozen lexicographic hierarchy exact multi-token phrase, complete
informative tokens, contiguous partial phrase, informative partial overlap,
generic single token, and zero overlap, and uses ontology-descriptor IDF only
as a deterministic secondary tie-break. Relation slots use query-local entity
types and bounded bidirectional domain/range propagation; no direction is
invented when the existing slot has none. Type ranking combines lexical,
entity-attached, relation-induced, and bounded ontology-expansion provenance
before truncation. Audit-only writes the versioned before/after and ranking
diagnostic artifacts without replacing historical E3B.2 diagnostics. The code
completed its real CWRU audit-only rerun. Relation Recall@1/5/10/20 is now
5/11/12/13 of 18, relation prompt coverage is 10/18, Type Recall@1/5/10/20 is
1/4/8/13, and explicit Type prompt coverage is 4/18. The remaining losses are
5 relation retrieval, 3 relation prompt-truncation, 5 type retrieval, and 9
type prompt-truncation cases; joint reachability remains 1/18.

M13-E3B.4 keeps those ranking outputs fixed and makes relation endpoint
metadata operational at the grounding boundary. For a selected fixed linear
path, the first relation's source endpoint and last relation's target endpoint
are derived exactly from domain/range and edge direction. A derived type is
accepted only for its matching source/target role; no hierarchy expansion,
lexical fallback, prompt-term insertion, or benchmark-specific alias is used.
Runtime grounding and offline reachability call the same versioned helper.
`type` continues to report explicit Type candidates, while `effective_type`
and `joint` include valid endpoint evidence. The audit adds
`endpoint_grounding_before_after.json` and
`relation_endpoint_diagnostics.jsonl` without rewriting E3B.2/E3B.3 history.
The real CWRU audit-only rerun retained explicit Type prompt coverage at 4/18,
raised effective Type coverage from 4/18 to 12/18, and raised joint prompt
reachability from 1/18 to 5/18. The unchanged 0.20 gate therefore passed at
0.2778. This is an inference-context ceiling, not Qwen accuracy.

M13-E3B.5 connects that exact passing artifact to the existing CWRU live
preflight. `query_local_e3b4` is an explicit runtime profile; it reads
`audit_summary.json` directly and rejects profile, question-ID-set,
catalog-hash, audit-hash, reachability-row-hash, prompt-bound, or endpoint
contract drift. The Qwen request receives the versioned role/direction rule
already used by runtime validation and the audit. Overall 18-query metrics are
preserved, while a separate jointly reachable subset reports provider success,
structured validity, and Candidate Recall among the five questions for which
all required grounding context is prompt-visible.

## M13-E2 CWRU H100 + vLLM Experiment Backend

M13-E2 adds a frozen CWRU Pioneer environment contract, a Qwen3-32B vLLM
ModelBundle, a model-specific copy of the unchanged 18-question M13-E1
preflight contract, generic OpenAI-compatible model/endpoint environment
selection, and configuration-owned non-thinking requests. Existing model
bundles retain their hashes.

The Slurm infrastructure requests one scheduler-selected `gpu2h100` GPU, eight
CPUs, and 64G memory. It resolves an existing shared-cache model revision,
binds vLLM only to `127.0.0.1`, polls `/v1/models`, runs a tiny strict JSON
Schema smoke, captures credential-free environment metadata, executes an
explicit command/spec, inventories artifacts, and terminates vLLM through a
trap. The GrailQA wrapper checks the M13-E1 offline gate before model startup.

Normal tests do not require Slurm, H100, vLLM, or model weights. M13-E2 does
not change `c_sem`, pattern semantics, algebra, M11, GP, GrailQA references,
the M13-D result, model weights, or any 150-query run. See
`docs/report/cwru_vllm_experiment_backend.md` and
`docs/report/cwru_vllm_runbook.md`.

## M13-E1 Reachability And Contract Repair

M13-E1 preserves M13-D as an immutable diagnostic baseline. Its reusable
offline audit reproduced catalog entity availability 12/150, retrieval Top-20
entity/relation/type coverage 10/47/67, deployed prompt Top-4 coverage 9/22/38,
and joint prompt reachability 0/150. This explains why the frozen Candidate
Recall 0 cannot be attributed to Qwen capability.

The implementation adds a streaming, query-independent catalog-v2 builder for
the final official Freebase RDF dump, deterministic alias/FTS5 entity
retrieval, public-metadata relation retrieval, three bounded relation-hop
pools, domain/range type expansion, catalog/retrieval/prompt decomposition,
and a fail-closed live gate. No question, answer, logical form, alignment, or
reference interpretation is accepted by catalog construction or inference.

The v2 interpretation boundary defaults canonical fixed-path fields through a
named general profile, derives SIMPLE node inequalities deterministically,
defines a complete typed recursive condition schema, compares normalized
interpretations component by component, and attributes failures by stage.
The M13-D parser/spec/model bundle remains unchanged. `c_sem`, M11, GP,
compilers, logical operators, and backends are unchanged.

The comprehensive approximately 22 GB compressed Freebase source is not
present locally. Consequently committed catalog-v2 and reachability-v2
manifests are explicitly `blocked`; no v2 counts or improved Recall@k are
claimed. The frozen 18-query preflight spec hash is
`b02e67acd1f7b8f79d2cb7f3d48df7e5b2beb6c9e6624d1b1f5740921e3f2f35`.
Readiness refuses all provider calls until built artifact hashes match and the
offline gate passes. See the five M13-E1 reports under `docs/report/`.

## M13-D GrailQA Semantic Pilot Preparation

M13-D freezes the first real GrailQA RQ1 semantic pilot while preserving all
M13-C interpretation and algebra boundaries. It adds no PathPatternQuery form,
logical operator, `c_sem` rule, M11/Nash behavior, GP behavior, backend
execution, KQA Pro path, RQ2, or RQ3 functionality.

The query-independent public inference catalog contains 14,951 entities,
10,656 types, 13,747 relations, 5,531 scalar properties, and 9,908 directed
reverse-property entries. Its catalog hash is
`b547bf391a2dadf6c5affd205689da325bd4bce31b179b3d0a1f3c6bc4c4d416`;
the normalized ontology hash remains
`8bd4f19503d3a61a89831da1d040afea93fae1f64446e0ffb206b510bb69c10b`.
The entity source is the public FB15k-237 MID-name subset, so it is explicitly
incomplete and retrieval recall is measured after inference.

Inference now reads a gold-free question projection. A strict pre-provider
audit rejects gold forms, annotations, answers, references, canonical plans,
`Q(u)`, and `A(u)`. Evaluation-only references and workload statistics are
opened only after all selected questions have inference state. Deterministic
lexical retrieval persists IDs, labels, scores, ranks, question/catalog hashes,
and configuration; entity/relation/type Recall@1/5/10/20 is joined afterward.

The existing M12-B prompt and provider remain unchanged:
`qwen3-max-2026-01-23`, temperature 0, top-p 1, candidate cap 3, no supported
seed, and at most one repair. The frozen M grid is `{1,3}` because that M12
candidate cap supersedes requested values 5 and 10. Epsilon is
`{0,0.1,0.25,0.5,0.75,1}` and one generated candidate set is reused throughout.
Reference support is conservative variable-insensitive structural equality;
it is not a claim of general graph-query equivalence.

The ambiguity sanity audit selects recommendation C: exclude `A(u)` from this
pilot because it measures bounded ontology-neighborhood density rather than a
validated question-conditioned ambiguity quantity. `Q(u)` remains a complexity
stratum.

The immutable spec is
`experiments/specs/grailqa_semantic_pilot_v1.json`, with file SHA-256
`736237ec3293a1b3a86e94e7f2592b36179a6edf97635e07c306ba4c91a9ca48`
and canonical freeze hash
`5aeb1813813ca0c0835e30fa9c92644cf51a25b14480b6aa8b3d7e6938304e28`.
The local fake provider processed all 150 IDs, made 150 deterministic fixture
requests, produced 450 validated/grounded candidates, used no repairs, and
wrote every output. That run is orchestration-only and makes no accuracy claim.

Server commands are documented in
`docs/report/grailqa_semantic_pilot_server_runbook.md`. The frozen M13-D server
run subsequently completed all 150 questions: 132 provider successes, 18
malformed failures, 40 repairs, Candidate Recall 0, Top-1 0 for every epsilon,
and Feasible Coverage 0.48 for every epsilon. These remain immutable baseline
results; M13-E1 diagnoses their zero joint prompt reachability rather than
rewriting them.

Large generated benchmark bodies are intentionally excluded from Git. The
server now runs `scripts/server/fetch_grailqa_m13d_artifacts.sh` after `git
pull`. The script downloads pinned public GrailQA, official ontology, and
FB15k-237 sources, verifies their SHA-256 values, reproducibly rebuilds the
temporary v2 audit plus the required pilot/catalog, validates both against the
frozen experiment spec, and installs them atomically. On the experiment server,
it prepares `/home/<user>/xgap-data` as a symlink to
`/data/<user>/xgap-artifacts`, so large downloads and temporary builds do not
consume the home filesystem. A forced local fresh
rebuild reproduced all 64,331 audit classifications, the 35,439 supported
records, all 150 pilot IDs, catalog hash
`b547bf391a2dadf6c5affd205689da325bd4bce31b179b3d0a1f3c6bc4c4d416`,
and pilot bundle hash
`dd27f7fecdb226bef89beb50339932793bd5ffe1b987e1ce4144f6391caacd72`.
The dataset-bundle and RDF-mapping loaders normalize schema-declared empty YAML
mappings, including dataset metadata, alias groups, and compiler-token groups;
malformed non-mapping values remain rejected. Server bootstrap also exposed an
environment-dependent ontology mismatch: PyYAML coerced the valid unquoted
Freebase relation key `null` to a null object while XGAP's bundled parser kept
the required string identifier. Repository YAML now always uses the bundled
deterministic subset parser, preserving frozen artifact bytes and canonical
hashes whether or not PyYAML is installed.

## M13-C GrailQA Paper Vertical Slice

M13-C selected GrailQA as the current primary ontology-bounded semantic
interpretation benchmark and made one minimal generic semantic extension:
`NodeNotEquals` compares identity at fixed path-node positions and lowers
through the existing `Selection` operator. No logical operator, `c_sem`
definition, Nash objective, BnB rule, or GP confidence formula changed.

The full v2 audit classified all 64,331 public questions:

- 35,439 train/dev questions are supported, up 12,283 from M13-A;
- support is 69.352% of the 51,100 gold-available questions and 55.089% of all
  public questions;
- supported paths have lengths 1/2/3 with counts 26,002/8,952/485;
- `Q(u)` now has values 13/19/25, mean 14.680, median 13, p90 19, maximum 25;
- the operator totals are `Edges` 45,361, `Join` 9,922, `Selection` 151,678,
  `GroupBy` 35,439, and `Projection` 35,439;
- fixed numeric path-property comparisons contribute 466 supported questions;
  count, superlative, focus-only, branching, and multi-anchor forms remain
  explicitly unsupported.

The ontology is normalized by deterministic SCC condensation. Ten cyclic
components containing 18 terms become a 10,648-component DAG with 18,142
hierarchy edges. The normalized hash is
`8bd4f19503d3a61a89831da1d040afea93fae1f64446e0ffb206b510bb69c10b`;
no ontology edge is invented.

Reference `A(u)` is evaluation-only and is derived from the unchanged frozen
`c_sem`, exact interpretations, and bounded direct hierarchy neighbors. The
predefined epsilon analysis recommends 0.10 for pilot stratification but does
not freeze a final paper value.

`datasets/grailqa_pilot_v1/` contains 150 deterministic public train/dev cases
(seed 1303; 120 train and 30 dev). Its content hash is
`87ae8633712a54e30dd96154201248bbf3abe1fde5bdf104f09a92c5a472bac4`.
Gold answers, forms, alignments, slots, and reference interpretations are
evaluation-only; runtime aliases/entity catalog remain empty.

The controlled three-case vertical slice covers `Q=13/19/25` and traverses
the real `PathPatternQuery` lowering, M11 planning, and M9 Cypher/SPARQL
compilers. The controlled semantic metrics are pipeline-integrity checks, not
paper results. M13-C did not run live Qwen because it had no inference-safe
public entity catalog; M13-D later supplied a separate public catalog and
completed the frozen live 150-query diagnostic run. Freebase execution
feasibility is outcome C: semantic evaluation only is currently practical. No
financial-risk D0 was reused and no GrailQA D0 was created.

All 150 pilot interpretations currently expose one M11 all-local complete
realization; the fraction with more than one is zero. Two native compiler
targets do not constitute a rich physical search space. The current
recommendation is therefore **GrailQA for semantic-only paper evaluation**.
See `docs/report/grailqa_fragment_extension_analysis.md`,
`docs/report/grailqa_artifact_audit_v2.md`, and
`docs/report/grailqa_vertical_slice.md`.

## M13-B KQA Pro Artifact Feasibility Audit

M13-B classified all 117,970 public KQA Pro questions from verified official-
format artifacts using an isolated paired KoPL/SPARQL converter and unchanged
production XGAP boundaries.

- train has 94,376 questions, validation has 11,797, and public test has
  11,797; test masks KoPL, SPARQL, and answers;
- 1,690 train/validation questions lower through the strict linear fixed-path
  fragment and pass native Cypher/SPARQL compiler probes;
- 116,280 questions are explicitly unsupported or lack public gold;
- support is 1.592% of 106,173 gold-available questions and 1.433% of all
  public questions;
- supported M11 planning plans comprise 1,561 one-hop plans with `Q(u)=7` and
  129 two-hop plans with `Q(u)=15`;
- all 1,690 fit the controlled 4,096-state oracle bound, but no oracle or live
  backend measurement was run;
- the KB exposes 794 concepts, 16,960 entities, 363 observed relations, 629
  attributes, 275 qualifier keys, and an acyclic 365-edge concept hierarchy;
- the official download link was unavailable during the audit, so a complete
  public mirror revision and all four file hashes are frozen in the artifacts;
- native compilation feasibility uses an ephemeral term probe only. Current
  KQA Pro end-to-end execution coverage remains zero because final mappings,
  loaders, answer normalization, and a loaded backend snapshot do not exist.

The result is **unsuitable** as the primary current XGAP end-to-end and
physical-planning paper benchmark. It may be retained as a future restricted
diagnostic after a separate integration milestone. See
`docs/report/kqapro_artifact_audit.md` and `datasets/kqapro_audit/`.

## M13-A GrailQA Artifact Feasibility Audit

M13-A classified all 64,331 public GrailQA questions using an isolated audit
converter and the unchanged production `PathPatternQuery` lowering pipeline.

- 23,156 questions are structurally supported under the explicit one-hop
  entity-anchor and Freebase mapping contract;
- 41,175 questions are explicitly unsupported or lack public gold annotations;
- support is 45.315% of the 51,100 gold-available train/dev questions and
  35.995% of all public questions;
- 51,085 gold-available questions expose complete ontology-slot anchors from
  the parsed public resources;
- official ontology resources are substantial but require documented
  normalization, cycle handling, a type-to-label policy, and validation before
  they can become an M12 `OntologyGraph` artifact;
- a complete public alias lexicon, full entity catalog, Freebase backend
  mapping, executable graph snapshot, and public test gold are unavailable.

The result is **suitable with restrictions** for a future frozen train/dev
semantic-interpretation subset. It is not a completed DatasetBundle, backend
integration, ambiguity benchmark, or paper result. See
`docs/report/grailqa_artifact_audit.md` and `datasets/grailqa_audit/`.

## M12 Experimentalization

Current phase status:

- M12-A Experiment Artifact Contract + Dataset Bundle: Completed
- M12-B Live LLM + Ontology/Alignment Artifacts: Completed
- M12-C Cost Calibration + Online GP Protocol: Completed
- M12-D Baselines/Ablations + Server Experiment Runner: Completed

M12-A freezes experiment-facing semantics and artifact contracts. It does not
claim, by itself, live model access, production ontology reasoning/alignment,
KGQA execution, a final financial-risk benchmark, or final SIGMOD
experimental results. M12-B through M12-D add bounded live inputs, real-cost
calibration, and reproducible orchestration while preserving that separation.

See `docs/m12_experimentalization.md`.

## Implemented Logical Operators

- `Nodes(G)`
- `Edges(G)`
- `Selection`
- `Union`
- `Join`
- `Recursive`
- `GroupBy`
- `OrderBy`
- `Projection`

## Implemented Deterministic Core

LogicalPlan
  -> validate_plan
  -> reference evaluation

## Implemented Structured Pattern Layer

PathPatternQuery
  -> type_check_path_pattern
  -> deterministic lowering
  -> LogicalPlan

FocusedQuantifiedPatternQuery
  -> type_check_focused_quantified_pattern
  -> validate_quantifier_bounds
  -> deterministic lowering
  -> LogicalPlan

## Implemented M6 Binding Layer

- `BindingRelation`
- `BindNode`
- `BindEdge`
- `BindingJoin`
- `BindingProject`
- `QuantifiedCheck`
- `AntiSemiJoin`
- `FocusProjection`

M6 supports bounded, focused, rooted-tree quantified patterns with
non-injective set-valued bindings, distinct child-node counting, exact
ratio thresholds, non-vacuous ratio and universal semantics, anti-semi-
join `NONE`, focus-only queries, deterministic lowering, static schema
inference, plan validation, pretty printing, and reference evaluation.

M6 remains QGP-inspired only. It is not full QGP, not full GPC, and not
backend support.

## Not Implemented Yet
- Full GQL / Cypher / SPARQL compiler coverage
- GQL compiler support
- Recursive, selector, and M6 quantified-pattern backend compilation
- Logical rewrite optimization
- Paper-scale calibrated observations beyond the controlled development workload
- Production ontology/schema, stronger retrieval, and automated reasoning
- Distributed cross-backend execution
- Provider-specific production hardening beyond the generic OpenAI-compatible boundary
- Disambiguation
- KGQA evaluation

## M7 Backend Infrastructure

M7 Backend Infrastructure is completed.

Server-side Docker Compose scaffolding exists for starting local Neo4j
and Apache Jena Fuseki services on a lab machine, plus a minimal
financial-risk toy dataset and smoke-query scripts.

The server scripts default to the current repository checkout instead of
creating a fixed `/xgap-lab` directory. Operators can still override
`XGAP_REPO_ROOT` explicitly when needed.

When a user cannot access the Docker daemon socket directly, the server
scripts automatically fall back to `sudo docker`.

Backend healthcheck uses Neo4j `cypher-shell` readiness over Bolt
instead of requiring the Neo4j HTTP browser endpoint to respond first.

This is runtime environment setup only. It is not a compiler, planner,
semantic-deviation layer, ontology-reasoning feature, LLM feature, or
KGQA evaluation harness.

Earlier backend-environment scaffold verification, before the full M7
infrastructure layer:

- `bash -n scripts/server/*.sh`: passed.
- `docker compose --env-file services/.env.example -f services/docker-compose.yml config`:
  not available in the local development environment because the Docker
  CLI is not installed here.

Full M7 verification is recorded below.

## M7 Backend Infrastructure Protocol And Experiment Harness

XGAP now has JSON-serializable backend infrastructure records and a
minimal native-query execution harness:

- backend descriptors under `descriptors/backends/` for
  `reference_evaluator`, `neo4j`, and `fuseki`;
- `BackendDescriptor`, `BackendStatus`, `DatasetSpec`, `QueryArtifact`,
  `ExecutionReport`, and `RunRecord`;
- a descriptor registry with load, get, list, and language-filter
  helpers;
- a minimal `BackendClient` protocol with `healthcheck()` and
  `execute(QueryArtifact)`;
- native Neo4j Cypher and Fuseki SPARQL clients implemented with the
  Python standard library rather than backend driver dependencies;
- `examples/datasets/financial_risk_toy.yaml`;
- `xgap.experiments.backend_smoke`, which executes native smoke query
  files and writes `query_logs.jsonl` plus normalized result JSON under
  `runs/<run_id>/`.

This layer executes already-authored native Cypher/SPARQL smoke queries
only. It does not compile XGAP logical plans, does not implement
semantic-deviation scoring, ontology reasoning, bounded planning,
dominance pruning, top-K selection, LLM candidate generation, KGQA
evaluation, or logical-plan-to-native-query compilation.

Default pytest skips live backend execution unless `XGAP_RUN_BACKENDS=1`
is set.

Latest backend-infrastructure verification:

- `python -m pytest tests/test_backend_infrastructure.py tests/test_backend_live.py`:
  7 passed, 2 skipped.
- `python -m pytest`: 241 passed, 2 skipped.
- `./scripts/run_acceptance.sh`: passed, including harness check,
  pytest, all existing examples, and `examples/quantified_pattern_demo.py`.
- Server live backend test:
  `PYTHONPATH=src XGAP_RUN_BACKENDS=1 python -m pytest tests/test_backend_live.py`:
  2 passed.

## M8 Backend Capability Profile + Compiler Boundary Preflight

M8 is completed.

M8 is not a database bootstrapping milestone. It assumes the M7 backend
services and native smoke harness are available.

M8 answers five questions:

1. Which XGAP path/GPC fragments does Neo4j support?
2. Which XGAP path/GPC fragments does Fuseki support?
3. Which M0-M6 logical constructs can be safely compiled?
4. Which constructs must explicitly return unsupported?
5. What is the format of compiler input, output, and failure reports?

Descriptor `capabilities` now include program-checkable capability
profiles for `reference_evaluator`, `neo4j`, and `fuseki`.

Implemented M8 objects:

- `SupportLevel`
- `SupportReason`
- `FeatureSupport`
- `BackendCapabilityProfile`
- `CompatibilityReport`
- `UnsupportedFeature`
- `CompilerInputSpec`
- `CompilerOutputSpec`
- `CompilerFailureSpec`

Implemented M8 compatibility helpers:

- `check_backend_support(profile, feature_request)`
- `check_backend_features(profile, feature_requests)`

The compatibility checker is static. It does not compile logical plans,
call backend clients, call the reference evaluator, run optimizer code,
or invoke planner, LLM, ontology, cost, or evaluation code.

M8 remains a preflight and boundary-definition milestone. It must not
implement optimizer algorithms, semantic-deviation scoring, ontology
reasoning, bounded planning, dominance pruning, top-K selection, LLM
candidate generation, KGQA evaluation, or logical-plan-to-native-query
compilation.

Latest M8 verification:

- `python -m pytest tests/test_backend_capabilities.py tests/test_backend_compatibility.py`:
  13 passed.
- `python -m pytest tests/test_backend_infrastructure.py tests/test_backend_live.py`:
  7 passed, 2 skipped.
- `python -m pytest`: 254 passed, 2 skipped.
- `./scripts/run_acceptance.sh`: passed, including harness check,
  pytest, all existing examples, and `examples/quantified_pattern_demo.py`.

See `docs/m8_backend_capability_preflight.md`.

## M9 Minimal Compilers For Backend MVP

M9 is completed.

XGAP now has the first deterministic native-query compiler slice after
M8 capability preflight.

Implemented M9 compiler boundary:

- `compile_cypher(...)` returns a compiled Cypher `QueryArtifact` for
  Neo4j.
- `compile_sparql(...)` returns a compiled SPARQL `QueryArtifact` for
  Fuseki.
- `compile_gql(...)` remains an explicit unsupported boundary and
  raises `UnsupportedCompilationError`.
- Compiler failures carry `CompilerFailureSpec` records with backend,
  language, unsupported feature, support level, reason, and metadata.

Supported M9 fragment:

- `Nodes(G)`;
- `Edges(G)`;
- `Selection`;
- path-chain `Join`;
- fixed-length `OUT` path fragments;
- node-label and edge-label predicates;
- scalar property equality and numeric comparisons already represented
  by XGAP conditions;
- `PathPatternQuery` only for selector `ALL`.

M9 compiler outputs are row-oriented native artifacts. They do not claim
native XGAP `PathSet` object preservation.

M9 explicitly rejects:

- `Union`;
- `Recursive`;
- `GroupBy`;
- `OrderBy`;
- selector-style `Projection`;
- M6 focused binding operators;
- `FocusedQuantifiedPatternQuery`;
- `PathPatternQuery` selectors other than `ALL`;
- reverse or undirected edge lowering;
- unsupported regex placeholders;
- boolean `OR` and `NOT` conditions;
- path-length conditions;
- GQL compilation.

M9 does not implement optimizer rules, cost estimation, semantic-
deviation scoring, ontology reasoning, bounded planning, dominance
pruning, top-K selection, LLM candidate generation, natural-language
planning, or KGQA evaluation.

Latest M9 verification:

- `python -m pytest tests/test_compiler_boundaries.py tests/test_cypher_compiler.py tests/test_sparql_compiler.py`:
  11 passed.
- `python examples/compiler_mvp_demo.py`: passed.
- `python -m pytest`: 265 passed, 2 skipped.
- `./scripts/run_acceptance.sh`: passed, including harness check,
  pytest, all existing examples, `examples/quantified_pattern_demo.py`,
  and `examples/compiler_mvp_demo.py`.

See `docs/m9_minimal_compilers.md`.

## M10 LLM Planner Boundary + Structured Candidate Interface

M10 is completed.

XGAP now has a structured LLM boundary without connecting any live model
provider.

Implemented M10 objects and helpers:

- `PlannerRequest`
- `PlannerCandidate`
- `PlannerResponse`
- `CandidateValidationReport`
- `StructuredCandidateProvider`
- `MockStructuredCandidateProvider`
- `PlannerSchemaError`
- `parse_path_pattern_query(...)`
- `parse_planner_response(...)`
- `path_pattern_query_to_dict(...)`
- `plan_from_question(...)`
- `plan_response_from_question(...)`
- `validate_candidate(...)`

M10 accepts only controlled JSON that parses into existing
`PathPatternQuery` objects. It rejects native query fields such as
`cypher`, `sparql`, `gql`, `native_query`, and `query_text`.

`plan_from_question()` has no default live provider in M10. Callers must
pass an explicit provider, and the included mock provider is for tests
and local demos only.

Candidate validation is deterministic:

PathPatternQuery
  -> type_check_path_pattern
  -> lower_path_pattern
  -> validate_plan

M10 does not implement Qwen/OpenAI/DashScope/vLLM clients, LoRA,
prompt optimization, semantic-deviation scoring, ontology reasoning,
logical optimization, bounded planning, dominance pruning, top-K
selection, KGQA evaluation, native query generation by an LLM, or live
model tests.

Latest M10 verification:

- `python -m pytest tests/test_llm_boundary.py`: 7 passed.
- `python examples/llm_boundary_demo.py`: passed.
- `python -m pytest`: 272 passed, 2 skipped.
- `./scripts/run_acceptance.sh`: passed, including harness check,
  pytest, all existing examples, `examples/quantified_pattern_demo.py`,
  `examples/compiler_mvp_demo.py`, and `examples/llm_boundary_demo.py`.

See `docs/m10_llm_planner_boundary.md`.

## M11 Ontology-Bounded Physical Planning

M11 is completed in four sequential phases:

- M11-A Planning Objective and Physical-State Contract
- M11-B Bounded Branch-and-Bound Physical Search
- M11-C Bayesian Cost Model and Search Trace
- M11-D XGAP Main Planner and Exhaustive Oracle Evaluation

The logical plan for an interpretation remains the deterministic output of
the existing M5/M10 pipeline. M11 does not enumerate logical rewrites. Its
search variables are backend placement and explicit cross-backend exchange
decisions for that fixed logical plan.

Ontology/schema definitions, source-to-ontology mappings, aliases, alignment
evidence, and semantic-deviation inputs are external, versioned,
replaceable planning artifacts. Missing, unknown, unsupported, or
insufficient mapping evidence is not treated as success. Bounded physical
search neither invents nor enumerates ontology mappings.

The M11 planning contract uses a strict execution threshold: a plan is
returnable only when its conservative upper estimate satisfies
`C_bar < T_max`. No threshold relaxation or fallback outside that bound is
allowed. Each interpretation contributes at most one discovered physical
representative, chosen by minimum conservative upper estimate within the
search budget. Final deterministic top-K ranking uses the Nash score only
when semantic and execution utilities are both strictly positive.

M11 explicitly excludes live LLM providers, KGQA dataset integration,
LoRA/model training, automatic ontology induction, a built-in OWL/DL
reasoner, full GQL, new M9 compiler coverage, logical rewrite search, new
backend engines, and distributed cross-backend execution.

Implemented M11-A contracts and interfaces:

- deterministic frozen physical-state, placement, exchange, realization,
  plan, objective, cost, feature, observation, trace, and configuration
  records;
- stable logical-operator and dependency identifiers derived from existing
  plan structure;
- `OntologyAlignmentProvider`, `SemanticDeviationScorer`, `CostEstimator`,
  `StateFeatureExtractor`, `BudgetPolicy`, and `PhysicalCompiler` protocols;
- controlled `ArtifactOntologyAlignmentProvider` and
  `ProvidedSemanticDeviationScorer` boundaries.

Implemented M11-B physical search:

- deterministic child-before-parent placement order;
- configured exchange strategies with automatic single-strategy resolution,
  branching only for explicitly supplied alternatives, and explicit
  infeasibility when none exists;
- lower-bound priority queue, one budget unit per processed `ExtractMin`,
  strict incumbent replacement by lower conservative upper cost, successor
  pruning, early bound termination, and anytime-prefix records.

Implemented M11-C cost and trace layer:

- positive complete-plan log-cost observations in a versioned append-only
  JSONL store;
- deterministic features with explicit missing-value flags;
- an immutable RBF Gaussian-process snapshot in log-cost space;
- finite combinatorial state-space bounds, per-interpretation and across-task
  confidence utilities, positive raw-cost bounds, and deterministic JSONL
  traces.

The repository has no NumPy, SciPy, or scikit-learn dependency. The M11 GP is
therefore a deliberately small standard-library implementation using a
jittered Cholesky factorization, isolated from the algebra core and tested on
controlled small planning datasets.

Implemented M11-D composition and experiments:

- M10 structured candidates through versioned alignment, supplied semantic
  deviation, deterministic lowering, bounded physical search, strict
  `C_bar < T_max`, one representative per interpretation, positive-utility
  Nash ranking, and deterministic top K;
- an adapter to existing M9 compilers or structured unsupported boundaries;
- `python -m xgap.experiments.physical_planner --config <path>` and complete
  `runs/<run_id>/` planner artifacts;
- a test/experiment-only tiny exhaustive oracle with true-cost regret,
  reachable/processed/generated/pruned metrics, pruning and reduction
  measures, budget-quality curves, and the `eta_search + eta_select`
  decomposition.

Controlled M11 inputs are:

- `examples/configs/m11_candidates.json`;
- `examples/configs/m11_alignment.json`;
- `examples/configs/m11_controlled_planner.json`.

These are deterministic fixtures, not a production ontology, automated
alignment system, ontology reasoner, live model, or benchmark dataset.

The current deterministic `PathPatternQuery` lowering preserves selector
`GroupBy`/`Projection` operators. Neo4j and Fuseki profiles correctly reject
those complete logical plans under current M8/M9 coverage, so the controlled
end-to-end M11 demo selects the reference evaluator. M11 does not bypass the
logical plan by compiling the original pattern directly and does not expand
M9 selector coverage. Direct logical fragments already within M9 remain
compilable through the adapter.

Latest M11 verification:

- `python -m pytest tests/test_m11_contracts.py tests/test_m11_search.py tests/test_m11_cost.py tests/test_m11_planner.py tests/test_m11_oracle.py tests/test_m11_runner.py tests/test_m11_compiler_adapter.py -q`:
  26 passed.
- `python examples/m11_physical_planner_demo.py`: passed; 2 selected plans,
  both with conservative upper estimate `6.289246`.
- `python examples/m11_exhaustive_oracle_demo.py`: passed; 3 reachable states,
  3 processed states, oracle and BnB true cost `2.0`, log-cost regret `0.0`.
- `python -m pytest`: 298 passed, 2 skipped.
- `./scripts/run_acceptance.sh`: passed, including harness check, full pytest,
  all M0-M10 examples, and both M11 demos.

See `docs/m11_ontology_bounded_physical_planning.md`.

## M12-A Experiment Artifact Contract + Dataset Bundle

M12-A is completed. It freezes and implements the experiment-facing
contracts around the existing M10/M11 deterministic pipeline without
changing M11 planning behavior.

Implemented M12-A artifacts and APIs:

- stable SHA-256 canonical hashing that excludes resolved local bundle roots;
- `DatasetBundle`, normalized question/entity/alignment/schema records, and
  the four-way fragment-support taxonomy;
- validated ontology graphs with positive `H`, directed shortest-hop
  subsumption distance, and explicit admissible sibling pairs;
- directional semantic deviation with fixed multipliers `0`, `1/3`, `2/3`,
  and `1`, uniform slot aggregation, and symbolic `infinity` for missing,
  incomplete, unrelated, or inadmissible evidence;
- the default epsilon sweep `{0, 0.1, 0.25, 0.5, 0.75, 1.0}` with config
  override support;
- `ModelBundle` and prompt contracts plus an offline M10 mock response
  bundle, with no live model endpoint;
- `ExperimentSpec`, GP/calibration and M11 feature-schema references,
  execution protocol, explicit artifact availability, baseline IDs,
  ablation switches, and grouped nullable metric records;
- frozen run layout and traceable manifest with explicit unavailable
  CUDA/GPU/Docker/backend-version fields;
- `python -m xgap.experiments.run --config <path>` for the controlled
  `full_xgap` development path only.

The frozen GP experiment protocol retains the M11 RBF GP and
`log_execution_cost` target. Future calibration samples complete physical
plans into `D_0`, fits hyperparameters once on `D_0`, freezes those
hyperparameters during evaluation, and permits posterior updates only
between tasks. M12-A serializes and validates this protocol; it does not
collect real observations or perform server calibration.

The controlled development bundle at `datasets/financial_risk_dev/` contains
20 explicitly synthetic cases spanning exact, specialization,
generalization, explicit sibling, inadmissible/missing/incomplete mapping,
fixed path, filter, compiler/representation gaps, multiple interpretations,
and placement alternatives. It reuses the existing native financial-risk
load artifacts. It is not the final paper benchmark.

The formal development run used two currently representable OUT-path cases
and three controlled candidates. It produced 27 files under
`runs/m12-financial-risk-xgap-dev/`, including logical and physical plans,
search traces, reference logical query artifacts, manifests, and explicit
`not_available` backend-result records. Both questions completed
successfully. No backend execution is claimed.

Frozen baseline IDs:

`full_xgap`, `random_feasible`, `mean_only`, `no_pruning`,
`no_online_update`, `single_backend`, `exhaustive_oracle`, and
`direct_text2graphquery`.

Frozen ablation switches:

`no_uncertainty`, `no_pruning`, `no_online_learning`, `no_semantic_bound`,
`cost_only`, and `no_nash`.

M12-A executes only the controlled `full_xgap` development path. M12-D
subsequently adds executable baseline and ablation policies around the frozen
pipeline.

Latest M12-A verification:

- `PYTHONPATH=src python -m pytest tests/test_m12_semantic.py tests/test_m12_contracts.py tests/test_m12_runner.py -q`: 15 passed.
- `python examples/m12_experiment_contract_demo.py`: passed; 2/2 questions
  succeeded and 27 artifact files were produced in the temporary run.
- `PYTHONPATH=src python -m xgap.experiments.run --config experiments/configs/financial_risk_xgap_dev.json`: passed; 2/2 questions succeeded and
  the frozen run tree was produced.
- `python -m pytest`: 313 passed, 2 skipped.
- `./scripts/run_acceptance.sh`: passed, including the harness, full pytest,
  all previous examples, both M11 demos, and the M12-A demo.

M12-B subsequently replaces the controlled inference inputs with the bounded
live/runtime path described below. M12-C subsequently implements real-backend
D0 collection capability and the online posterior lifecycle. M12-D now
provides executable baselines, ablations, and server orchestration.

See `docs/m12_experimentalization.md`.

## M12-B Live LLM + Ontology/Alignment Artifacts

M12-B is completed. The same configuration-driven M12 runner now selects
either the existing M12-A mock path or a live structured provider path from
`ExperimentSpec` and `ModelBundle`; the M11 physical planner is unchanged.

Implemented M12-B boundaries:

- a generic `OpenAICompatibleStructuredCandidateProvider` implementing the
  existing M10 `StructuredCandidateProvider` protocol;
- one generation call and at most one schema/syntax repair call, with exact
  generation/repair counts and exact sanitized assembled requests in run
  artifacts;
- a fixed DashScope ModelBundle for `qwen3-max-2026-01-23` and a portable
  configuration-only vLLM OpenAI-compatible template;
- deterministic bounded lexical/alias retrieval over the versioned ontology,
  entity catalog, source schema snapshot, and backend mappings;
- per-question `PromptSchemaView`, explicit query anchors, separate candidate
  slot realizations, prompt-visible ID validation, full slot-coverage checks,
  real kind-compatible pattern-component validation, and explicit
  missing-mapping failures;
- `FileBackedRuntimeAlignmentProvider`, which creates real runtime inputs for
  the frozen M12-A directional ontology-hop `c_sem` implementation without
  using benchmark gold artifacts;
- live invocation, exact sanitized assembled requests, usage, prompt-view,
  query-slot, grounding, alignment, diagnostics, and optional live-generation
  metrics artifacts;
- stable failure categories for provider, parsing, repair, grounding,
  mapping, semantic, representation, and compiler boundaries.

The anti-leakage boundary excludes gold answers, gold logical forms, gold
alignments, and evaluation labels from runtime retrieval, prompts, model
requests, candidate validation, semantic deviation, and M11 planning. The
runtime artifact loader has no gold-bearing DatasetBundle reference after
construction. Gold remains available only to a future explicit evaluation
path.

The financial-risk ontology remains a controlled development artifact. The
retriever is deterministic lexical/alias retrieval, not a full OWL/DL
reasoner. The live provider emits grounded `PathPatternQuery` JSON only;
native Cypher, SPARQL, or GQL remains deterministic compiler output.

The M12-B end-to-end audit is recorded in
`docs/report/m12b_llm_boundary_audit.md`. Its final verdict is PASS after the
required fixes and a credentialed post-fix smoke. The fixes persist
`llm_requests.jsonl`, reject empty semantic context, validate typed
`component_ref` attachments, and clarify the zero-shot semantic contract and
interpretation diversity. They do not change M11, `c_sem`, PathPatternQuery
semantics, or downstream planning.

M12-B itself does not implement model training, LoRA, model deployment, real
D0 collection, GP calibration, online posterior updates, executable
baselines, ablation matrices, KGQA evaluation, or server-scale orchestration.
M12-C and M12-D subsequently add calibration/lifecycle and experiment
orchestration; model training, deployment, and KGQA remain later work.

Latest M12-B verification:

- `python -m pytest tests/test_m12b_provider.py tests/test_m12b_runtime_alignment.py tests/test_m12b_runner.py tests/test_m12b_live.py -q`:
  23 passed, 1 skipped;
- `python -m pytest tests/test_llm_boundary.py tests/test_m12_contracts.py tests/test_m12_runner.py tests/test_m12_semantic.py tests/test_m12b_provider.py tests/test_m12b_runtime_alignment.py tests/test_m12b_runner.py tests/test_m12b_live.py -q`:
  45 passed, 1 skipped;
- `python -m pytest -q`: 336 passed, 3 skipped;
- the skipped M12-B test is the real DashScope smoke test, gated by both
  `XGAP_RUN_LIVE_LLM=1` and `DASHSCOPE_API_KEY`;
- credentialed post-fix command
  `XGAP_RUN_LIVE_LLM=1 PYTHONPATH=src python -m pytest tests/test_m12b_live.py -v`:
  1 passed in 33.64 seconds;
- the post-fix run made one generation call and no repair call, persisted an
  exact `llm_requests.jsonl` payload whose hash matches the invocation, and
  produced one fully validated logical/physical candidate;
- the fake-HTTP integration exercised the real OpenAI-compatible provider,
  runtime grounding, frozen `c_sem`, unchanged M11 planner, and live artifact
  layout without network access;
- the M12-A mock runner regression planned 2/2 questions successfully;
- `./scripts/run_acceptance.sh`: passed with 336 tests passed, 3 gated live
  tests skipped, and all existing examples successful.

## M12-C Cost Calibration + Online GP Protocol

M12-C is completed. It adds a separate, server-friendly calibration path and
does not modify `PathPatternQuery`, logical lowering, M11 BnB, `c_sem`, the
Nash objective, or the frozen M12-B model/alignment boundary.

Implemented M12-C boundaries:

- typed calibration config, case, workload, plan, measurement, D0, calibrated
  model, posterior snapshot, and posterior-update artifacts;
- deterministic stratified selection of complete plans from a dedicated
  calibration split;
- M9 compilation followed by repeated execution through the existing Neo4j
  and Fuseki clients, including support for M9 `compiled` native artifacts;
- raw millisecond and `log(execution_ms)` persistence with all warmup and
  measured repetitions retained;
- separate `D0_neo4j` and `D0_fuseki` datasets with no cross-backend
  observation mixing;
- deterministic negative-log-marginal-likelihood calibration of the existing
  RBF GP family, with repeated-run noise evidence and a positive noise floor;
- persisted config, protocol, descriptor, feature-schema, D0, model, and
  hyperparameter hashes;
- immutable `BackendCostModelRegistry` snapshots that expose calibrated
  estimators through the existing M11 `CostEstimator` interface;
- `OnlinePosteriorLifecycle`, which gives task q one fixed `D_(q-1)` snapshot
  and atomically appends only successful executed complete-plan observations
  after the whole task batch finishes;
- backend-isolated updates, batch IDs and K_q records, temporal anti-leakage
  checks, persisted execution evidence, and unchanged hyperparameter hashes;
- explicit unavailable handling for unsupported distributed cross-backend
  movement measurement;
- a two-plan financial-risk development workload, a dual-backend calibration
  config, an offline deterministic demo, and an optional gated live smoke.

The local offline development run created two D0 records per backend and two
independently calibrated model artifacts. It demonstrated that the calibrated
posterior differs from the development prior for at least one state. These are
explicit fake development latencies and are not claimed as real Neo4j/Fuseki
calibration results.

Real server command:

```bash
XGAP_RUN_BACKENDS=1 PYTHONPATH=src \
python -m xgap.experiments.calibrate \
  --config experiments/configs/financial_risk_gp_calibration_dev.json
```

Optional live pytest additionally requires `XGAP_RUN_CALIBRATION=1`. Default
pytest remains fully offline.

M12-C does not add a joint backend-aware GP, cross-backend movement-cost
learning, distributed runtime orchestration, new compiler coverage, baseline
or ablation execution, matrix scheduling, new benchmarks, semantic-deviation
changes, ontology reasoning, or new LLM behavior. M12-D subsequently adds
baseline/ablation execution and matrix scheduling without adding the other
features.

Latest M12-C verification:

- `PYTHONPATH=src python -m pytest tests/test_m12c_calibration.py tests/test_m12c_live.py -q`:
  9 passed, 1 live calibration test skipped;
- the M11/M12-A/M12-B focused regression suite: 57 passed, 1 gated live LLM
  test skipped;
- `PYTHONPATH=src python examples/m12c_calibration_demo.py`: passed, with 2
  explicit fake D0 records and one calibrated model per backend;
- `python -m pytest`: 345 passed, 4 gated live tests skipped;
- `./scripts/run_acceptance.sh`: passed, including the harness, full pytest,
  all historical examples, and the M12-C offline calibration demo.

The real M12-C backend calibration was run separately on the server after both
native smoke queries returned nonempty results. The two backend live tests and
the live calibration test reported `3 passed in 2.11s`; calibration reported
`measurement_source=real_backend` and D0 observation count 2 for each of
Neo4j and Fuseki. These are development acceptance observations, not final
paper calibration data.

## M12-D Baselines/Ablations + Server Experiment Runner

M12-D is completed. It composes the frozen M10-M12-C boundaries into a
declarative, resumable experiment system without changing logical semantics,
`c_sem`, M11's default BnB/Nash behavior, or GP formulas.

Implemented M12-D boundaries:

- explicit policies for `full_xgap`, seeded `random_feasible`, `mean_only`,
  `no_pruning`, `no_online_update`, configured `single_backend`, controlled
  bounded `exhaustive_oracle`, and separate `direct_text2graphquery`;
- real behavior for `no_uncertainty`, `no_pruning`, `no_online_learning`,
  `no_semantic_bound`, `cost_only`, and configured `no_nash` ablations, with
  contradictory combinations rejected;
- immutable candidate/grounding artifacts shared across comparable planning
  methods, with prompt/model/grounding/artifact hashes and exact live request
  evidence where available;
- an online task runner that snapshots `D_(q-1)`, fixes it for all planning
  decisions in task q, executes selected complete plans, then atomically
  commits K_q observations to produce D_q;
- deterministic matrix expansion and run IDs, completed-run skipping,
  explicit resume/retry, per-task recovery records, collision checks, and a
  bounded 12-run financial-risk development matrix;
- normalized execution cardinality and separate
  `execution_success_nonempty`, `execution_success_empty`, and
  `execution_error` statuses;
- calibration-query cardinality diagnostics with explicit expected-nonempty
  cases, relevant mapped IRIs, and separate empty-success handling;
- method-aware search traces, cost prediction/confidence observations,
  separated latency/result/failure metrics, and JSON/CSV aggregation;
- development/pilot/paper modes, environment capture, readiness checks, and a
  paper freeze manifest. Paper mode supports Python 3.10+ and requires pinned,
  identified backend versions/images plus a passing RDF mapping/data/compiler
  contract. Exact runtime and image identity remain recorded per run.

Offline completion verifies the runner lifecycle and D0 -> D1 -> D2
transition using deterministic fake backend timings. The real M12-D online
D0 -> D1 -> D2 pilot remains a separately gated server command and is not
claimed by local completion.

M12 completion means experiment infrastructure is ready for paper-grade
dataset/model artifact preparation and large-scale runs. It does not mean
final datasets or paper numbers exist, MetaQA/QALD are integrated,
cross-backend distributed execution or transfer-cost learning exists, or new
compiler fragments are supported.

## Post-M12-D Paper-Environment Hardening

This completed hardening pass did not change `PathPatternQuery`, logical
algebra, `c_sem`, M11 search/ranking, GP formulas, prompt/schema contracts,
baselines, or M12-D experiment semantics.

- package metadata, paper readiness, and the online paper gate now support
  Python 3.10+; the dependency and 3.10 syntax/API audit found no blocker;
- paper backend startup uses `services/.env.paper` and requires current
  validated `repository@sha256:<digest>` image references, while development
  floating tags remain warning-only;
- environment manifests record repository, tag, digest, local image ID and
  RepoDigests when visible, plus backend-reported software version where
  available;
- the DatasetBundle backend mapping is now the sole source for M9 SPARQL RDF
  IRIs; missing or invalid mappings fail explicitly;
- the financial-risk RDF bundle retains reified Transfer records and adds the
  mapped direct `transfersTo` predicate needed by the existing bounded M9 path
  fragment;
- `python -m xgap.experiments.backend_mapping_audit` verifies
  `URI_data == URI_mapping == URI_m9`, and readiness fails on any unresolved
  mismatch;
- readiness also rejects paper use of Fuseki calibration artifacts whose
  query mapping hash is absent or differs from the active DatasetBundle, so
  pre-hardening D0 must be regenerated after the updated data is loaded;
- configured expected-nonempty live calibration cases assert positive Fuseki
  row counts; arbitrary empty results remain valid successful executions.

## Required Acceptance Command

```bash
./scripts/run_acceptance.sh
```

# Latest Known Acceptance Status

M0-M13-E3B.5 local implementation tests passed. M7 backend smoke and M12-C real
calibration acceptance passed on the server. A real DashScope M12-B
development run completed one question with one generation call, no repair,
and three candidates; its credentialed post-fix rerun verified the revised
prompt, typed grounding, and exact-request artifact. M12-D live online and
direct-baseline tests remain explicitly gated and have not been claimed from
the local completion run.

Latest recorded command results:

- `PYTHONPATH=src python -m pytest`: 492 passed, 10 skipped, including the
  focused M13-E1 catalog-v2 fixture, M13-E2 CWRU/vLLM contracts, M13-E3 source
  checksum/restart/integrity/audit tests, and M13-E3A frozen-inventory,
  mode-selection, compatibility-report, and CPU workflow tests. Three M13-E3A
  file-level Parquet tests are skipped only when optional PyArrow is absent;
  M13-E3A.1 covers both old and new curl capability paths. M13-E3B covers
  question-only construction, query isolation, local type enrichment,
  Catalog-v2 compatibility, local loss attribution, pending-full reports, and
  E3B.1 `PosixPath` materialization normalization. E3B.2 adds persisted-rank
  entity retrieval, global-FTS non-regression, Top-k prefix/isolation, and
  relation/type diagnostic-stage regressions. E3B.3 adds phrase-tier,
  term-aggregation, stable-tie, slot-isolation, domain/range-coherence,
  type-provenance, and no-gold contract regressions. E3B.4 adds exact
  direction/role mapping, runtime accept/reject, explicit-versus-effective
  Type reachability, prompt truncation, and endpoint audit-artifact regressions.
  E3B.5 adds explicit query-local profile success, contract/ID/hash fail-closed
  cases, structured endpoint-contract request propagation, conditional metric
  separation, order-independent exact-ID-set validation, and CWRU wrapper
  syntax/path checks.
- `./scripts/run_acceptance.sh`: passed with the same 492 passed and 10 skipped,
  followed by all required deterministic examples and acceptance checks.
- `PYTHONPATH=/private/tmp/xgap-m13e3a-pyarrow:src python -m pytest
  tests/test_m13e3a_freebase_parquet.py tests/test_m13e3_freebase_catalog.py
  -q`: 14 passed, including N-Triples/Parquet catalog and retrieval parity.
- `PYTHONPATH=/private/tmp/xgap-m13e3a-pyarrow:src python -m
  xgap.experiments.freebase_sources smoke ... --max-row-groups 1`: passed on
  the real frozen `0000` shard; 649,794 rows contained every required construct.
- `PYTHONPATH=src python -m pytest tests/test_m13e3b3_schema_ranking.py
  tests/test_m13e1_reachability_contract.py tests/test_m13e3a_freebase_parquet.py
  tests/test_m13e3b_local_catalog.py -q`: 40 passed, 3 skipped.
- `bash -n scripts/server/build_grailqa_local_catalog.sh`, `bash -n
  scripts/slurm/build_grailqa_local_catalog.sbatch`, and `git diff --check`:
  passed.
- M13-D offline reachability reproduction: catalog entity 12/150; retrieval
  Top-20 entity/relation/type 10/47/67; deployed prompt 9/22/38; joint 0/150.
- M13-E1 local readiness: refused the live path because catalog v2 and
  reachability v2 are explicitly incomplete; no provider call was made.
- full official GrailQA audit command: completed 64,331 classifications with
  23,156 supported and 41,175 unsupported records.
- full GrailQA v2 audit command: completed 64,331 classifications with 35,439
  supported and 28,892 unsupported records; the gold-available support ratio
  is 69.352%.
- GrailQA pilot command: built and validated 150 questions with bundle hash
  `dd27f7fecdb226bef89beb50339932793bd5ffe1b987e1ce4144f6391caacd72`;
  its controlled `Q=13/19/25` vertical slice completed.
- M13-D deterministic fake-provider run: accounted for all 150 frozen IDs,
  completed 150 fixture requests, produced 450 validated and grounded
  candidates, used no repairs, and wrote every required output. It is marked
  orchestration-only and makes no accuracy claim.
- full KQA Pro audit command: completed 117,970 classifications with 1,690
  structurally/planning-supported and 116,280 unsupported records; current
  integrated KQA Pro execution coverage remains zero.
- `python -m pytest` over the focused M9-M12-D and hardening regression set:
  109 passed, 5 live-gated tests skipped.
- `python -m xgap.experiments.backend_mapping_audit --dataset
  datasets/financial_risk_dev`: passed with no three-way IRI mismatches.
- `python examples/quantified_pattern_demo.py`: passed.
- `python examples/compiler_mvp_demo.py`: passed.
- `python examples/llm_boundary_demo.py`: passed.
- `python examples/m11_physical_planner_demo.py`: passed.
- `python examples/m11_exhaustive_oracle_demo.py`: passed.
- `python examples/m12_experiment_contract_demo.py`: passed; 2/2 controlled
  questions and 27 artifact files.
- `python examples/m12c_calibration_demo.py`: passed; the explicit offline
  fake path produced 2 D0 records and one calibrated GP per backend.
- `python examples/m12d_experiment_matrix_demo.py`: passed; 12 runs and 12
  aggregate groups completed with frozen candidate reuse.
- `./scripts/run_acceptance.sh`: passed with 436 passed and 7 live-gated
  skips, including harness check, pytest, all existing examples,
  `examples/quantified_pattern_demo.py`,
  `examples/compiler_mvp_demo.py`, `examples/llm_boundary_demo.py`, both M11
  demos, the M12-A demo, the M12-C calibration demo, and the M12-D matrix
  demo. The M12-B fake-HTTP and M12-D offline paths are exercised by pytest.
- `git diff --check`: passed.

Expected checks include:

- harness check
- pytest
- examples/core_algebra_demo.py
- examples/plan_print_demo.py
- examples/recursive_demo.py
- examples/solution_space_demo.py
- examples/semantic_audit_demo.py
- examples/lowering_demo.py
- examples/pattern_lowering_audit_demo.py
- examples/quantified_pattern_demo.py
- lowering tests
- pattern-lowering audit tests
- quantified-pattern tests
- M9 compiler tests
- M10 LLM-boundary tests
- M11 contracts, search, cost, main-planner, oracle, and runner tests
- examples/m11_physical_planner_demo.py
- examples/m11_exhaustive_oracle_demo.py
- M12-A semantic, bundle/contract, and runner tests
- examples/m12_experiment_contract_demo.py
- M12-C calibration, model, measurement, and online-posterior tests
- examples/m12c_calibration_demo.py
- M12-D methods, ablations, candidate freeze, direct baseline, online
  lifecycle, matrix, resume, aggregation, and readiness tests
- examples/m12d_experiment_matrix_demo.py
