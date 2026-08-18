# GrailQA M13-D Reachability Postmortem

## Scope

This is an evaluation-only diagnosis of the immutable 150-query M13-D run.
It does not change the run, select questions, or expose reference information
to inference. The reusable audit is implemented in
`xgap.experiments.grailqa_reachability`; compact results are frozen under
`datasets/grailqa_m13d_reachability_baseline/`.

## Reproduced Diagnosis

The v1 catalog contains 14,951 FB15k-237 entity names, 13,747 relations, and
10,656 types. Relations and types cover the pilot references at catalog level,
but only 12 of 150 questions have every required entity in the catalog.

| Stage | Entity | Relation | Type | Joint |
|---|---:|---:|---:|---:|
| Catalog availability | 12/150 | 150/150 | 150/150 | 12/150 |
| Retrieval Top-1 | 8/150 | 10/150 | 11/150 | 0/150 |
| Retrieval Top-5 | 9/150 | 24/150 | 41/150 | 0/150 |
| Retrieval Top-10 | 10/150 | 35/150 | 60/150 | 0/150 |
| Retrieval Top-20 | 10/150 | 47/150 | 67/150 | 0/150 |
| Deployed prompt Top-4 | 9/150 | 22/150 | 38/150 | 0/150 |

The catalog loss is therefore dominant for entities. Retrieval and prompt
truncation introduce additional relation/type losses. No question has all
required entity, relation, and type IDs jointly visible to the model.

## Interpretation

The frozen server run reported Candidate Recall 0, Top-1 0 at every epsilon,
and Feasible Coverage 0.48. Because joint prompt-visible reference coverage is
0/150, Candidate Recall cannot isolate model capability: the controlled
grounding contract forbids the model from emitting most reference IDs.

The old `retrieval_miss=0` field measured only whether a nonempty candidate
pool existed before generation. It did not evaluate reference reachability.
M13-E1 separates `reference_not_in_catalog`, `reference_not_retrieved`, and
`reference_not_prompt_visible` after inference, using gold only for diagnosis.

## Artifact Boundary

The local repository does not contain the server's frozen live response rows.
No post-hoc response metric has therefore been fabricated. Copying that run
back enables the separate command documented in the M13-E1 systematic-fix
report; it never overwrites M13-D.

