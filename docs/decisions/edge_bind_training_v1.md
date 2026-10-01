# Independent tiny coverage for edge bind, 2026-09-12

RQ: can the frozen estimator represent the new executable endpoint-bind work
without using observations from the incoming financial query? X is bound endpoint
(source/target), target engine (Neo4j/Fuseki) and one/two driving keys. Y is native
answer preservation and estimate availability, not ranking improvement or speedup.

Allowed: four independent training programs/fixture, verified import of the old
28 measurements, per-sample frozen statistics in offline fitting, native collector,
focused tests, and current evidence documents. No baseline, large-data, LLM or
old-query reruns. No FinBench test observations become labels, no parameter search,
no repeated measurement, no automatic retry. Keep original model and inputs intact.

Use a new namespace with four Vertex nodes and six LINK edges, including two
identical-valued parallel edges. Fix four endpoint-bind programs before service
startup: Neo4j-source, Fuseki-target, Neo4j-target, Fuseki-source. Each executes
one specified training plan (two remote fragments), not all physical alternatives.
One-key source binding and two-key target binding have independent expected edge
IDs. Stop on failure; store the actual response before checking correctness.

Reuse the 28 pinned training observations and their original plans/statistics,
verifying parent-model, collection, manifest, measurement and reconstructed sample
hashes. New records carry the new fixture statistics. Fit the existing bounded
128-sweep nonnegative model once to these 32 records, without changing its feature
dimensions, objective, hyperparameters or serving algorithm. A per-sample statistics
map must exactly cover the samples and share feature names; wrong snapshots fail.
Preserve each statistics artifact and its assignment in training provenance. The
model's primary statistics remain its default serving contract, not a claim that
all training samples came from that snapshot. Deployment to FinBench is still an
explicit uncalibrated transfer. All preparation/collection/fit is offline; new and
reused acquisition costs are shown separately. Work remains O(SNd) for fixed sweeps
S<=256 and samples N<=256 plus polynomial feature extraction and validation.

Acceptance: new snapshot import/fit guards and the four native training outcomes;
one saved new-model artifact with all four endpoint-bind categories recognized.
After freezing, check only estimate availability on the already saved financial
plans, without reading their timing/answer records or rerunning them. Do not select
a favorable fit based on that check. FinBench gold programs, prior exposed queries
and SPLIT-NL-01 remain excluded from the new training population. Genuine held-out
ranking and latency quality are subsequent paper evaluation, not this gate.

Next: frozen financial NL input/catalog/profile and one unaided NL-to-answer run.
The ordinary deterministic financial 3/3 native result stays accepted and is not
rerun merely because the estimator changed.
