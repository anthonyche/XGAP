# GrailQA catalog comparison: no coverage change

Observed on 2026-09-10 through the authenticated CWRU OnDemand file UI,
following the user's returned scheduler record. This is a real development
comparison with a bounded row-level reconstruction, not a new independent
whole-run admission or a model/answer experiment.

Job `3796988` completed with exit `0:0` in `03:56:26`. Its launch record and
Slurm log bind producer `e39b98e109870f8910c1f2ec98348965bd272f30` and the
original 18 question IDs/order. The log, `run_status.json`, and comparison
report all identify success and comparison hash
`ec08d1ace864bfc07acd28866f251fa3b01bc414764a8f577b19c0c571822cf0`.
The complete six-file comparison directory listed no failure marker.

The 549,604-character comparison JSON was copied from the portal editor and
parsed without editing or saving. Its 18 rows per variant reproduce all 15
reported coverage cells. Entity ID lists are identical, including order, for
every query at catalog, retrieval, and deployed-prompt stages. The launch
question order and source identity also match the comparison report.

| Stage (18-query denominator) | Entity | Relation | Explicit type | Effective type | Joint |
|---|---:|---:|---:|---:|---:|
| Catalog, both versions | 10 | 18 | 18 | 18 | 10 |
| Retrieval Top-20, both versions | 8 | 13 | 13 | 15 | 6 |
| Deployed prompt Top-4, both versions | 7 | 10 | 4 | 12 | 5 |

Every cell has zero gains and zero losses. The same eight questions fail at
catalog availability, four at retrieval, one at prompt visibility, and five
remain jointly reachable. Effective type includes the existing role-aware
relation-endpoint evidence; it is distinct from explicit type retrieval.

Both catalogs contain 865 unique entities, 900 query-candidate assignments,
978 aliases, 3,099 entity-type records and a 14,413,824-byte database. The
catalog hashes differ because their version/construction metadata differ;
different artifact identity does not imply different candidate content.

## Engineering consequence

The eligibility-before-Top-K repair is exercised, but it does not explain or
recover the eight missing entities in this development population. Do not
perform another full-source rebuild with the same intervention, promote v2 as
a measured quality improvement, or spend a GPU run merely to compare these
unchanged candidate lists. This observation preserves the earlier warning
that the real v1 catalog already filled all 18 × 50 candidate assignments.

Keep the preserved v1 catalog fixed for the separately versioned inline-output
development comparison, subject to its complete preflight and evidence gates.
This is a controlled engineering comparison choice, not a new population or
paper authorization. A later catalog change must be measured separately.

The next catalog diagnosis should distinguish unavailable names/aliases,
mention-span extraction, selection rank and retrieval/prompt truncation using
inference-side data and question text. Evaluation-derived missing MIDs must
never be inserted into the inference catalog or used to select execution facts.
The existing 5 reachable questions are diagnostic only; all 18 remain in the
primary development denominator.

The builder recorded 13,773.23 seconds and 516,825,088 bytes peak RSS, versus
2,703.37 seconds and 335,290,368 bytes in the historical v1 construction.
These are separate original construction observations, not a paired speed or
memory experiment, nor scheduler-wide resource accounting. They motivate
inspecting build cost before another 964-shard scan without establishing its
cause. Catalog metadata still contains no executable fact-edge snapshot.

## Evidence and limits

The compact [observation receipt](../../experiments/artifacts/grailqa_catalog_comparison_3796988_observation_20260910.json)
retains the reported identities, per-query coverage flags, reconstructed
counts, unchanged-entity observations, and explicit verification limits.
The full comparison text was read in the browser session but has not been
exported as a complete local source file. Reported source hashes were not
independently recomputed, retrieval was not replayed from its ledger, and
Freebase was not rescanned by this observation. Do not call this a complete
source audit or use the receipt as live/model/paper execution authority.

No new remote job, model call, backend query or retry was made. Browser work
used a separate task tab after the shared user tab changed. Raw-view links
returned `ERR_BLOCKED_BY_CLIENT`; the portal's normal text editor exposed the
content with Save disabled. No browser restriction was disabled and no remote
file was saved. This is the working read-only observation route; native
foreground typing remains unsuitable while the user uses that window.

Acceptance for this observation is scheduler/CLI/status identity agreement,
the row-level recomputation above, and durable preservation of the negative
result. No executable source changed, so the already successful full offline
regression was not rerun.
