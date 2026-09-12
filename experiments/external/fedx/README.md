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
