# Frozen author summary and campaign method hosts

Milestone: connect the original FedUP/FedX hosts to the accepted disk-backed RDF
sources and per-request observer. This closes formal evaluation prerequisites;
it does not improve a baseline algorithm or repair its answers. Only experiment
preparation/host/controller code and new boundary tests are in scope. Existing
models, queries, catalog, population, baseline JARs and original failures stay fixed.

Build FedUP's summary offline once from the exact graph/control RDF input hashes.
Use named graphs `http://xgap-source.invalid/graph/sparql` and
`http://xgap-source.invalid/control/sparql`; these are logical identities only.
The original CLI `--modify` maps this common prefix to the current observed
loopback base URL. The author's server and ASK/source-selection paths already
implement this option. No query-dependent mapping or network access to `.invalid`.
Frozen summary files are copied for serving, never rebuilt after each question.

Use the pinned author server/summarizer JARs and existing hash modulo1 profile.
Two native TDB named-graph loads: one attempt each,2GiB heap/3GiB sampled RSS/900s.
One author summarizer invocation:4GiB heap/6GiB sampled RSS/900s, chosen before
any result because the original CLI materializes per-graph triple/quad lists.
All are offline costs, separate from the common online2GiB method/source budgets.
Keep the10GiB output/6GiB free-disk guard and all partial failures. Do not replace
the author summarizer with an optimized implementation or retry a failed run.

Host initialization has its own sealed observer phase; source requests during
initialization are accounted separately. Per-request failures still retire all
owned services; the next distinct cell gets a new session. Healthy method hosts
may retain their native caches. Idle hosts are outside the active method's RSS,
but total machine/package memory must remain feasible. Frozen host settings use
original FedUP with engine FedX and the already pinned matched FedX adapter.

Acceptance: prepare the new logical-source summary on the already accepted tiny
RDF inputs and issue one SELECT through each newly integrated host. Compare the
plain account business-ID rows to independent tiny facts; validate observation
seals and source routing, preserve any native failure, then stop owned services.
Do not rerun the previously censored generated FedX question, the FedUP aggregate
failure, or successful one-shot NL/planning gates. No live LLM call is needed.
If this boundary works, prepare the same summary recipe once on frozen SF0.1.
