# T5 batch-interface acceptance — 2026-09-20

The current shared system is now connected to the common batch worker, supervisor,
compressed-answer scorer and resumable ordered driver. This closes the engineering
gap between T4's standalone worker and batch evaluation. Chapter 7 can be designed
in parallel; a paper workload, comparison protocol and scale schedule are not frozen
by this engineering gate.

Implementation source: `412103f6dd673b914bb17272a7521de5ca0d6c27`.
Interface: [T5 contract](../decisions/bounded_joint_batch_v1.md).
T4 algorithm, operator bounds, intent-distance guarantee and historical runs are
unchanged. Historical IDs remain routed to their historical workers.

## Verification

40 unique targeted tests passed across `test_bounded_joint_batch.py`,
`test_bounded_joint.py`, `test_evidence_store.py`, `test_common_method_trial.py`
and `test_fixed_information_dispatch.py`. The two invocations reported 24 and 30
passes with 14 overlapping boundary tests; this is 40, not 54 distinct tests.
These cover current/legacy routing, pinned identities, compressed scoring with
order/multiplicity, corrupted evidence, budgets, preserved primary failure cause,
interrupted/failed/successful intents, source closure and no duplicate execution.
No blanket regression or full dataset run was performed.

Actual native acceptance used the frozen authored eight-node Neo4j+Fuseki stores,
the real common guarded subprocess, source observer, current worker, scorer and
batch driver. The public toy NL grammar supplied proposals; **zero external model
calls**. This does not verify model quality or the new batch path with a live LLM.

|Case|Execution|Final plans|Answer EM|Row multiset F1|User calls|Disclosed coordinates|Backend calls|
|---|---|---:|---:|---:|---:|---:|---:|
|Exact, epsilon 0|Answered|1|1|1|2|3|14|
|Performance, epsilon 0.5|Answered|1|0|0.4|2|1|14|
|Exact, preset zero user budget|Scope budget exhausted|0|0|0|0|not acquired|0|

Exact returned the four independent expected rows. Performance returned one row,
had four consistent intents remaining and satisfied its **structured-intent**
certificate with upper bound 0.5. The scorer correctly distinguished successful
bounded execution from exact answer equality. It does not infer an answer error
bound from epsilon. The non-answer was retained as a failed outcome and was not
mistaken for a correct empty answer.

Each answered case transferred 17,872 response-body bytes and stored 7,878 source
capture bytes. Both purchased one scope confirmation and one clarification;
only disclosure amount differed. This gate does not demonstrate reduced calls,
planner CPU or overall latency. Single-run CPU/latency/RSS measurements are retained
in the per-cell receipts for audit, not promoted to speedup estimates.

## Resume and resources

Invocation 1 sealed Exact. Invocation 2 resumed only the two unattempted cases and
sealed Performance and the preset non-answer. Invocation 3 returned
`no_unattempted_cells`: three sealed, two execution successes, one failure, zero
incomplete and zero pending. No model/backend work or serving startup was repeated.
All owned source groups and observers from the two executing invocations closed;
reconstructable serving copies were discarded and frozen stores preserved.

Batch identity pins the source commit and manifest. Sealed outcomes and scores
retain their SHA identities. Incomplete intents are visible and not retried. Hard
termination without verified closure requires explicit recovery before resume.
Study wall time includes pauses since the first invocation; thresholds remain
declared rather than silently extended to finish remaining cells.

## Evidence and remaining evaluation work

Local gate receipt:
`/Users/anthonyche/xgap-data/bounded-joint-batch-native-20260920-v1/receipt.json`

SHA-256: `ba2a9749f204cd4919e283533cc5d300027ecb318bbefd280e45f7a825664c1b`.
Its pinned manifest, per-cell common outcome/score, source captures and closure
receipts are retained in the same directory. The gate is reproducible with
`scripts/check_bounded_joint_batch_native.py` and an independently pinned native
store preparation; no live services are left running.

Before full evaluation: freeze Chapter 7 questions, datasets, baselines, epsilon
and budgets, order/cache protocol and scoring contract; perform a bounded live-LLM
release preflight. The RDF session adapter is available, but this T5 gate validates
the native deployment only. Large-result JSON still needs RAM and explicit bounds;
the scorer is not an external-memory row engine. This milestone does not establish
full-scale stability, output-semantics guarantees or SOTA superiority. No new SF0.1
evaluation, baseline tuning, historical result rewrite or old job resubmission occurred.
