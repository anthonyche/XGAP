# T3-B: execution-observation memory for the common question entry

2026-09-11, frozen before implementation on8db41fa. User explicitly prioritizes
the research prototype and paper experiments over perfect/general implementation.

The same question entry must support a cost-inclusive memory versus no-memory
contrast. It currently accepts a manually supplied snapshot; the integration
gap is automatic lookup and persistence through the existing MemoryStore.

Add an optional small SemanticPlanMemory adapter using the existing in-memory
or JSONL store. An explicit environment episode and finite maximum age are
required. Key reuse by exact candidate plans/meaning, registered observations,
cost parameters and episode. Candidate metadata already includes declared
source snapshots and the frozen resolution bundle. No answer caching: even a
memory hit executes the chosen backend plan. Keep the original no-memory and
static paths unchanged. Explicit snapshot/static/memory conflicts fail before
backend calls. A missing/expired/context-changed entry acquires observations;
an invalid stored record is a terminal error, not an automatic external retry.

Persist only a complete successful observation collection, with its snapshot,
actual acquisition call/time accounting and provenance. Historical acquisition
cost stays attached to the memory read and is not charged again as fresh calls.
The whole query's elapsed time includes memory read/write overhead. Partial
observations are retained by the run but never published as a complete entry.
Stored information may become stale inside an episode; expiry/re-scoping is
explicit. This step does not claim learned family transfer, adaptive within-query
replanning, calibrated predictions or a performance advantage.

Allowed: a small memory adapter, semantic_planning/agent argument plumbing,
existing toy and native harness options, targeted tests, evidence/docs.
Forbidden: algebra/compiler changes, new graph/gold/catalog, legacy FinBench
protocol changes, new general experiment framework, large server datasets,
changes to the deployed bc2bb67 model producer.

Acceptance: cold and warm runs through the same question entry keep independent
gold answers; cold acquires and warm reuses, no-memory acquires again. All fresh
and historical calls/times are explicit. Source/meaning/environment/cost changes
or expiry cannot reuse stale context; invalid state has zero backend calls;
failed acquisition publishes nothing, and query failure is terminal. Persistence
survives a JSONL store reload. Verify a cold/warm sequence on the existing tiny
real Neo4j/Fuseki graph, focused tests and one final broad gate. Research results
still require real data/model and controlled comparisons; this is their plumbing.
