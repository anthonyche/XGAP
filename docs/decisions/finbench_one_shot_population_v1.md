# FinBench one-shot evaluation population

## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: plan, followed by authorized offline ETL
- Origin Date:2026-09-12, Asia/Shanghai
- Verification Status: five new tiny checks passed; actual120-group build and artifact audit passed
- Version Label: finbench-v010-sf01-one-shot-120-v1

This concretizes the already approved FinBench/native+matched-RDF priority and
120-instance proposal. It does not change the research question, methods or old
exposure labels. It prepares inputs; it is not a model/engine evaluation run.

## Frozen population and split

Source: the existing SHA-pinned LDBC FinBench v0.1.0 SF0.1 archive. Metadata-only
reading found7771 people,20409 accounts,3892 companies,9699 media and79909 transfers
in the eight tables used by these queries; those four entity counts are not the
entire graph vertex count because the complete archive also contains other types.
Transfer times span2020-06-28 through2022-11-29, amounts are nonnegative with at
most2 decimal places, and the largest source-account outdegree is336. This was a
3.557s read/validation action, not a benchmark execution or catalog build.

The frozen design is `experiments/protocols/finbench_one_shot_population_v1.json`.
The two known copies of the old48 public instances are byte-identical at
e49302d6cce2122c0a75181ce33fbcbb9fdf2465f072a8be508b9cbad7285542.
Their public parameters supply exclusions; old answers/results are never opened.

| Family | Candidate frame and group unit | Stratification |
|---|---|---|
| Direct transfers | All person owners; exclude every old F1 person anchor | Four rank quartiles of transfer count from that person's accounts to company-owned accounts, before blocked filtering |
| Increasing temporal paths | All accounts, including zero outdegree; exclude every old F2 account anchor | Four rank quartiles of outgoing transfer count; no old degree<=32 restriction |
| Risk aggregation/ranking |80 disjoint equal-duration millisecond bins over the observed time span; one source risk label per bin, cycling through sorted labels | Four time-position rank quartiles |

Every stratum selects10 groups by a seeded SHA-256 order. A separate seeded order
assigns2 development,4 estimator-training and4 evaluation groups. Therefore each
family has40 groups and the total split is24/48/48. IDs break structural-feature
ties deterministically. F1/F2 groups do not reuse an anchor across splits; F3 groups
do not share time intervals. Same-family old anchors are excluded entirely, not
only exact old parameter tuples. F3 excludes any same-risk interval with temporal
intersection/union>=0.8 against an old query. All constraints are applied before
reference evaluation, without resampling by answers or method outcomes. Insufficient
frames fail explicitly; they cannot silently shrink the population.

Three authored equivalent phrasings are selected by a separate hash; a paraphrase
does not become another independent sample. Entity requests use public business
IDs to make their intended entity unambiguous. This primary cohort measures NL
composition and execution quality, not intrinsic ambiguous-name resolution.
No name-ambiguity improvement or held-out-template generalization claim is allowed.
Empty and nonempty answers are both retained; emptiness is counted only after the
selection file is sealed. Report both descriptive strata in addition to overall
metrics. Source graph overlap and three shared templates preclude independent-data
or broad family-population claims.

## Independent semantics and outputs

All selected instances get ordinary NL request files; separate reference files
contain exact CSV-derived answers. A third gold-only directory holds the semantic
DAG and canonical unresolved-source SPARQL for deterministic/reference evaluation.
Runtime requests contain no gold program, answers, prepared operator IDs or source
assignment. Every artifact is pinned in a manifest with split and group identity.

F1 uses the full inclusive time window and returns business-ID-sorted company/account
sums. F2 admits1..3 outgoing transfers with strictly increasing timestamps, no repeated
accounts including a closing repeat, and distinct endpoint/distance/blocked-medium
rows. F3 uses a half-open bin, accounts qualified once by any matching risk medium,
parallel transfers counted individually, and top10 descending company sums with
ascending company-ID ties. The independent evaluator traverses original CSV records
and uses Decimal sums; it never executes an XGAP-generated plan for gold.

## Numeric and failure comparison contract

New references explicitly opt into `xgap-row-normalization-v1`: business IDs and
medium type remain exact strings; distances/counts normalize to integral values;
amounts round to3 decimals with ROUND_HALF_UP. Numeric representations may be JSON
numbers or numeric literal strings; booleans/nonfinite values and magnitudes>1e30
are rejected. Original source amounts have2 decimal places, so exact mathematical
sums do not lie at half-millidecimal ties. This equivalence is fixed before new
method outputs, and does not change the runtime query or the baseline algorithm.

Normalization never sorts rows, removes duplicates, changes IDs or substitutes
answers. Wrong order remains wrong ordered EM; wrong multiplicity remains wrong
bag F1. An execution failure or malformed answer remains wrong even against an
empty reference. Invalid reference contracts fail preparation/scoring rather than
silently changing correctness. Legacy references without normalization retain their
original comparison behavior. All formal methods must use the same frozen rule;
external record integration is still a prerequisite for a comparison campaign.

## Execution boundary

Allowed changes: this source-only sampler/CSV evaluator, explicit shared scoring
normalization, tiny new-risk tests, offline input artifacts and evidence. No baseline
algorithm/query-result repair, model call, native service, estimator collection/fit,
old campaign rerun or large-data debugging loop. A120s hard timeout bounds one offline
preparation attempt. Inspect its specific process handle and output root; preserve
partial outputs on failure and do not retry automatically. This user-authorized
preparation follows the approved plan without a new permission step.

Success requires120 frozen groups with the declared24/48/48 split, no excluded or
cross-split group reuse, separate request/gold/reference files, audited hashes and
zero method calls. It does not mark the formal campaign ready. Frozen serving
profiles, uniform runtime/resource watchdogs, common external inputs and source-level
measurement still need completion before the main experiment; ablations remain last.

The five targeted checks in `tests/test_finbench_one_shot_population.py` passed
in0.51s before the actual preparation: independent financial CSV answers and
equal-valued parallel transfers, source-only grouped sampling with old/near-duplicate
exclusions, numeric normalization preserving order/bags, failed or malformed answers
against empty references, and120 controlled output groups with selection sealed
before reference evaluation and gold kept outside requests. No old suite, model or
native gate was repeated. The controlled120-file-group test is not the real cohort.

## Actual preparation accepted; pause gate

Execution at49aaff0 produced120 real-source groups,24/48/48, in5400.266ms with
zero model/backend/fit/method calls. All361 pinned files and split/exclusion
invariants passed the artifact audit. Evaluation references are33 empty/15
nonempty; all40 direct-transfer references are empty. Preserve this outcome and
report empty/nonempty and family strata; do not resample for better results.
See [the milestone report](../report/finbench_one_shot_population_20260912.md).
The user requests a pause after this milestone until2026-09-13 12:00 Asia/Shanghai.
No next-stage engineering or campaign before that time.
