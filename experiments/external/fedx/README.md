# FedX transport adapter

This research adapter exposes the official RDF4J/FedX5.1.2 library as a loopback
SPARQL SELECT endpoint. It does not call XGAP's compiler, estimator or optimizer.
The dependency matches FedUP commit4c1a3aa8137a3940f7f8255397cb8fec717c8afa's
[declared pom](https://raw.githubusercontent.com/GDD-Nantes/fedup/4c1a3aa8137a3940f7f8255397cb8fec717c8afa/pom.xml).
API usage follows the [official federation documentation](https://rdf4j.org/documentation/programming/federation/).

Build with Java21 and Maven. `mvn -DskipTests package` packages the thin adapter;
it does not load data or run queries. The resulting jar's `--help` performs no
repository initialization. Run with positional port, query timeout seconds and
explicit SPARQL endpoint URLs. Send SELECT text to `/sparql` with Content-Type
`application/sparql-query`; response is standard SPARQL JSON. No default endpoints.

Keep the JVM alive across the declared timed block. One top-level request is
processed at a time; FedX uses its native source-selection cache and joins with
bound-join block10, join workers10 and union workers10, matching the pinned FedUP
executor. Its standalone JSON/XML readers are explicitly registered as in FedUP.
Setup/init traffic and cache state must be observed separately. These are published
baseline settings, not tuned optimal settings. Do not claim concurrency throughput
from this sequential adapter. Later use a common HTTP observer for backend ASK/
query/bytes accounting, rather than estimating those counts from returned rows.

Query/result limits are1MiB/16MiB, errors are failures rather than successful partial
answers, and there is no automatic retry. The engine query timeout is not a hard
global process deadline; the experiment launcher must supply its declared watchdog.
The adapter's response header times server work only, not client end-to-end latency.
Gold scoring and durable invocation/response records belong to the external harness.

Build status and actual tiny endpoint correctness are separate acceptance gates.
See `docs/report/external_federation_preparation_20260912.md` in the repository.

2026-09-22 baseline integration also accepts GET and form-encoded SELECT requests.
`scripts/build_ch6_fedx_transport.py` can replace only the adapter classes inside
the frozen distribution, checking that every external entry is byte-identical.
The historical diagnostic JVM switch `xgap.fedx.debugErrors` emitted exception
stacks; the current source replaces that output with the bounded fields below.
`xgap.fedx.disableOptionalBind` was tested against a NULL failure and did not fix
it; the admitted baseline profile leaves it off and retains the original config.
ARUQULA compatibility is in its separate worker overlay, not this engine. See the
[frozen protocol](../../../docs/decisions/ch6_planner_external_followup_20260922.md).
Successful HTTP execution and agreement with an independent answer are recorded
separately; the adapter never deduplicates or corrects the engine's returned rows.

2026-09-26 source-only diagnostics record the failure stage (protocol, connection,
prepare, configure, evaluate, serialization callback, connection close, or HTTP
response), exception class, bounded root-cause class and SHA-256 of the exact
decoded query. They do not emit query text, messages, headers or response bodies.
The existing HTTP status/body, JSON writer, query bytes and retry behavior stay
unchanged. This change does not update any frozen jar or prior run manifest.

For the focused offline contract check, set `XGAP_TEST_FEDX_JAR` to an existing
frozen distribution and `XGAP_TEST_JAVA_HOME` to a Java21 JDK, then run
`pytest -q tests/test_fedx_failure_diagnostics.py`. The check compiles only into
its temporary directory, uses the real SPARQL parser with fake repository/HTTP
boundaries, and executes no source query or network request. It checks parse and
evaluation failure separation, serialization errors, HTTP compatibility, and
unchanged decoded query text including special characters.
