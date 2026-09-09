# Research-question and dataset coverage inventory

## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: plan
- Origin Date: 2026-09-09
- Verification Status: source-inspected coverage inventory only, not completed
  experiments or a fresh reconstruction of the remote measurements
- Version Label: research_question_dataset_coverage_v1
- Scope: existing repository protocols, accepted selection records, recorded
  admissions, implementation boundaries, and the user's request to evaluate
  every research question across every included dataset

## Purpose and authority boundary

The existing experiment architecture separates FinBench physical evaluation
from GrailQA semantic evaluation. That division does **not** satisfy the user's
requested cross-dataset research coverage. This inventory makes the missing
cells visible; it does not dismiss them as not applicable, redefine research
questions around whichever experiments already pass, or authorize new runs.

No model, backend, ontology-service, or web call was made for this inventory.
No raw result, frozen protocol, scientific selection, or author receipt was
changed. Recorded results below retain their original scope and verification
status. A new cross-dataset protocol must preserve those records and explicitly
bind any new population, semantic reference, placement, baseline, and analysis
decisions before measurement.

The old protocol contains scale/integration cutoff choices. They are recorded
here as **historical selected protocol values**, not a freshly verified venue
deadline, a new deadline decision, a promise of completion, or permission to
drop an unfinished dataset from the user's latest coverage requirement.

## 1. Existing research-question identifiers and contracts

The exact numbered physical contracts are in
[`m15_finbench_paper_protocol_draft_v1.json`](../../experiments/configs/m15_finbench_paper_protocol_draft_v1.json).
Their original field values are retained here rather than replaced with new
global RQ names.

| Existing ID | Protocol population and estimand | Comparison and metric |
|---|---|---|
| `RQ-P1` | `heldout_instances_from_seen_F1_F2_families`; `geometric_mean_within_query_end_to_end_latency_ratio` | `family_memory_zero_profile` versus `current_query_dual_profile`; `selection_plus_serving_elapsed_ms` |
| `RQ-P2` | `heldout_instances_from_seen_F1_F2_families`; `query_level_selection_quality_and_resource_regret` | `family_memory_zero_profile` versus `fixed_routes_family_global_and_current_query_dual_profile`; `winner_accuracy_latency_regret_bytes_regret_frontier_jaccard` |
| `RQ-P3` | `entirely_heldout_F3_family`; `cold_family_serving_cost_and_regret` | `predeclared_family_fallback` versus `fixed_routes_current_query_dual_profile_and_observed_oracle`; `latency_bytes_winner_accuracy_regret` |

`RQ-P1` includes current-query acquisition and reports offline training
separately. Its inferential unit is the query, with within-query median
aggregation, fixed query bootstrap, and paired sign-flip testing. `RQ-P2`
reports both serving-only and selection-plus-serving cost, with Holm adjustment
for defined secondary paired tests. `RQ-P3` is a separate descriptive cold-start
stratum: it has no inferential test, and its fallback must not be relabeled
family-memory prediction. These boundaries are also documented in
[decisions D169 and D172](../decisions.md).

The exact semantic pilot identifier is
`"research_question": "RQ1 ontology-bounded semantic interpretation only"` in
[`grailqa_semantic_pilot_v1.json`](../../experiments/specs/grailqa_semantic_pilot_v1.json).
The later
[`grailqa_semantic_paper_protocol_draft_v2.json`](../../experiments/configs/grailqa_semantic_paper_protocol_draft_v2.json)
defines a proposed semantic comparison without introducing another explicit
`rq_id`:

- Treatment: `ontology_bounded_c_sem_epsilon_frontier`.
- Proposed comparator: `model_confidence_top1_same_grounded_candidate_set`;
  `first_valid_grounded_candidate` remains an author-selection alternative.
- Primary outcome: `exact_canonical_structural_interpretation_match`.
- Other outcomes: candidate recall in top three, nonempty admissible coverage,
  hard-constraint violations, returned frontier size, calls, repairs, tokens,
  latency, and separately reported joint prompt reachability.
