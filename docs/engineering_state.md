# XGAP current engineering loop

Updated: 2026-09-10. Owner: task 01a085a5-3722-78e2-aab8-c19ef093c36d.

## Workspace and scope

- Authoritative working repository: `/Users/anthonyche/Developer/XGAP`.
- Branch at entry: `codex/m13e4-grailqa-semantic-paper-protocol`; base `a91aed6`.
- The ChatGPT mirror repository is stale; synced `sources/` remain read-only.
- Goal: complete the agentic federated system through measured milestones,
  preserving prior scientific choices and accepted/raw experiment artifacts.
- No subordinate agents requested or spawned in this task.

## User schedule and stopping condition

The user-requested overnight pause ended at **2026-09-10 10:00 +08:00**.
Work resumed at 10:03 and the existing `xgap` heartbeat was restored to ACTIVE
hourly cadence. D198 had completed at commit `65ad96c` before the pause.
Do not treat the old overnight stopping instruction as a current pause.
Local scheduled execution needs this Mac and the Codex app available.

The agent cannot directly push to ChatGPT mobile or verify phone delivery.
Do not claim a phone push occurred. The app's Goal is still active: the goal
tools expose no pause operation, and CUA explicitly prohibits controlling the
Codex app itself. No alternate UI/database workaround is permitted. At the
next explicitly requested pause, the user can click the Goal progress row's pause control.
Do not mark the broad system goal complete or blocked to imitate a pause.
The scheduled morning recovery has occurred; normal authorized work continues.

## Current milestone

D204 is in progress: actual frozen inline18 deployment through the restored
OnDemand portal. The initial read-only Slurm checks showed no running job and
only the known 3796877/3796878/3796968/3796988 terminal jobs. The user then
uploaded the original ZIP and made three observed launch attempts; each stopped
at GitHub HTTPS authentication, before input pinning or sbatch. No new job ID
was obtained. Do not repeat HTTPS authentication, type credentials, or infer a
running job from the extracted package. The final observed shared terminal
returned to a prompt; user activity means read fresh state before any input.

Remote UI is now readable/operable: Chrome browser 1, original user terminal
tab 366873264 (hpc5), file tab 366873233 (/home/hxc859). Re-inventory if stale.
For the terminal, the iframe's `log` role is actionable; its snapshot textbox
does not resolve. Inspect partially typed commands after any UI timeout, and
never press Enter before confirming the complete text. The extension denied
file-chooser setFiles because file-URL permission is absent. Do not bypass or
change that permission; the user was asked whether it is now enabled.

The exact old ZIP was published at transport commit
47cc44f8dc50dd2c8525a0aa76c96f8b03622421. An anonymous server download was NOT
attempted after authentication failures became visible. Instead, an offline
Git bundle package is fully prepared and locally verified:
`/Users/anthonyche/Developer/XGAP-deliverables/xgap-inline18-offline-6b32b97.zip`
(3,261,891 bytes, SHA-256
`5e85c79352c25cb7f056df346fbc0c42d4470eb3058bf0291b36ce16a5340a61`).
It contains a self-contained source bundle at exact 6b32b973…1b07, checked by
an independent real clone, detached checkout and clean-tree verification.
The helper only verifies/clones local bundle bytes instead of HTTPS; all
frozen experiment/model/catalog settings and the one-submission guard remain.
The original package and a conflicting target checkout are never overwritten.

Next: transfer this existing offline ZIP once file upload is available (or the
user manually uploads it), inspect that no prior submission exists, then run
its helper once and observe the resulting job. All failures and any uncertain
submission must be retained; never resubmit. See
`docs/report/grailqa_inline18_remote_execution_20260910.md`. No new production
query/provider code was changed; existing D203 regression is not repeated.
The two pending historical research reports were fully read; inventory now
66 full / 7 selected / 8 pending Markdown documents, plus the three prior PDFs.

## D203 accepted predecessor

