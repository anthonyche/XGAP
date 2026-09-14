# One-shot intermediate retention — 2026-09-14

Implementation and directed offline gate are complete; one native tiny boundary
is the next acceptance step. No new full-data question has run in this milestone.
The user clarified September14 10:00 is the resume time; execution is active.

Research scope: preserve exact selected-plan semantics while reducing retained
intermediate payloads and duplicate trace serialization. X is all versus explicit
root retention on the same independent tiny DAG; Y is exact rows, call/byte/node
metrics, registered rows, serialized trace bytes, failure visibility and replay.

Twelve new directed cases have passed across the targeted runs: six-row fanout
answers and node metrics; multiple roots including downstream consumers (success
and native failure); a deliberately delayed concurrent bind consumer; legacy
prefix/omitted-payload rejection; pinned response replay for success and native
failure; three corrupt-pin variants; failed capture with no retry; and current
ordinary estimated selection plus exact saved-response replay. The existing
failed-result-seal cost-accounting test also passed. No broad suite was run.

Measured tiny fanout: 6 final rows and 8 source invocations each. Full serialized
runtime trace 48,788 bytes; compact 18,412 bytes (62.26% smaller). Full end-of-run
registered rows255 versus compact6; compact registered peak48 rows /6576 encoded
output bytes, final283 bytes,48 released nodes. These counters are not peak RSS;
the tracing reduction does not establish full-data latency or memory speedup.

Initial collection found missing rdflib in the selected environment; the declared
7.1.4 wheel was installed from cache. Twelve checks then passed and two attempted
entry checks failed: the historical successful record has parameter admission v1,
while current admission is v2. It is correctly rejected. A test-only attempted
admission update still failed exact native-query identity due to previous compiler
changes; this was discarded, leaving the original historical recording and strict
checks untouched. Current tiny captures replace that unsuitable replay gate.
A concurrent in-process rdflib parser failure was isolated in the new fixture;
that fixture uses one parser worker, with scheduler overlap tested separately by
a deliberately slow consumer. Real native concurrency remains unchanged.

No model/remote GPU calls, baseline changes, new source preparation, or full-data
retries were needed for these checks. The tiny analytic estimator fixture uses
its independent synthetic training setup; production frozen weights are untouched.

Native acceptance: pending. Then run only the next predeclared real NL group8,
with a new implementation epoch and unchanged budgets, retaining all old outcomes.

The first real native gate executed one estimated coordinator plan correctly:
4 nonempty exact rows,14 source requests/18,606 response bytes; all source
processes and observer closed. Its replay failed because independent concurrent
requests reached the per-backend ordered replay cursor in a different order.
That original failed overall receipt is preserved. Indexed complete captures now
use an exact-artifact multimap and lock to consume each record once, independent
of unrelated request start order; duplicate requests retain multiplicity and hash/
identity checks. Legacy embedded records still require their old order. Seven
new/affected indexed-replay cases passed after this correction. The live query is
not repeated: only its newly saved records will be replayed offline.