- Shared generation, validation, and grounding; rank-1 versus rank-1 primary
  comparison. Recall@3 and the full return frontier are not substituted for
  rank-1 accuracy.
- Query-level exact paired McNemar, fixed paired bootstrap, and secondary Holm
  analysis are implemented but have not produced an admitted 150-query result.

### Original-source reconciliation: three distinct numbering schemes

The read-only project PDFs were subsequently inspected, including rendered
pages. Both passed structural PDF preflight with all declared pages readable:

- `Towards_Agentic_Graph_Query_Planning_under_Ambiguity_VLDB_workshop_Camera_Ready_.pdf`,
  5 pages, SHA-256
  `6340c46d5fbd0323ef6d1ce65d7162041c154a089056a468f768e10c8b6cc4ce`.
  Page 2, **Research questions**, numbers three questions: (1) query modeling,
  (2) query representation generation, and (3) deployable cross-platform plan
  generation. Page 4, **Research Plan**, connects them to supported operator
  fragments, bounded interpretation generation/validation, and physical
  placement/cost/selection. These are not the FinBench `RQ-P1/P2/P3` estimands.
- `OntoXGAP_whitepaper.pdf`, 13 pages, SHA-256
  `cf0c4e06910909284bccc88bcceafc3699ed67b4e7976eeef632e7236197f36c`.
  Pages 10–11, **Evaluation Plan**, explicitly define `EQ1` semantic quality,
  `EQ2` bounded relaxation, `EQ3` planning efficiency, `EQ4` execution
  efficiency, and `EQ5` robustness, with baselines, metrics and ablations.

The original research content is therefore available; final submission RQ
numbering remains an author-level reconciliation, not a missing-source excuse.
Keep the workshop's three questions, the whitepaper's five evaluation questions,
and the frozen experiment identifiers distinct. No historical protocol or
admitted result is renamed here. The source proposals do not establish that
their features, guarantees, datasets or comparisons are already implemented.

Query modeling additionally needs an explicit supported-fragment and
operator/backend-capability account, with correctness/equivalence validation;
runtime tables alone cannot establish expressivity or a general theorem.

## 2. Dataset and artifact scope actually recorded

The accepted
[Option-A author selection](../../experiments/artifacts/m15_finbench_paper_protocol_author_selection_a_v1.json)
is distinct from unselected values in the older draft. It selects:

| Dataset or scale | Recorded scientific role | Current scope limitation |
|---|---|---|
| FinBench-derived heterogeneous workload, SF0.1 | Primary physical population: 48 answer-independent instances | F1 and F2 have 32 cross-fit query units together; F3 has 16 cold-family descriptive units; not a conformant official FinBench score |
| GrailQA v1.0 / Freebase, frozen150 | `grailqa_primary` semantic track | 120 train-source plus 30 dev-source questions, not the full public benchmark; current paper runner is explicitly semantic-only |
| FinBench SF1 | `sf1_if_feasible_by_2026-09-12_else_omit` robustness choice | Historical conditional selection; no admitted SF1 run identified here |
| FedShop subset | `fedshop_if_ready_by_2026-09-24_else_omit` external-validation choice | Historical conditional selection; no implemented dataset-specific protocol or admitted result identified here |

The
[public artifact stack](../m15_paper_experiment_acceleration_plan.md)
also records three important distinctions:

- FIBO is a proposed limited **ontology mapping artifact**, not another dataset.
  A pinned subset and mappings are necessary if that interoperability claim is
  retained; no such completed artifact was identified in this inventory.
- FinBench SF0.01 and the earlier controlled financial-risk world are
  development/correctness evidence. They do not automatically add formal
  confirmatory populations or replace missing public-data cells.
- KQA Pro is a historical public feasibility audit. It is not silently added
  to the accepted primary selection, nor silently treated as covered. If the
  author intends it within "every dataset," its scope must be recorded and its
  missing integration must be completed. The
  [current KQA Pro status](../status.md) reports 1,690 supported linear
  conversions but zero integrated end-to-end execution.

## 3. Cross-dataset coverage matrix