D203 controlled software/native acceptance is complete. Broad regression ended
in original session 39813: **2,827 passed / 38 skipped in 643.80s**, exit 0
(`/tmp/xgap-d203-full.log`). Do not repeat passed tests or native queries without
a new change or unresolved concern. Report:
`docs/report/grounded_candidate_execution_v1.md`. The new opt-in preparation
interface reruns typed/canonical grounding against the exact request/view and
compiles supported candidates into actual Neo4j/Fuseki programs. Correlated
URI tuples preserve all path positions; declared functional scalar constraints
are checked on reached resources before filtering. Missing entity bindings,
unsupported constructs, invalid/multivalued scalar data and overflow fail
explicitly. No backend or model call repairs a missing entity automatically.

Actual controlled recording/track/release cases on the retained first shard:
string track number `"1"` gives one release; `"2"` gives empty; no scalar gives
the same release. Type-constrained track queries give one `music.release_track`
and no `book.book`. All five agree with independent full-Fuseki and Arrow
evaluation. An explicit numeric `1` against the string field fails before
literal filtering/baseline. The source, stores, frozen catalog, pending inline18
package and model parameters are unchanged. These are controlled fixtures,
not real LLM predictions or a comparative performance result.

The historical 3796877 source still hashes to f207a5d4…18. All 18 questions and
49 raw candidate outcomes are retained: 38 candidate grounding failures,
7 shared grounding failures, and 4 typed/grounded survivors with no positive
entity equality. Zero candidates are prepared under the explicit anchored goal.
This does not replace old semantic metrics or imply Freebase lacks the answers.
Durable receipts:
`experiments/artifacts/d203_historical_candidate_execution_20260910.json` and
`experiments/artifacts/d203_native_candidate_execution_20260910.json`.

Focused: 268 passed / 1 skipped in 2.61s (45 new offline tests). Harness and
21 examples pass, 22/22 entrypoints. Both owned native runs finished and stopped
normally, no SIGKILL: session 25261 and 9851, roots
`/Users/anthonyche/xgap-data/d203-native-candidates-20260910` and
`/Users/anthonyche/xgap-data/d203-native-types-20260910`. Source/example sessions
79649/76062 finished. No native data reload or catalog construction occurred.
No test/example/native process remains from this milestone.
Next: real generated anchored answers; the original fixed-v1 CWRU inline18
handoff still awaits a user-returned job ID. An optional new anchor feedback
profile is not part of D203 and must not silently alter that pending protocol.

## D202 accepted predecessor

D202 has completed **local software and real Freebase answer acceptance**. See
`docs/report/freebase_native_answer_bridge_v1.md`. The exact Neo4j 5.26.30 and
Fuseki 5.6.0 archives ran on installed Java 21.0.10 in an explicitly local
development environment. No CWRU gate or Java-17 contract changed. The full
D201 first-shard snapshot was loaded once: 3,247,670 occurrences became
3,233,752 distinct Fuseki facts and 541,675 Neo4j resource edges; independent
Arrow grouping confirms both distinct counts (13,918 input duplicates).

The typed query for English names of `type.property` resources returned
**103 identical entity/name pairs** from the actual federated plan, full-Fuseki
baseline and independent Arrow source evaluation. The new opt-in SPARQL IRI
VALUES boundary makes coordinator bindings effective in Fuseki. This is a
typed development query on a partial source, not NL/GrailQA accuracy.
One observation: federated 204.83 ms / two calls versus baseline 16.76 ms /
one call, different timing boundaries and baseline-after-federation cache
order; no speedup claim. Actual output rows encode as 9,044 + 17,924 bytes.

