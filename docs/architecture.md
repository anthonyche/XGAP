# Architecture

The primary entry point is `xgap.api.answer_unified`. It combines semantic
interpretation with bounded physical planning and one final execution over
Neo4j and Fuseki. `answer_unified_controlled` uses the same controller from an
explicit initial state, without the natural-language initialization step.

## Request flow

1. A proposal provider uses a frozen source schema and public finite domains to
   propose a bounded candidate family.
2. The declared authority confirms scope and supplies required binding validations.
   Model output and catalogs cannot attest user intent.
3. Protected seed plans and source capability evidence establish a completion route.
4. The online controller compares eligible final plans, information actions, and
   checked local rewrites using fixed-depth lookahead.
5. One selected action is performed and metered; the controller updates its actual
   state and replans. Hypothetical lookahead makes no external calls.
6. The runtime checks the final contract and executes one selected plan, returning
   materialized rows and an observed execution trace.

## Contracts

`Lambda` identifies validations allowed to remain unresolved. `epsilon` bounds the
implemented discrepancy between structured queries over the confirmed finite
family. Neither parameter turns the system into a different algorithm. Hard fields
never relax, mandatory validation does not disappear for singleton candidates, and
query discrepancy does not bound answer error.

The controller retains protected seeds and reserves a completion recipe for every
outcome, including unknown and zero-probability outcomes. Unknown resource bounds
cannot certify a finite budget. On an optional search deadline, incomplete action
scoring cannot replace the completed fallback.

`agent.unified_family` manages bounded candidate and plan pools.
`runtime.unified_physical` generates individual checked transformations.
`agent.unified_information` handles registered information actions. Only selected
actual actions enter paid accounting. Backend and transport failures remain
explicit outcomes rather than successful empty answers.

The runtime preserves directed edge semantics, scalar identity, row lineage, and
join/filter/aggregation behavior. Binding restrictions and native pushdowns must
carry sufficient equivalence evidence. Approximate truncation is not a valid
replacement for exact query semantics.

## Implementations and evaluation support

`src/xgap/experiments` contains reusable data preparation, evaluation contracts,
reference scorers, process supervision, and source observations. `scripts` exposes
supporting execution and service-management entry points. These are implementation
utilities; generated results and machine-specific run packages are not distributed.

The default, no-probe, shallow, and myopic settings share semantic eligibility and
completion guards. Different deployment support and measurement boundaries must
remain explicit when comparing configurations. The legacy APIs retain separate
identities for compatibility.

## Limits

This is a bounded research prototype. It does not promise arbitrary natural-language
coverage, global optimality, or successful execution under every backend failure.
The portable demo demonstrates a small synthetic graph. It is not evidence of
large-workload performance or backend readiness on another machine.
