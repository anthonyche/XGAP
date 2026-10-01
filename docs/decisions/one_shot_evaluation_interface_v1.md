# Frozen dataset interface for one-shot evaluation

This milestone closes an experiment-reuse gap, not a new inference algorithm.
The generic run_question entry already works; current actual model drivers embed
toy-specific dataset and request preparation. Research acceptance needs the same
mode/estimator/strategy path under independently frozen dataset configurations.

The interface accepts a caller-pinned JSON profile: dataset/source versions,
logical replicas, schema context, semantic backend encodings, frozen catalog and
estimator file identities, mode policies and provider/prompt identities. It does
not discover data, start/load servers, build catalogs, fit models, or probe plans.
Endpoint addresses and credential environment-variable names are explicit; keys
and passwords are never configuration values. Snapshot declarations remain a
deployment assertion; file hashes do not prove the current server contents.

Each request separately declares its question ID, original NL, optional explicit
requirements and population/exposure metadata. Exposure and evaluation labels do
not enter LLM context. No gold program, target plan or answer belongs to the input
profile. The runner validates the whole configuration before any external call,
records an intent once, executes the common entry once, seals its complete result
and records a terminal receipt. Errors remain in the denominator; unknown calls or
tokens remain unknown. An existing output directory is never a retry permission.

Preflight is zero-call. Offline replay is an explicit execution kind, with current
network calls zero and historical usage/times retained separately. It must match
the exact recorded request and backend artifacts; changed plans cannot consume
another plan's recorded rows. Live and replay data must not be pooled as timings.
Pure row evaluation is separate and follows the result seal, using an explicitly
normalized JSON multiset or ordered-row contract. No general semantic-equivalence
claim is made. Record selected plans, prediction uncertainty, all failed candidates,
online stage costs and separate offline preprocessing provenance.

Allowed: thin frozen-profile/runner/replay/scoring adapters, CLI, focused new-risk
checks and documentation. Keep compiler/planner/grounding/training behavior and all
historical evidence unchanged. Reuse actual saved success/failure for adapter
validation; no new external model/database executions, fitting or comparison runs.
Acceptance is profile portability, strict hash/source/mode binding, one invocation
and terminal persistence, exact replay refusal on changed inputs, failure/unknown
accounting, and post-seal answer scoring. Ptime planning bounds stay as previously
declared; wrapper work is linear in bounded input/result serialization size.

After this interface and the bounded core evidence are accepted, discuss the
16–20-figure RQ/X/Y and external-SOTA protocol before new evaluation campaigns.

## Usage

`scripts/run_one_shot_record.py run` requires `--profile-path`, `--profile-sha256`,
`--request-path`, `--request-sha256`, `--mode precision|performance` and a fresh
`--output` directory. The default is zero-call preflight. Explicit
`--operation execute` uses configured credential environment variables and loaded
native stores. `--operation replay` additionally requires `--replay-path` and
`--replay-sha256`; it makes no network calls. Do not reuse an output directory.

`evaluate` requires the receipt path/hash, reference path/hash and a fresh output
file. Hashes are SHA-256 of file bytes. Catalog identity uses its existing frozen
bundle hash. Relative file references resolve against the profile's directory.
Both mode definitions are validated, even when only one mode is requested.

The top-level profile has schema_version, profile_id, dataset, source_schema,
sources, backends, catalog, estimator, modes and offline fields. A request has
schema_version, question_id, question, population and exposure, with optional
required_constraints/requested_output. A reference uses
`xgap-normalized-row-reference-v1`, dataset, question_id, ordered and rows.
The executable small profile construction and saved actual response fixtures are
in `tests/test_one_shot_records.py` and `tests/fixtures/one_shot_record_replay/`.
They are development examples, not a frozen evaluation population.

Limits:16MiB per pinned file,1..64 logical sources and backends, one source per
backend, registered Neo4j/Fuseki clients, existing semantic capability admission.
Backend timeouts are finite; this wrapper does not add a global process deadline.
External snapshot validity and row normalization must be established by the
dataset protocol. Per-call durable capture is inside core latency; result and
receipt persistence boundaries are explicitly labeled. Terminal records preserve
failures, but cohort membership/denominators belong to a separate frozen manifest.

Accepted interface evidence and remaining evaluation scope are recorded in the
[bounded core audit](../report/one_shot_core_freeze_20260912.md).