`Admitted` below refers only to the already recorded independent admission,
not a new audit performed for this document. `Missing` is unfinished required
work for any dataset retained in the full cross-dataset study. `Development`
does not satisfy a confirmatory cell. No cell is marked not applicable.

| Dataset / scale | Existing `RQ1` semantic interpretation contract | `RQ-P1` physical end-to-end contrast | `RQ-P2` physical selection / regret | `RQ-P3` cold-family boundary |
|---|---|---|---|---|
| FinBench SF0.1 primary | **Missing:** no admitted public semantic/ontology/clarification comparison | **Admitted:** exact 32-query seen-family contrast | **Admitted:** exact seen-family controls and resource analysis; instance-specific memory advantage not isolated | **Admitted descriptive only:** exact 16-query cold F3 fallback report, not a cold-family inference claim |
| GrailQA frozen150 primary | **Missing formal result:** 18-query audited negative development preflight; 150-query execution/admission absent | **Missing:** real federated execution/placement and physical protocol | **Missing:** competing executable physical plans and measured controls | **Missing:** executable family/split/fallback protocol and measurements |
| FinBench SF1 conditional robustness | **Missing:** scale-specific semantic protocol and evidence | **Missing:** source/load/correctness and measured scale result | **Missing:** scale-specific selection/control measurements | **Missing:** scale-specific family and fallback evidence |
| FedShop conditional external slice | **Missing:** semantic inputs/references/ontology and protocol | **Missing:** dataset integration, frozen physical protocol, execution | **Missing:** candidate space, controls, and measured analysis | **Missing:** family definitions, split, fallback, and measurements |
| FinBench SF0.01 development | **Missing formal result:** no admitted semantic comparison identified | **Development correctness only:** no admitted confirmatory E2E contrast identified | **Development mechanism/correctness only:** no admitted confirmatory control comparison identified | **Missing formal result:** no admitted cold-family study at this scale |
| Controlled financial-risk development world | **Development mechanisms only:** bounded interpretations, authority, and frontier execution | **Development pilots only:** not public-dataset confirmatory evidence | **Development pilots only:** not cross-dataset generalization evidence | **Missing formal result:** no admitted cold-family confirmatory study identified |
| KQA Pro legacy feasibility; primary inclusion unresolved | **Missing formal result:** conversion feasibility is not semantic generation evaluation | **Missing:** mappings, loading, normalization, and executed backend snapshot | **Missing:** live competing plans and cost/control measurements | **Missing:** family/split/fallback design and executed evidence |

### Original whitepaper evaluation questions across both primary datasets

The table above inventories current experiment contracts. The table below
exposes the broader original research obligations; neither replaces the other.

| Original question and required comparison | FinBench SF0.1 primary | GrailQA frozen150 primary |
|---|---|---|
| `EQ1` Semantic quality: ontology-relative versus schema-only and LLM-only; entity/predicate/path and complete interpretation accuracy | **Missing:** public semantic input/reference population and measured semantic baselines | **Missing formal result:** audited negative development preflight, no positive or admitted 150-query semantic comparison |
| `EQ2` Bounded relaxation: precision–recall–cost tradeoff under epsilon | **Missing:** measured joint semantic/answer/cost tradeoff; old physical frontier overlap does not substitute | **Missing:** formal epsilon evaluation and executable answer/cost evidence |
| `EQ3` Planning efficiency: semantic-dominance and cost-bound pruning versus their removal; explored/pruned states and planning latency | **Missing:** paired pruning/search-space experiment; physical winner accuracy is a different measure | **Missing:** paired pruning/search-space experiment and measured planning overhead |
| `EQ4` Execution efficiency: cross-platform versus centralized migration and pipeline-style execution; latency, data movement and resource cost | **Partial related evidence:** admitted memory/profiling/fixed-route comparisons; centralized/pipeline contrasts and throughput are not established by that admission | **Missing:** genuine competing complete physical plans, federated execution and matching baselines |
| `EQ5` Robustness: partial/noisy ontology mappings and heterogeneous capabilities | **Missing:** cold-family fallback is descriptive evidence about a different perturbation, not an ontology/capability robustness test | **Missing:** mapped perturbation population and executed robustness comparisons |

