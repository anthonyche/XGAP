# Next tiny gate: one-shot intermediate rows and trace retention

2026-09-13, pending implementation after equality-key statistics and real NL
group7 acceptance. Do not claim this design is implemented or a measured gain.

Both real XGAP modes selected anchor fanout, executed once and returned the
correct empty answer. Full online80.876/84.423s; method sampled peak2.111/1.654GB
under the original2GiB limit. Each complete trace is603.9MB although final rows
are empty. Scheduler currently retains all RuntimeNodeResult.rows until return;
RuntimeNodeResult.to_dict then copies every intermediate row into the public
execution value. This is verified code behavior. Its share of total measured
latency/peak RSS has not yet been isolated; do not claim all cost is logging.

Next bounded scope: contracts/scheduler/tool serialization and the ordinary
one-shot entry, focused tiny tests, and compact result provenance. Keep existing
legacy full-trace/prefix/replanning APIs intact. Choose an explicit one-shot
retention mode if needed, rather than silently changing all callers.

- Preserve every final answer row and all original query/plan semantics.
  Release a nonroot intermediate only after every dependent operation has
  consumed it. Shared fanout, concurrent remotes, multiple roots, and failed
  consumers must remain correct; roots may themselves have downstream users.
- Keep actual row counts, statuses, elapsed/byte/call metrics and errors after
  releasing rows. Mark omitted payloads explicitly, never serialize them as
  a fabricated empty result or substitute a sample for a full final answer.
- Avoid duplicating all intermediate row payloads in the final trace. Preserve
  selected program/plan, stats/model hashes, interpretation and native request/
  response pins for failure replay. Existing backend capture already persists
  complete source responses; do not claim storage is free or silently drop it.
- This changes instrumentation/resource behavior and therefore needs a new
  implementation epoch in evaluation. Do not rescore or retry the old question,
  increase resource limits, alter baselines, or fit the cost model to this result.

RQ: does bounded retention enable the same one-shot semantics with less retained
intermediate data/serialization? X: current full retention versus explicit
one-shot retention on one independently authored tiny DAG; Y: exact answers,
peak retained rows/payload size, preserved counts/calls/errors and replayability.
Only test these new lifetime/serialization risks and one necessary tiny vertical
slice. Use a saved structural diagnostic before any new full-data request.

If the gate passes, continue the immutable new equality-v1 NL journal at group8,
at most the next predeclared bounded chunk. Do not reopen previous journals.
Full nonempty NL quality, population-level comparisons, FedShop and scalability
remain required evaluation work; a single empty-answer success does not fill
those gaps. This is a prototype resource correction, not a general logging or
streaming platform project.
