# GrailQA 3795067: audited negative development result

## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: validate
- Origin Date: 2026-09-08
- Verification Status: ANALYZED
- Version Label: preflight_3795067_validation_v1
- Source: operator-pasted CWRU audit JSON; raw request/response bodies are not
  locally available for this assessment. No model experiment was rerun.

## Validation Report

The independent preflight audit establishes artifact consistency, not semantic
effectiveness. Producer job `3795067` used commit
`49941203612fae841340c2c651bd93d0ecc8b619`. Auditor job `3795103` used
`b421a426852fce77eef86676f38b5783102e88a5` and returned audit hash
`233cdd368580174a39337c90d7be9ee3c542cb57699f50475d3cdb0dbb38bbe6`.
All 101 checks passed, with no reported source-tree mutation.

| Observed quantity | Value | Meaning |
|---|---:|---|
| Questions | 18 | Development preflight, not the 150-query paper run |
| Schema-valid provider envelopes | 17/18 | Not equivalent to grounded/valid interpretations |
| Logged provider requests | 19 | Includes the bounded repair attempt |
| Candidate-bearing questions | 0/18 | No rows reached the validated-candidate artifact |
| Candidate recall | 0/18 | All queries retained, including the provider failure |
| Jointly prompt-reachable subset | 5/18 | Its candidate-bearing count and recall are also zero |
| Graph backend executions | 0 | This is a semantic-only preflight |

No p-value, confidence interval, effect-size comparison, or population-wide
accuracy claim is supplied or inferred. Semantic-score means and normalized
interpretation accuracy are unavailable, not zero-valued measurements, because
there are no candidate rows. `paper_result=false` and
`full_150_run_authorized=false` remain explicit.

## Diagnostic limitations

The frozen first-failure taxonomy reports 8 queries whose reference is absent
from the local catalog, 4 whose reference was not retrieved, 1 whose reference
was not prompt-visible, and 5 labeled `generated_semantic_miss`. Those counts
describe its classification, not a proven causal decomposition of the failure.

Source inspection establishes an observability gap: `_infer_one` returns no
candidate rows after a `RuntimeAlignmentError` in grounding; the preflight
classifier then tests for zero candidate rows before the grounding-failure
flag. It can label this rejection `generated_semantic_miss`. The final failure
file also omits the original exception message. Thus zero validated candidates
does not prove the model generated no candidates: the successful audit checks
1–3 raw candidates in each of the 17 schema-valid provider responses.

The exact grounding guard that fired on the live responses is **not yet known**.
Read-only replay can reconstruct the exact prompt view from the recorded user
payload and check its hash against the response, then repeat normalization and
grounding locally. It needs neither catalog nor gold, and performs no LLM,
backend, or ontology-service calls. Replay diagnostics must remain separate
from the frozen result; they do not replace its metrics or establish a repaired
live outcome. No scientific parameter is selected from these observations.

## Fallacy Scan

Coverage: 11/11 categories checked for applicability; this is a descriptive
engineering result, not a hypothesis test.

| Category | Assessment |
|---|---|
| Simpson's paradox | No reversal is present in reported overall/subset zero recalls; no broader subgroup claim |
| Ecological fallacy | No inference beyond the 18 query units |
| Berkson's paradox | The 5 reachable queries are a selected diagnostic subset, not a replacement primary population |
| Collider bias | No adjusted causal estimate; conditioning on reachability is descriptive only |
| Base-rate neglect | Denominators 18 and 5 are explicit; provider schema validity is not candidate validity |
| Regression to the mean | No before/after improvement claim or rerun selection |
| Survivorship bias | Provider failure and all 13 unreachable queries remain in the all-query result |
| Look-elsewhere effect | No selected significance test or favorable epsilon is reported |
| Garden of forking paths | Do not tune scientific choices on this preflight; preserve versioned negative evidence |
| Correlation versus causation | Exact rejection cause remains pending raw-artifact replay |
| Reverse causality | No directional causal estimate is made |

## Reproducibility

- Method: source inspection and analysis of the returned audit; no experiment rerun.
- Verdict: CANNOT_VERIFY a live reproduction locally. The reported successful
  remote audit remains scoped to its declared artifact-integrity checks.
- Engineering disposition: inspect existing request/response records before
  advancing the production runbook; no automatic retry or 150-query launch.
