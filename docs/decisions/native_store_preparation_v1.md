# Native serving preparation v1 — 2026-09-13

Scope: finish the missing full FinBench Neo4j/control-Fuseki preparation boundary
for the approved native-versus-same-facts-RDF evaluation. This is offline work,
not a new research direction, optimizer, or baseline modification.

RQ: what effectiveness and online cost does the one-shot method obtain across
the declared native/RDF deployment representations? The deployment is the
factor; answer quality and complete online latency are the later measured
outcomes. Correct, frozen serving inputs are a prerequisite, not an experimental
gain by themselves.

The native input profile, generated Cypher batches and original control Turtle
are already frozen. Execute each nonempty batch and existing constraint exactly
once, in source order. Preserve all failures; no restart/resume of partial loads.
Do not rewrite statements, change batch sizes, add indexes, rebuild catalogs,
retrain estimators or consult workload questions/answers. Two fixed count reads
check input row totals against Neo4j nodes/relationships; they are offline
integrity operations, not per-query probes. Counts do not prove every property.

One private worker group owns Neo4j, with 900s wall and sampled 3GiB RSS;
heap 1GiB/page cache 256MiB. TDB2 uses the already pinned Fuseki jar's default
phased loader, 2GiB heap, the same wall/RSS limit, one invocation. Output cap
10GiB and free-space reserve 6GiB are sampled. Resource overshoot between samples
is possible. Graceful shutdown and an empty owned group precede store sealing.
Persist complete batch outcomes and process records. Native engine files and
source checksums must remain unchanged. Subsequent serving uses copies of sealed
data/transactions and the control TDB2 directory; the original stores stay frozen.

Acceptance: three targeted new offline checks (changed input, first-load
failure, missing relationships); one tiny real load/close/freeze boundary;
then one full-data offline load. The previous accepted NL/query/compiler gates
are not rerun. An artifact being loaded does not assert campaign readiness:
native serving-copy startup, common observation/runner wiring and actual method
queries are separate remaining evidence. Existing RDF and NL evaluation results
and exposures remain frozen.