Every additional dataset retained in the final study inherits these same five
coverage obligations. The conditional/legacy rows above have no admitted
complete EQ1–EQ5 result; they cannot be silently counted as covered or excluded
because integration is unfinished. A source's proposed dataset list is not an
automatic instruction to expand the currently selected dataset population.

### Existing result evidence and limits

The [FinBench recorded admission and reporting section](../status.md) binds
the original runner `cf622cbc024e3aa945213df68e177d2cc1eb7d8a`, 22 measurement
blocks, 1,888 plan runs, and independent audit job `3795042` with 167 passing
checks and no run-tree mutation. Source campaign result SHA-256:
`258ca17c055126d6e95ff5f201e3eb743c3adc11ce92047f624217e179d34235`.
Audit SHA-256:
`6085c977f6cf98fb42d2290ba2bab2cd10d8677675fdef6630452edcb53f64a5`.
Rendered report SHA-256:
`ff087278a59d17c2273b23cc7edf06d054f3fba43db9b4134a8e515cac6a43d0`.

That report records the benefit of avoiding current-query profiling within its
population. Family-global and fixed route A made the same selections as XGAP;
the reported comparison does not independently identify an instance-specific
family-memory advantage. The F3 fallback performed poorly and remains a
separate descriptive result. The
[report implementation](../../src/xgap/experiments/m15_finbench_confirmatory_report.py)
explicitly forbids semantic-ambiguity, ontology, and general-KGQA claims from
this physical result. Its predicted/observed frontier statistic is not a
substitute for an independently validated semantic-interpretation frontier.

The [GrailQA negative preflight report](grailqa_preflight_3795067_validation.md)
records 101 passing integrity checks, 17 successful provider envelopes, 47 raw
candidates, but zero validated-candidate questions out of 18. The five jointly
prompt-reachable questions also produced zero validated candidates. A passing
artifact audit is not a positive semantic result. The separately versioned
[output-contract clarification](grailqa_output_contract_revision_v1.md) and
offline tests do not supply new model measurements or repair the old result.

The [GrailQA feasibility boundary](../status.md) reports one M11 all-local
complete realization per pilot interpretation. Two native compiler targets
are not, by themselves, competing complete federated physical plans. This is a
specific implementation gap to address for cross-dataset physical evaluation,
not a reason to declare its physical cells complete or not applicable.

## 4. Baselines: frozen controls versus still-missing comparisons

| Scope | Existing frozen or proposed methods | Remaining coverage gap |
|---|---|---|
| FinBench seen-family physical protocol | family memory zero-profile; current-query dual profile; family-global/no-instance; fixed A; fixed B; postexecution oracle | Admitted only for the exact SF0.1 population; other included datasets/scales need equivalent executable controls |
| FinBench cold-family physical protocol | predeclared fallback; dual profile; fixed A/B; postexecution oracle | Not family-memory prediction; other datasets need an explicit cold-family contract, not inferred cross-family compatibility |
| GrailQA semantic paper draft | same grounded candidates, XGAP semantic ranking versus confidence top-1 or author-selected first-valid; exact-only, no-equivalence-merge, and no-epsilon/K-pruning ablations | Formal author choices, successful execution, analysis, and independent admission remain missing; this is not an evaluated full selective-agent/clarification experiment |
| Broader physical acceleration plan | also lists pre-query catalog-cardinality heuristic and, if feasible, centralize-all deployment control | These are not methods in the admitted FinBench report; named plans do not establish implementation or comparison |
| Broader semantic acceleration plan | also lists deterministic catalog top-1, bounded Qwen top-1, ontology-expanded proposal without clarification, full XGAP selective route, and clarification removal | These full route comparisons have not been established by the shared-candidate ranking draft or its negative preflight |

Sources: [FinBench methods](../../experiments/configs/m15_finbench_paper_protocol_draft_v1.json),
[GrailQA methods/outcomes](../../experiments/configs/grailqa_semantic_paper_protocol_draft_v2.json),
and [broader baseline/ablation plan](../m15_paper_experiment_acceleration_plan.md).
The GrailQA draft permits gold-simulated clarification only as a postinference
oracle upper bound or explicit exclusion; it is not an observed interactive
treatment and does not demonstrate real user utility or authority cost.

