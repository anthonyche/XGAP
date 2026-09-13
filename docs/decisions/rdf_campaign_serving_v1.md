# RDF disk serving and balanced evaluation dispatch

Scope: prepare existing frozen graph/control inputs for the approved common RDF
track, serve owned copies, and freeze/dispatch evaluation cells. No query, baseline
algorithm, estimator, catalog, population or reference changes. No large-data
debugging: validate the new disk-to-HTTP boundary on the accepted tiny facts first.

Use the same pinned Fuseki5.6.0 JAR for TDB2 loading and serving. Each source gets
one default phased loader invocation,900s/3GiB sampled RSS/2GiB Java heap. Preparation
has10GiB sampled output cap and6GiB free disk reserve; require16GiB free initially.
The two source stores are loaded sequentially, sealed, and preserved. Each serving
session verifies source/engine/store pins, copies stores, starts read-only loopback
Fuseki instances with768MiB heaps and120s query/I/O limits. Common observed source
RSS remains2GiB. Preparation RSS is not the online query budget. No warmup queries.
Store verification, copies and initial startup are explicit offline/session costs;
post-failure replacement costs must be retained and separately amortized/reported.

Acceptance is one tiny TDB load and two source HTTP counts211/36 using the campaign
observer, with phase sealing/release and all owned processes terminal. These do not
repeat model, planner, financial-answer or baseline gates. Then the full already
frozen SF0.1 files may be loaded offline once; this is not an evaluation query run.

The schedule contains the unchanged48 evaluation groups. NL has one block and
four methods (XGAP precision/performance, FedX, FedUP); fixed semantics has three
blocks and three methods (estimated XGAP-RDF, FedX, FedUP). The frozen hash ordering
does not inspect answers or outcomes. Williams rows balance positions and directed
adjacency over complete cycles. This defines192 NL cells and432 fixed cells.
Only a fixed-semantics cell references gold; NL workers receive the original NL-only
request. Scoring uses the separately pinned reference after the method result seal.

Dispatch processes at most one query group per call. Exclusive intent directories
prevent redispatch, including interrupted or orphan directories. A prior incomplete
intent is indeterminate, never permission to retry. Missing prerequisites leave
cells unrun. Actual host/session callbacks must enforce resource readiness/recovery,
package disk/time/model budgets, retain failed denominators, and register canonical
terminal method outcomes. This generic controller does not yet claim those callbacks
are integrated or set formal_campaign_ready=true. Schedule pins are immutable;
readiness is a separate pre-dispatch receipt, not a rewrite after seeing outcomes.

No automatic5-block extension or stochastic NL repeats are activated here. The
approved12-group repeat and remaining experiments stay later declared evaluation
work; native FinBench, FedShop and other retained obligations are not dropped.
