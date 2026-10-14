# Confirmed Fuseki query cancellation

This optional Jena 5.6 embedding extension adds `xgap-query` and `xgap-control`
endpoints to an existing dataset. It uses Fuseki's normal query processor,
dataset authorization and read-transaction lifecycle. It does not load or copy
another dataset and does not replace ordinary SPARQL endpoints.

Compile the two Java source files against the deployment's `fuseki-server.jar`
(Java 17+). In the existing embedded Fuseki launcher, after adding the dataset:

```java
ConfirmedCancellation.install(builder, "/data");
FusekiServer server = builder.build();
```

Preserve the deployment's authentication policy on this dataset and its HTTP
transport. Configure that dataset's XGAP `BackendDescriptor.runtime` with
`"confirmed_cancel_protocol": "xgap-fuseki-v1"`. Leave the setting absent on
ordinary Fuseki installations; their timeout/socket termination must not be
reported as acknowledged database cancellation. The extension is explicitly
installed by the operator, not downloaded or activated during answering.

The client registers a random 256-bit handle before query dispatch, sends it
in `X-XGAP-Handle`, and cancels only that handle. Handles bind the authenticated
principal and dataset, permit one execution and expire when unused. The bounded
registry never evicts active queries. Cancellation invokes `QueryExec.abort()`
and acknowledges only after query close and dataset transaction end; a request
that has not started is prevented from starting. If cleanup does not finish
within the acknowledgement window, the response explicitly says unconfirmed.

Query calls and control HTTP calls are metered separately. A fully consumed
response is also finalized through the control endpoint to verify lifecycle end.
Failed acknowledgements remain visible in the execution receipt. Client timeout
or connection shutdown alone never creates an acknowledgement.

Local regression (no HTTP listener, no server job):

```sh
XGAP_LOCAL_FUSEKI_JAR=/path/to/fuseki-server.jar \
  python -m pytest tests/test_confirmed_cancel.py
```

The regression compiles the extension and exercises real in-memory Jena query
abort, ownership checks, pre-dispatch cancellation and acknowledgement ordering.
Deployment authorization and transport integration need their own configured
backend integration tests before a production rollout.
