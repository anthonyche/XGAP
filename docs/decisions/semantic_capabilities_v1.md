# Semantic capability admission v1

2026-09-10. Accepted: native8/8 programs,16/16 admitted placements and the old
slice pass;12 placements rejected as expected. Focused120/daily300 and full
3145 passed/38 skipped with24 harness/example entrypoints. This is a static
capability integration milestone, not complete-system acceptance.

The semantic compiler currently rejects every nonempty required_capabilities
tuple. Connect the existing requirement vocabulary to the implementation that
actually realizes each operator, without adding algebra or relaxing meaning.

Admission happens after pure compilation and before a plan is returned to
observation/selection/execution. A requirement belongs to its semantic operator:
only runtime nodes emitted for that operator may witness it. Capabilities of a
child, another source or another placement cannot satisfy it. Every requested
name must have a witness; unknown names fail explicitly. The planner retains
rejected placements and registers observations only for admitted plans.

Native language requirements native.cypher/native.sparql require a compiled
remote artifact in that language. property_graph.read/rdf_graph.read additionally
require the matching declared backend data model. Existing native compiler
profile, encoding, shape and condition checks still run; neither a profile's
theoretical supported flag nor this admission layer bypasses them. This proves
static compilability, not endpoint health or that a query has executed.

Coordinator requirements name actual emitted operations: coordinator.join
(legacy alias equality_join), semi_join, aggregate, order_limit, path_select,
filter, project, align and union. Each uses the coordinator. They do not assert
that a native engine supports the same operation. The requirements are local
execution obligations, not a request to insert a missing operation. In
particular, coordinator.join on a Match does not invent a join. Domain-specific
requirements such as window_total are not equated with a generic aggregate.

The plan records requirement-to-node witnesses. Empty requirement tuples retain
the previous plan shape/metadata. Gold, graph data and original fixtures remain
frozen; small explicit overlays add requirements to existing complete toy chains.
No online discovery, model call, catalog build or automatic retry is introduced.

Scope: semantic compiler/admission, requirement validation, development fixtures,
tests, harness and status documentation. No algebra or historical benchmark edits.
Gates: supported and rejected placements; owned-node isolation; native compiler
limits still enforced; exact typed RDF toy results and selected-plan execution;
one real two-engine capability-constrained slice; targeted/daily tests followed
by the shared-core acceptance suite and existing examples.