Focused: **241 passed / 2 skipped**; 30 new offline tests plus a live-gated test.
Harness + 19 existing acceptance examples pass. Full regression completed in
original session 43688: **2,782 passed / 38 skipped in 596.81s**, log
`/tmp/xgap-d202-full.log`. Do not restart any of these successful checks.
Native session 37809 completed exit 0, both services stopped without SIGKILL.
Source-query session 90335, distinct-count session 80344 and example session
64526 all completed successfully. No backend or source-build process remains.
Native output/data: `/Users/anthonyche/xgap-data/d202-local-native-20260910-diagnostic2`.
Source answer: `/Users/anthonyche/xgap-data/d202-source-query-20260910.json`.
Archives: `/Users/anthonyche/xgap-data/native-cache` (now present and verified).
The earlier local attempt 68937 failed before service startup because of the
Fuseki help CLI's explicit TerminationException/exit 1; its output is retained.
The corrected help validator passed in diagnostic2; no download/load retry.

Two additional declared book/person queries reused the same databases without
loading data again. Actual resource-match/final-name counts are 7/6 books and
2,234/202 people; all answers equal the full-Fuseki baseline and independent
Arrow source evaluation. The English-name requirement is enforced within this
partial source. Native session 37587 and source-reference session 87038 both
completed; services again shut down normally. No running handle remains.
Outputs: `/Users/anthonyche/xgap-data/d202-domain-queries-20260910`.
Durable receipt/all three answer sets:
`experiments/artifacts/d202_native_freebase_answers_20260910.json`.
Producer source hashes in that receipt remained unchanged through acceptance.
The local D201 commit 61923b6 was also verified at the remote branch head before
D202 began. The document inventory now records 64 full / 7 selected / 10 pending
Markdown reviews; the historical logical-lowering report was fully read while
the regression ran. Do not claim all indexed historical text is fully reviewed.

Next after D202 acceptance: inference-candidate-to-execution lowering and
actual end-to-end model answers. Preserve the existing typed data/mappings,
do not repeat passed exports/loads or substitute catalog/audit work. The
existing fixed-v1 inline18 CWRU package still awaits a returned job ID.

## D201 accepted predecessor

D201 local software and one-shard data acceptance is complete: typed Freebase fact snapshots and executable answer
integration. Scope/acceptance: `docs/report/freebase_typed_fact_snapshot_v1.md`.
The fact reader/exporter, tests and `examples/freebase_typed_fact_demo.py`
preserve all six archival columns and RDF term identity,
consume complete selected shards under finite budgets, and emit reusable
N-Triples parts. Old catalog/source behavior and frozen model inputs are intact.
Focused validation: **203 passed, 1 live skip in 4.47s**, including 52 new tests
and an actual Parquet → exported parts → HTTP loader → RDFLib engine → compiled
numeric-filter query → typed answer integration. The new offline demo passes;
its data is synthetic. Full regression completed in original session 67395:
**2752 passed, 37 skipped in 609.22s**. Harness and all 19 acceptance examples
also pass. Logs: `/tmp/xgap-d201-full.log`, `/tmp/xgap-d201-focused.log`,
`/tmp/xgap-d201-examples.log`. No running test/export/verification handle remains
from D201. Do not restart any of these successful checks without a new reason.
Durable receipt: `experiments/artifacts/d201_typed_fact_snapshot_20260910.json`.

