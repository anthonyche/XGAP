# Frozen practical-mode request and replay contract

2026-09-14. Extends the approved strong-policy implementation without changing
the algebra, baselines, discrepancy definition or the declared outcome model.

## Research purpose and input boundary

Make the selected mode, information policy and frozen physical estimator the
actual inputs to the ordinary request path. This removes experiment-only Python
assembly as a prerequisite to measuring the new system. The factor is the mode
under the same trusted skeleton, request and source snapshot. This development
gate measures admission, authority, call consumption and outcome reproduction;
it does not measure a mode's effectiveness or speed advantage.

`FrozenPracticalProfile` pins the deterministic intake, frozen resolution bundle,
optional frozen estimator, source versions, backend capabilities/clients, model
prompt and safe configuration. Each mode specifies semantic permissions, search
limits, consumed physical limits and explicit action priority/estimated cost.
Unknown costs stay null. No configuration key silently enables an unsupported
legacy approximation. The loader performs no fitting, model or source call.

A separately caller-pinned request supplies trusted bindings, disjoint predictions
and optional binding-only clarification response pins. Pins establish identity;
the caller's trusted-input contract establishes authority. A hash alone does not
prove the natural-language interpretation. Arbitrary NL structure verification
is outside this release. Model proposals do not become authoritative.

The same prediction input is admissible to both modes when the performance mode
authorizes its slots. EXACT still validates every required slot. PERFORMANCE can
use the authorized prediction immediately. Clarification contents are read and
hash-checked only when the selected policy invokes that action. Missing tools
are unavailable to search. The response file and its source/program identity
must both match; file failures outside declared outcomes remain real failures.

## Publication and execution

`python -m xgap.experiments.practical_records` provides four explicit operations:

- `publish`: validate and freeze resolved dependency paths into a new file;
- `preflight`: construct the strong policy, without model/source/clarification calls;
- `execute`: follow the actual branch through the ordinary request entry and
  execute at most one final federated plan; capture each actual call once;
- `replay`: use pinned historical tool outcomes and exact native artifacts,
  parameters and results; make zero model or source network calls.

Publication resolves references; it does not copy stores, launch services, certify
backend contents, or release a paper campaign. The development fixture uses
unserved localhost source URLs. Endpoint deployment and snapshot verification
remain explicit before native use. Output creation is exclusive; no overwrite,
automatic retry or recovery from an indeterminate paid call.

## Replay and accounting

The v2 manifest requires complete captures, expected rows, and an outcome
fingerprint: request success/status, acquisition identity/status/value/error,
final execution status/error, node statuses/errors/row counts, and final rows.
Every captured acquisition and native call must be consumed exactly once.
Native calls match by exact artifact so independent dispatch order may differ.
Optional recorded byte counts and hashes are checked, including at consumption.
Configuration/replay manifests retain the16MiB read bound. Source captures now use
the existing512MiB BackendReplay bound with exact size/hash revalidation; see
[the source-capture correction](practical_capture_size_v1.md). This remains bounded
JSON replay, not a large-result streaming release. The practical worker reads a
small pinned [outcome](practical_outcome_v1.md) rather than the full trace.

A replay receipt's success means faithful reproduction. Its separate
`original_execution_success` can be false; a reproduced failure remains a failed
query. Merely producing another failure is insufficient. Started/indeterminate
calls cannot be certified as a complete replay. Changed failure reasons or
unconsumed observations invalidate equivalence. Replay failure cannot trigger a
live fallback. Historical time/tokens remain provenance, not new consumption.

Preparation, core request and outer recording durations are separately visible.
Outer recording includes profile/request reads and durable captures/results;
receipt serialization is outside that duration. Offline statistics/model build
and service preparation remain separate from online acquisition/planning/query.
Configured endpoint contents are not attested by this wrapper.

## Accepted development evidence

See [report](../report/practical_profile_20260914.md). Fourteen distinct new cases
and two affected cases pass across targeted runs. The CLI publication and v2
replay reproduce one previous live proposal and two exact native responses with
zero new network calls. No baseline, scale sweep, new model inference or training.
The deployed estimator reuses frozen weights with query-independent toy snapshot
statistics; transfer accuracy and policy-ranking benefit remain unproven.
