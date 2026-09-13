# Native campaign boundary v1 — 2026-09-13

Complete the approved FinBench native deployment comparison by connecting frozen
store copies to the existing common observer, worker, score and no-retry journal.
This is an evaluation integration change; it does not alter semantic operators,
interpretation, estimator weights or baseline algorithms/configuration.

The factor is native Neo4j/control-Fuseki versus same-facts dual RDF deployment;
outcomes are answer quality, full online latency, source calls/bytes and resources.
Do not interpret native engine/encoding differences as a planner-only speedup.
The original native control and disjoint-RDF control revisions remain separate.

NativeStoreSession verifies pinned engine/store contents before copying, starts
only job-owned loopback services, and redirects both clients through the same
bounded observer. Record Cypher statements and parameters without changing wire
bytes or logging authorization values. Neo4j uses 768MiB heap/128MiB page cache;
Fuseki uses 768MiB heap. Keep the existing common 2GiB aggregate source RSS and
2GiB method RSS sampling limits, 180s request wall and 120s source I/O limits.
Startup/copy/hash costs are separate from online execution. No runtime data loads,
catalog rebuild, warmup query, probing, retry or fit.

Add explicit `xgap-native` fixed-semantics method admission requiring both engine
types; ordinary NL retains precision/performance names with native deployment
identity. No FedUP/FedX host or RDF summary is attached to the native deployment.
Native schedules retain all 48 frozen evaluation groups, the same question order,
three fixed blocks (144 cells), and one NL block with alternating two-mode order
(96 cells). No current answers are read to order, include or exclude questions.
The existing RDF schedule/results are unchanged.

Acceptance: five new focused checks for deployment labels, ordering, JSON wire
fidelity, copy retirement and controller isolation; one real tiny serving-copy →
common fixed worker → independent nonempty answer → shutdown boundary. Reuse the
previous frozen tiny stores by a separately sealed source-hash-equivalent profile
association; do not reload or replace them. Then start the real native campaign
from the beginning of its frozen order. Earlier RDF/NL question exposures remain
declared; no claim of fresh template-held-out data. Old accepted gates are not
rerun. Baselines stay on their declared RDF track and remain present in eventual
overall comparisons with explicit representation labels.