The first frozen archival shard was downloaded once and verified at its original
SHA-256 `f1b21a5869da41938818a3f0f2ef2ead92fd5df978c2d5bf6fbaad31d3f650b1`:
14,984,726 bytes, 3,247,670 rows, five row groups. It was selected as the first
inventory entry before inspecting its contents, without questions/references.
Actual export completed successfully in original session 15621; do not rerun.
Log: `/tmp/xgap-d201-real-shard.log`. It emitted **3,247,670 occurrences,
420,940,219 bytes in 13 parts, in 98.57s**, with 125,272,064 bytes peak process
RSS (macOS observation). Kinds: 541,677 URI objects, 2,603,948 language literals
and 102,045 other typed/string literals. These are one local partial-source
construction observation, not comparative performance or query quality.
Source/output/plan receipts are under
`/private/var/folders/78/2hb19nqj0jv_l0vgmp084ht80000gn/T/xgap-d201-source-b2ymubis`.
The build uses all rows of this one shard, 16,384-row batches, 32 MiB parts and
a 1 GiB output ceiling. This is a partial source-data experiment, not a model,
real-backend answer, complete-Freebase or paper measurement. The source download
and completed demo must not be repeated just because this task continues.
Independent verification v1 completed all 13 parts/counts but failed its final
ordered term digest. The first language-literal diagnosis showed a verifier
representation bug: RDFLib's language literals expose `.datatype=None`, which
the ad-hoc verifier wrongly treated as xsd:string instead of implicit
rdf:langString. Source values, language and exported data agree. The failed
script/log and diagnosis are retained; neither exporter nor source was changed.
Corrected `verify_export_v2.py` completed successfully in session 35115; log
`/tmp/xgap-d201-independent-source-v2.log` and `independent_verification_v2.json`
were inspected. All 3,247,670 ordered terms agree at digest
`96aca67e31c1254387580000abfd21ef5dd163b84553f3eb6e04dfe9c4c66c78`.
Actual literals include 1,681 xsd:date, 6,089 xsd:gYear and 2,760 xsd:gYearMonth
values, plus 91,515 strings and 2,603,948 language literals. Verification took
57.79s alongside the full regression; no model/backend was called. Do not
rerun either the export or successful independent verification.

At D201 completion the next gate was: connect typed fact data to actual backend loading, dataset-owned term
mapping, generated query execution and cross-backend answers. Date/gYear/
gYearMonth terms are preserved but require their own comparison semantics;
the successful compiled query test uses integer years. Do not promote that
fixture into a claim of date-aware real Freebase answers. The inline18 CWRU
package still has no returned job ID, and no remote submission was attempted.
The D201 Java inventory showed Temurin 25 and Homebrew OpenJDK/21, but no known
Java 17 installation. The accepted native lock requires Java 17, Neo4j 5.26.30
and Fuseki 5.6.0. Read the actual lock and locate/retrieve exact local runtimes
before trying a separate local service experiment; never fabricate a Slurm
allocation or label a local run as CWRU. No service was started in D201.

D200 local software acceptance is complete: read-only reconstruction of the
guarded inline development run, including source/context, provider, semantic,
token/lifecycle and evaluation layers. See
`docs/report/grailqa_guarded_whole_run_evidence_v1.md`. D199 fixes v1 as the
control catalog; no actual new model run has been measured or admitted.

The implementation reconstructs complete actual offline-runner fixtures and
passes **184 focused tests in 17.39s**. Full regression completed in its
original exec session 59949: **2700 passed, 37 skipped in 625.92s**. Do not
restart it. The harness and all 19 acceptance examples pass. Receipt:
`experiments/artifacts/d200_guarded_whole_evidence_local_20260910.json`.
The narrow environment fix accepts numeric JSON 0/1 versus the bundle's
normalized floats while rejecting booleans; frozen specs are intact.
Accepted producer **6b32b973d4fd1a979b714570d3edcd2e684c1b07** is committed
and successfully pushed to the existing remote branch. The working tree was
clean after the commit. No source changed after the successful full suite.

The exact-commit remote operator package and one-step instructions are in
`docs/report/grailqa_inline18_cwru_handoff_20260910.md`. The local ZIP is ready,
but has not been uploaded or executed. It fixes v1, preserves prelaunch catalog
and tokenizer pins, submits once to an isolated checkout, then supports a
separate post-completion D200 reconstruction. Server-side upload/start has been
requested because both browser control and the one SSH route are unavailable.

User steering (September 10): explain XGAP versus graph-guided RAG, identify
which pipeline stage the catalog serves, and stop treating catalog work as the
whole system. After D200 acceptance, prioritize the fixed-v1 real inline18
experiment and actual federated answers. Metadata-index reuse and entity
coverage diagnosis remain separate, bounded work; do not repeat the same scan.

