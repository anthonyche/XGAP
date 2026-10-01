# GrailQA 3795067: audited negative development result

## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: validate
- Origin Date: 2026-09-08
- Verification Status: ANALYZED
- Version Label: preflight_3795067_validation_v2
- Source: operator-pasted CWRU audit and replay JSON, followed by the uploaded
  request/response ledgers. Both uploaded file hashes exactly match the audited
  artifacts. No model experiment was rerun.

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

## Hash-matched raw-envelope diagnosis

The operator ran the read-only replay on CWRU with unchanged parser/grounding
imports, then supplied both ledgers. Local hashes exactly match the earlier
independent audit:

- requests: `6060078b189fa11a0fbf3840960f372b61d4306e004855c52093a3cf278363d0`
- responses: `557d5b250d299cd7fff3d7ffe4f13537a00f4e3bd3843b41c6731c110a3c12ce`

Local reconstruction reproduces all 18 first-rejection outcomes without
opening gold, loading a catalog, or making an external call. The 17 retained
schema-valid responses contain **47 raw candidates**, not empty arrays.

| First rejection | Queries | Raw-record observation |
|---|---:|---|
| Incomplete top-level query anchors | 16 | 13 omit `relation-hop-2` and `relation-hop-3`; 3 omit only `relation-hop-3` |
| Invalid component reference | 1 | Query `3205285001000` uses `n2` (a target variable name) where a structural path is required |
| Provider parsing/repair failure | 1 | Query `3206065001000` omits `selector` and `restrictor` in both identical response bodies |

All omitted slots in the 16 responses are marked `required_for_candidate=false`
in the prompt view. The two required slots are present, and the returned
anchors have no duplicate/unknown slots or out-of-set IDs. However, the
grounder requires **every** top-level slot to have an anchor; the optional flag
only applies to each candidate's realizations. The frozen prompt already says
to choose an anchor for every supplied slot, so the responses violate an
existing requirement. What it does not explain explicitly is the two levels
and the restricted meaning of `required_for_candidate`; the static schema
does not encode exact slot coverage. This is a possible source of confusion,
not proof of why the model produced the omissions. One candidate (`2101661019000/c2`)
even realizes `relation-hop-2` while its top-level anchor is missing. Therefore
simply treating every omitted slot as unused is not a valid repair.

A separate structural-path inventory, without bypassing any validator, finds
55 invalid `component_ref` occurrences across 26 of the 47 retained candidates
and 10 queries. These overlap the first-rejection counts: most are hidden by
the earlier top-level anchor guard. Variable names and paths such as
`expr.edge.label` are not the required structural component path `expr.edge`.
Filling missing anchors alone would not establish candidate validity.

The provider failure also exposes a confirmed implementation mismatch. The
frozen prompt permits omitted defaults, but the provider invokes the legacy
parser before the runner's existing normalization. Both raw response bodies
contain three candidates, all omitting both fields; legacy parsing produces
`selector must be a mapping`, whereas the existing normalized parser accepts
both bodies. **This does not recover a valid interpretation:** the unchanged
grounder then rejects `boats.ship`, which is not an allowed anchor for the
retrieved-type slot. There is no measured accuracy improvement to report.

The compact source-bound diagnosis is retained in
`experiments/artifacts/grailqa_preflight_3795067_contract_diagnosis_20260908.json`.
The raw ledgers are not copied into version control. These observations remain
separate from frozen metrics and do not authorize a new live run or select
scientific parameters.

## Engineering correction and acceptance boundary

The provider now supports explicit parser injection, with the legacy parser
remaining its default. Only the already-normalized GrailQA preflight and paper
entrypoints select the existing normalization before provider validation and
the unchanged bounded repair loop. Raw responses remain unmodified. Malformed
semantics, grounding, anchor coverage, and the repair limit are not weakened.
The frozen prompt, structured schema, model bundle, and scientific choices
are unchanged. Prompt clarification or a different grounding-repair policy
requires a separately versioned contract and explicit review before execution.

The old paper draft correctly rejects the changed runner's implementation
hash. Its v1 protocol and readiness artifacts are preserved byte-for-byte.
The separately numbered **draft v2** changes only the protocol ID, runner
implementation hash, and derived freeze/readiness hashes; all science, model,
source, and unselected author fields are identical. Defaults now refer to v2,
but no old receipt transfers to it, and all authorization gates remain false.
This implementation-binding revision is not a prompt-contract revision.

The identified logging gap is repaired for future preflight invocations by
preserving the original inference failure as an optional nested diagnostic on
the existing failure row. This does not alter the frozen top-level taxonomy,
metrics, or candidate handling. It does not retrofit fields into job
`3795067`; its original errors were instead recovered by replay. The current independent
auditor checks the containing artifact identity but does not reconstruct the
nested diagnostic's causal content.

### Offline acceptance (2026-09-08)

`python -m pytest -q` passes **1,301 tests with 36 skipped** in 503.96 seconds.
The revision adds 26 cases for additive diagnostic retention, explicit parser
wiring and the unchanged legacy behavior/repair bound, preservation of v1
artifacts, v2-only implementation rebinding, rejection of old approval records,
and executed shell defaults. Both `examples/llm_boundary_demo.py` and
`examples/m15_goal_loop_demo.py` also pass with `PYTHONPATH=src`; these are
offline fixtures, not live backend measurements. Independent code review found
no relaxation of the downstream grounding or semantic guards.

The two uploaded ledger hashes remain unchanged after replay. These tests
accept the engineering correction only; they do not replace the recorded
zero-candidate outcome or establish new semantic accuracy.

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
| Correlation versus causation | First deterministic rejection is reproduced; fixing it is not proof of a valid candidate or improved accuracy |
| Reverse causality | No directional causal estimate is made |

## Reproducibility

- Method: source inspection, hash-checked raw-ledger parsing, and exact offline
  reconstruction of the 18 first-rejection outcomes; no model experiment rerun.
- Verdict: REPRODUCIBLE for deterministic first-rejection diagnostics only.
  CANNOT_VERIFY a new live outcome. The reported successful remote audit remains
  scoped to its declared artifact-integrity checks; this report stays ANALYZED
  for overall experimental effectiveness.
- Engineering disposition: correct implementation-order drift, preserve the
  negative run, and review a separate interface-contract clarification before
  any new inference. No automatic retry or 150-query launch.