## 5. Concrete artifacts required to fill the gaps

### FinBench semantic and joint semantic-cost evaluation

1. A public-query-bound natural-language input and supported semantic-program
   population, with explicit ambiguity slots, candidates, hard constraints,
   equivalence classes, and separately sealed reference interpretations.
2. Versioned catalog/ontology provenance and mappings. If FIBO is included,
   lock the actual subset and mapping rather than inventing FIBO meanings for
   FinBench-specific predicates or risk categories.
3. Shared-candidate and full selective-route method definitions, their
   applicable ablations, authority events, and complete acquisition/model/user
   cost ledgers. A correctness oracle cannot impersonate user authority.
4. Executable physical candidates and oracle/correctness admission for every
   evaluated semantic interpretation, not only the originally fixed query.
5. A separately frozen protocol, exact population and analysis contract,
   execution authority, inference/selection seals, measured outcomes, and
   independent result admission. Do not relabel the earlier physical campaign.

### GrailQA physical, family-memory, and joint evaluation

1. Hash-bound executable Freebase data/mappings/source placement, loaders,
   native templates, cross-source IDs, and final-answer normalization.
2. At least two genuinely executable complete physical alternatives for each
   compared semantic query, with independently checked semantic equivalence
   and reference answers. Merely compiling one plan to two languages is not
   this artifact.
3. Mapping from the supported interpretations into the M15 semantic-program
   and registered family contracts; answer/cost-independent population and
   cross-fit/cold-family partitions; explicitly chosen cold-start policy.
4. Comparable fixed, profiling, family-global, and family-memory methods,
   acquisition/serving/shadow phase ledgers, oracle isolation, cache/lifecycle
   records, and dataset-bound failure/statistical rules.
5. A new executable protocol and authority chain. The current paper runner's
   `backend_execution=false` boundary must not be bypassed to activate a
   scientifically different experiment.

The current semantic-only gap separately requires reviewed contract changes,
bounded live validation where authorized, all five explicit scientific
choices, the audit-bound preexecution admission, exact 150-query authority,
run/analysis reconstruction, and final paper-result admission. These gates are
specified in the [GrailQA runbook](grailqa_semantic_paper_runbook.md); possessing
the catalog or passing an integrity audit does not create the missing choices.

### FedShop and additional scales

- FedShop needs an actual source/revision/hash lock, template and instance
  selection, endpoint/source assignments, adapter and equivalent physical
  candidate space, reference correctness, and dataset-specific protocol.
  Semantic and cold-family cells additionally need the real NL/ontology/
  reference artifacts and executable family/split definitions; the public
  federation benchmark alone does not supply those conclusions.
- SF1 needs verified acquisition, loading feasibility and correctness,
  scale-bound population/method controls, and independently audited
  measurements. SF0.1 cannot be relabeled SF1 or extrapolated into a scale
  result. Any changed sampling or candidate semantics need an explicit new
  protocol rather than silent migration of the old authority.
- If KQA Pro is included, finish final mappings, loaders, answer normalization,
  a loaded backend snapshot, executable candidate/family admission, and its
  own scientific/reference population before using the conversion counts as
  evidence for any evaluation cell.

## 6. Completion rule for the requested full coverage

The next coverage ledger must select final RQ numbering against the reconciled
original sources, explicitly list every dataset retained by the author, and
bind each required cell to its
population, input/reference artifacts, supported executable semantics,
baselines, metric/estimand, failure policy, measurement identity, and independent
admission. Until those identities and results exist, the corresponding cell
remains missing, development-only, or scope-unresolved.

This inventory neither authorizes remote jobs nor changes existing execution
authority. It does not select scientific values, omit difficult cells, promise
an experiment date, or declare the system/paper complete. New measurements
must preserve the already admitted FinBench evidence and the original negative
GrailQA result rather than replacing them with a more favorable account.