During the full suite, dedicated OnDemand shell tabs 366873210 (hpc5) and
366873213 (hpc7) appeared, but browser control timed out before any server
command was sent. No job was submitted or remote file written. CUA resets can
renumber browsers: most recent inventory was Chrome browser 1 and in-app
browser 2, not their earlier IDs. The new terminal tabs lack providerTabId in
the latest inventory; do not assume they are controllable. The user-owned
366872568 terminal still has a providerTabId and hpc8 title, but avoid typing
into it while the user is active. The earlier file-editor route remains a
separate read-only fallback. Native foreground typing remains unsuitable.
The subsequent read of existing file tab 366873192 also timed out before
returning any page content. This is a browser-control failure, not evidence of
expired authentication. No new remote action has been attempted. Prepare the
exact-commit runnable handoff and continue independent answer-execution work;
do not keep creating tabs or repeat unchanged catalog/audit work.
The alternate provider-ID lookup returned tab-not-found. A single strict,
noninteractive SSH connection to Pioneer port 22 timed out before any remote
command ran. No authentication setting was changed or credential requested.

Concrete next answer-chain gap: `freebase_sources.parquet_row_to_triple`
intentionally drops plain/datatype-bearing literals for catalog compatibility.
It cannot serve unchanged as the fact reader for dates/numeric filters. Build
the target-data path with full RDF term identity and independent answer checks;
do not change the old catalog parser, derive facts from gold, or substitute
another catalog/audit cycle. The D200 and handoff turn is progress: full
acceptance completed, source committed/pushed, exact runnable package prepared,
and the remaining remote-control and typed-fact gaps were directly observed.

D199 / H1 catalog comparison observation is complete. Job **3796988** finished
successfully; the actual report has **zero coverage gains and zero losses** in
all 15 stage/component cells. Both catalogs retain joint availability 10/18,
Top-20 joint retrieval 6/18, and deployed-prompt joint reachability 5/18.
All 18 entity ID lists, including order, are identical at all three stages.
Launch/log/status/report identities agree; all 15 counts were reconstructed
from the report's per-query rows. This is a real development observation,
not a fresh whole-run/source audit. The full report was read in the browser
session; only a compact derived receipt is durable locally. See
`docs/report/grailqa_catalog_comparison_3796988.md` and its linked receipt.
No executable source changed or full regression was repeated in this observation.

D198 adds read-only admission of the complete retained inline provider history:
all materializations, typed/grounded feedback, exact repair payloads, token
receipt and transport order, raw/consumed responses, invocation copies and
query state seals. This is a provider evidence component, **not whole-run
admission**, semantic accuracy, recomputed token counts, or server identity.
See `docs/report/grailqa_inline_evidence_v1.md`.
Focused regression: **215 passed in 3.13 seconds** (41 new tests).
Harness + all 19 acceptance examples pass. Full offline regression: **2587
passed, 37 skipped in 596.33 seconds**. D198 local software acceptance is complete.
Evidence: `experiments/artifacts/d198_inline_evidence_local_20260909.json`;
full log: `/tmp/xgap-inline-evidence-20260909/full-regression.log`.
The final handoff is `docs/report/xgap_implementation_report_20260909_evening.md`.
The scheduled recovery has now occurred.

D197 / H3 software acceptance is complete: inline slot annotations are
materialized into the existing guarded semantic pipeline, with original/derived
response evidence and deterministic replay. See
`docs/report/grailqa_inline_grounding_v1.md` and
`experiments/artifacts/d197_inline_grounding_local_20260909.json`.
Focused regression: **297 passed in 2.28 seconds**. Final full regression:
**2546 passed, 37 skipped in 608.62 seconds**. The harness check and all 19
acceptance examples pass. Actual Qwen schema acceptance, token fit and semantic
effectiveness remain unmeasured; H3's empirical comparison is still open.

The first full attempt was 2545 passed / 1 failed / 37 skipped. A historical
review test compared its frozen provider hash to later source. The test now
reads the original source from that review's declared commit, preserving every
old artifact/hash. The full suite was rerun after this test-only correction.
Do not repeat successful acceptance without a new code change or concern.

