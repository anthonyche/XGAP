# Hand off practical answers without rereading complete execution traces

2026-09-15. The practical worker reread its full core trace through the generic
16MiB pinned-configuration reader. Intermediate materialized node rows can exceed
this limit even when the final answer is small. This can turn a successful native
query into an artificial worker failure. The old one-shot entry already separates
its answer outcome from the full trace; apply that boundary to practical records.

Scope: practical outcome serialization and worker consumption, focused saved
replay checks, evidence/status documentation. No algorithm, semantic, cost-model,
query, native source, baseline, population or evaluation change. The RQ is whether
reported successful completion reflects the executed result rather than trace
size; the controlled factor is retained intermediate-trace size, not graph scale.

The producer still durably writes the complete original trace, then a pinned
outcome with final rows, success/status, validation/uncertainty metadata, exact
reported model usage and the time partitions the common worker consumes. It omits
intermediate rows, candidate/policy payloads and unused invocation text. The
outcome includes the full trace pin; the reader requires it to equal the receipt.
The worker reads this small handoff and retains the full trace reference. It never
repairs answers, guesses missing metrics or rereads source captures. New receipts
start with outcome=null; failed sealing cannot silently fall back to the full
trace. Legacy records without this field retain bounded legacy reading.

The shared16MiB admission bound remains: this milestone does not introduce a
streaming interface for unbounded final answers. Full trace generation/retention
and its memory cost remain visible, and outcome writing is part of online time.
One snapshot's hash link supplies record identity, not semantic truth or an
attestation that a mutable external service has not changed.

Acceptance uses saved native/model replay plus a controlled>16MiB intermediate
row payload; no large database run. Final answer and existing outcome fingerprint
stay unchanged and the worker returns success from a<4KiB summary. A mismatched
trace pin fails; missing new summary cannot fall back; old bounded records remain
readable; a faithfully replayed failed method stays failed. Zero new network.
