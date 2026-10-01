# GrailQA eligibility-before-Top-K catalog repair

## Scope and evidence

This is an offline engineering repair of the query-local entity selector, not
a new semantic experiment or an admission of a new catalog to a paper run.
The source dump, question set, ontology, model, prompt, grounder, lexical score,
and the existing Top-50 / retrieval Top-20 / prompt Top-4 defaults are unchanged.
The original 18-query negative evidence and all FinBench results are preserved.

The legacy builder first takes lexical Top-K and then drops entities without
English canonical names during enrichment. An alias-only entity can therefore
displace a lower-scoring materializable entity, leaving fewer than K results
even when eligible alternatives exist. An independent exhaustive synthetic
reference reproduces this defect and tests the replacement algorithm. This
does **not** establish that it caused the eight real local-catalog misses in
job 3795067. Those still require an explicitly versioned source-backed coverage
comparison; the other retrieval, visibility and output-contract failures remain.

## Implemented behavior

`grailqa_eligible_candidates.select_eligible_query_candidates` spools English
canonical MID eligibility and each question/MID's best lexical match to a
private SQLite file. It completes the name/alias scan before joining against
eligible MIDs and applying per-question Top-K. A late canonical record, an
earlier batch flush or more than 2K ineligible matches cannot prevent backfill.
Deduplication is by MID within each query, not by alias row or across queries.

Eligibility matches the final materializer's existing SQLite integrity rule:
an English literal NAME must have a value for which `trim(canonical_name)` is
nonempty. SQLite's default trim removes ordinary U+0020 spaces only. This repair
does not invent a stricter Unicode-whitespace rule or rewrite the name. Empty
canonical records do not establish eligibility or override another valid name
for the same MID during the second metadata pass. If a selected MID loses its
usable canonical metadata between passes, the build fails explicitly instead
of silently shrinking the selected set.

Ranking retains the existing normalized contiguous spans, stopword option and
lexical score, followed by MID, matched label and source shard. Only an otherwise
identical name/alias tie now deterministically prefers the name. Diagnostic
`legacy_topk_dropped_count` and `backfilled_count` describe lexical-Top-K-then-
filter with this deterministic tie rule; they are not a byte replay of every
historical source-order-dependent tie.

The selector limits pending writes to 4,096 rows and configures a 16 MiB SQLite
page cache, file-backed temporary storage and no database mmap. These are **not**
a whole-process memory limit or a disk quota. The spool and ranking index grow
with the source and matches. Full-source time, peak memory and disk consumption
have not been measured. Source/SQLite errors propagate; only owned scratch is
cleaned, and no partial selection or automatic retry is returned.

## Independent version and publication

The existing builder defaults to `legacy_topk_v1`. The new choice is explicit:

```text
python -m xgap.experiments.grailqa_local_catalog build
  --candidate-selection canonical_eligible_topk_v2
  --local-root <explicit-fresh-development-parent>
  --parquet-root <existing-frozen-parquet-source>
  --source-manifest <existing-frozen-source-manifest>
  --workload preflight18
  --staging-root <existing-node-local-scratch-parent>
```

This is an interface illustration, not a submitted or authorized CWRU command.
The existing frozen config supplies question and ontology paths. The CLI adds
`-eligible-v2` to the workload output directory and artifact ID, refuses
`--force`, and refuses `run`, `audit` and `compare` before loading their inputs.
The raw local-root path and ancestors are checked before resolving symlinks.
The Python build API also requires a fresh output. Neither entrypoint changes
old launcher defaults or installs missing artifacts.

The local manifest version is `m13e3b-grailqa-local-catalog-v2`. Its identity
includes the selection policy, anchor contract and deterministic content-file
hashes. `selection_diagnostics.json` records per-query matched, eligible,
dropped, selected, truncated and backfilled counts with `gold_inputs=false`.
Timing and resource measurements are kept separately in manifest construction
metadata so source ordering and runtime noise do not change semantic identity.

Publication validates an output-adjacent private copy, exclusively claims a
new destination directory, and links data files before the completion manifest.
It never removes an existing destination or an unrelated publishing directory.
If publication fails halfway, partial output is retained without a completion
manifest and a subsequent build refuses to overwrite it. This is manifest-last
publication, not an atomic whole-tree rename or a power-loss durability claim.

The v2 validator reconciles hashes, query identities, persisted selections,
diagnostic arithmetic and runtime database contents with exported evidence.
This is local consistency, **not** proof of completeness against the entire
source corpus, semantic accuracy or historical experiment admission. The
generic query-conditioned runtime can retrieve the new persisted candidates;
historical reachability and paper audits remain bound to their old versions.
New artifacts retain `paper_result=false`.

## Acceptance and remaining work

Offline acceptance includes independent exhaustive selection checks, source-
order/batch invariance, cross-query isolation, empty-name behavior, end-to-end
materialization and actual query-conditioned retrieval, legacy compatibility,
invalid-input and symlink refusal, tampered evidence rejection, and interrupted
publication without overwriting evidence. The focused command currently passes
**177 tests**:

```bash
python -m pytest tests/test_grailqa_eligible_candidates.py tests/test_grailqa_eligible_catalog_build.py tests/test_m13e3b_local_catalog.py tests/test_m13e3b5_local_preflight_wiring.py tests/test_grailqa_artifact_audit.py -q
```

The independent selector cases number 83; the remaining cases include new
builder checks and old wiring/audit regression. The end-to-end source iterator
and full-source inventory verification are fixture doubles: source I/O is not
an actual 964-shard scan. SQL materialization, validation, publication and
query-conditioned runtime retrieval are real local operations. One test
demonstrates legacy zero retained candidates versus one usable v2 backfill on
the same input. Separate read-only review found no remaining blocking
integration issue; it does not replace real source/model measurements.

`examples/llm_boundary_demo.py`, `examples/m15_goal_loop_demo.py`, CLI help and
`git diff --check` also pass. Full repository regression (`python -m pytest -q`)
passes **2,005 tests with 36 skipped in 550.18 seconds**. Skipped behavior remains
unverified; only documentation changed after full-suite collection.

Next, separately measure full-source construction resources and compare the
same inference-only questions under v1/v2 before any downstream model result
is attributed to this intervention. References may be opened only for the
subsequent evaluation, never used to add construction anchors or choose MIDs.
Public schema-label/alias enrichment and retrieval/packing interventions remain
separate. Full-150 execution is not authorized by this change.

The full XGAP goal remains the original EQ1–EQ5 on both retained primary
datasets: FinBench semantic comparisons and GrailQA executable physical
alternatives, answer evaluation and baseline comparisons are still incomplete.
This catalog repair advances one necessary input path; it does not replace
those obligations with another passing software audit.