Prior completed milestone, commit `13dd4ba`: D196 / H2 preserves RDF term and resource identity through explicitly selected
native compilation, HTTP execution, runtime fragment wiring, and answer projection.
Implementation and 153 focused tests pass (one live gate skipped).
Full regression: **2503 passed, 37 skipped in 604.92 seconds**.
The harness check and all 19 acceptance examples also pass.
The new live Fuseki test is explicitly gated and not yet measured.

Current full regression log: `/tmp/xgap-inline-evidence-20260909/full-regression.log`.
Python with pytest 9.0.2 / RDFLib 7.1.4:
`/tmp/xgap-directed-tests.qU2YfW/venv/bin/python`.

## Remote state

OnDemand is open in Chrome at
`https://ondemand-pioneer.case.edu/pun/sys/shell/ssh/pioneer.case.edu`.
The user returned a fresh scheduler record for **3796988: COMPLETED, 0:0,
03:56:26**, start `2026-09-09T04:35:55`, end `2026-09-09T08:32:21` in the
scheduler's unverified time zone. This record was also read in the terminal.
Its log is
`/home/hxc859/XGAP-m15-465e2e2/slurm-xgap-grailqa-catalog-compare-3796988.out`;
the final five-line log was read through the portal editor and reports CLI
success with the same comparison hash as the status and report.
The job belongs to the previous e39b98e CPU catalog comparison and is terminal.
Keep its outputs intact. No new remote job has been submitted by this task.
There is no local SSH config. Native browser input can be delayed and drops
some special characters; do not send compound or state-changing commands
through that route until exact input is verified. Read-only attempts produced
two harmless `scontrol` syntax errors, not a change to the running job.

The restored login now works through a fresh extension-backed file tab. Raw
file links return Chrome `ERR_BLOCKED_BY_CLIENT`; the portal's ordinary Edit
view exposes file contents. Read/select/copy only, never Save. Its Save button
remained disabled after copying. Use a separate task tab, because the user may
navigate the shared tab during other work. Native foreground terminal input
remains unverified; do not type into a user-changing window or infer execution.
Do not treat retained screen text as a newly executed scheduler observation.

## Next actions

1. Continue the document reading inventory; long historical material is
   indexed but not all paragraphs have been reviewed. All three known source
   PDFs have now been read in full, with selected figures/formulas checked;
   proof verification and experiment reproduction are separate. Markdown
   progress is 63 full / 7 selected sections / 11 detailed reviews pending.
2. Preserve the 3796988 negative comparison. Do not repeat this rebuild or a
   GPU comparison of unchanged candidate sets. For inline-interface development,
   keep the old v1 catalog fixed; diagnose entity mention/alias/selection-rank
   exclusions separately from retrieval/prompt truncation, without gold-fed data.
3. Extend D198's provider evidence component to independent whole-run admission
   for the new materialized-response contract: producer/spec/population,
   catalog/retrieval, environment/lifecycle, tokenizer parity, metrics and gold
   isolation still need their complete evidence chain. Keep the new inline bundle/spec separate.
   Establish vLLM schema compatibility and actual request fit with the existing
   bounded probes while holding the v1 catalog fixed. No running job was found
   for this completed comparison; retain exact producer checkouts and use the
   existing staging/run authority before any new bounded experiment.
4. Prepare a real two-engine answer admission over inference-owned data.
   Current typed-row results are not full GrailQA execution or accuracy.

## Continuation

Existing automation `xgap` was updated, not duplicated, and has returned to
hourly bounded cycles. Stay quiet without meaningful change. The broad goal
remains in progress; the overnight pause is complete.

## Persistent rules

Never use gold to construct retrieval/deployment data. Keep all evaluation
denominators and failed records. Do not rerun the accepted FinBench campaign,
change its population, or claim independent instance-memory gains from the
recorded fixed-route tie. External failures are observations without silent
retry. Ask the user only for unavailable credentials/network/server action,
external artifacts, or a material scientific decision; routine authorized
implementation and testing continue autonomously.
