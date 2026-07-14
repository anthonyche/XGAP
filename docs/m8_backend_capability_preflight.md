# M8 Backend Capability Profile + Compiler Boundary Preflight

## Status

M8 is completed after M7 Backend Infrastructure.

M7 proved that XGAP can start Neo4j and Fuseki services, load the
financial-risk toy dataset, run already-authored native Cypher/SPARQL
smoke queries, and record normalized backend smoke results.

M8 is no longer about whether the databases can run. It is about whether
XGAP can determine, before compilation, whether a backend can
theoretically support a particular XGAP path/GPC logical fragment.

## Core Goal

M8 upgrades backend `capabilities` from descriptive metadata into
program-checkable capability profiles.

The capability profile must use XGAP path/GPC vocabulary. It must not
introduce backend-internal logical operator names or graph-algebra terms
that are outside the XGAP logical model.

## Questions M8 Must Answer

1. Which XGAP path/GPC fragments does Neo4j support?
2. Which XGAP path/GPC fragments does Fuseki support?
3. Which M0-M6 logical constructs can be safely compiled?
4. Which constructs must explicitly return unsupported?
5. What is the format of compiler input, output, and failure reports?

## Expected Outputs

M8 produces:

- program-checkable capability profile objects or schemas;
- updated Neo4j and Fuseki descriptor capability sections;
- a compatibility-check interface that reports support,
  conditional support, or unsupported with reasons;
- a documented compiler boundary;
- typed compiler artifact and unsupported-report records;
- tests that verify supported and unsupported M0-M6 logical fragments.

The M8 compatibility checker must not compile queries. It only decides
whether a backend profile claims support for a logical fragment and why.

## Implemented Schema

M8 introduces these JSON-serializable records:

- `SupportLevel`: `supported`, `conditional`, or `unsupported`;
- `SupportReason`: machine-readable reason code plus human-readable
  message and optional future milestone;
- `FeatureSupport`: support level, reason, conditions, and metadata for
  one feature id;
- `BackendCapabilityProfile`: backend id, language, data model, feature
  namespace, and feature support map;
- `CompatibilityReport`: deterministic result of checking one feature
  or a feature set against a profile;
- `UnsupportedFeature`: blocking unsupported or conditional feature
  reported by a compatibility check;
- `CompilerInputSpec`: future compiler input boundary;
- `CompilerOutputSpec`: future compiler output boundary;
- `CompilerFailureSpec`: future compiler failure boundary.

The schema lives in `xgap.backends.capabilities`.

The static compatibility checker lives in
`xgap.backends.compatibility`.

## Capability Profile Expectations

Capability profiles should describe backend support using feature-level
XGAP terms such as:

- graph model support;
- directed edge/path support;
- node-label and edge-label predicate support;
- scalar property comparison support;
- recursive path support by XGAP `Recursive` mode;
- selector-style support for `GroupBy`, `OrderBy`, and `Projection`;
- focused quantified-pattern support, if any;
- result model support for paths, rows, bindings, and normalized smoke
  rows;
- limitations and explicit unsupported reasons.

Profiles should distinguish:

- `supported`: the backend can preserve the XGAP semantics for the
  construct;
- `conditional`: support depends on bounded depth, mode, result shape,
  query shape, or a documented restriction;
- `unsupported`: the backend cannot safely preserve the construct in
  this milestone.

## Profile Summary

### Reference Evaluator

The reference evaluator profile supports implemented M0-M6 in-memory
semantics:

- core path algebra;
- recursive modes;
- selector-style SolutionSpace operations;
- M5 `PathPatternQuery`;
- M6 focused quantified pattern semantics;
- M6 `BindingRelation` and focused binding operators.

It explicitly does not execute native Cypher or SPARQL.

### Neo4j

The Neo4j profile supports the native backend facts already validated by
M7:

- labeled property graph model;
- directed relationships;
- node labels;
- relationship types as edge labels;
- scalar property predicates;
- row bindings;
- native Cypher smoke-query execution.

It marks basic path-algebra constructs as conditional where a future
compiler could plausibly preserve the XGAP semantics, but where M8 does
not yet prove or implement compilation.

It marks exact SolutionSpace selector semantics and M6 focused
quantified semantics unsupported for M8.

### Fuseki

The Fuseki profile supports:

- RDF graph model;
- directed RDF predicates;
- row bindings;
- native SPARQL smoke-query execution.

It marks RDF encodings for labels and scalar properties conditional
because they depend on dataset mapping and datatype choices.

It marks XGAP PathSet path identity, exact SolutionSpace selector
semantics, recursive path restrictors, and M6 focused quantified
semantics unsupported for M8.

## Compiler Boundary Expectations

M8 defines the records and boundaries needed by future compilers.

The compiler input should be an already validated XGAP logical plan or
structured pattern lowering result, plus a target backend profile.

The compiler output should be a native query artifact, such as Cypher or
SPARQL, with metadata about language, backend id, result model, and
semantic assumptions.

The failure output should be an explicit unsupported report. It should
identify:

- the backend id;
- the logical construct or feature that is unsupported;
- the reason;
- whether support is impossible, future work, or conditional on a
  narrower fragment.

M8 only defines these records. It does not emit native query text from a
logical plan.

## Non-Goals

M8 must not implement:

- logical-plan-to-native-query compilation;
- optimizer rules;
- cost estimation;
- semantic-deviation scoring;
- ontology reasoning;
- bounded planning;
- dominance pruning;
- top-K selection;
- LLM candidate generation;
- KGQA evaluation;
- arbitrary conjunctive graph pattern support;
- backend-specific logical operator vocabulary.

## Boundary With Existing Layers

M8 does not change M0-M6 semantics.

`PathPatternQuery` and `FocusedQuantifiedPatternQuery` lowering remain
deterministic and backend-independent.

The M7 native-query harness remains valid for smoke testing, but native
smoke query execution is not evidence that a backend can compile every
XGAP logical construct. M8 adds the program-checkable boundary needed to
make that distinction explicit.
