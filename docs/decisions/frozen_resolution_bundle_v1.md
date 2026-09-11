# Offline resolution bundle and runtime boundary

2026-09-11; design frozen before implementation, on ffb7b47. Accepted after native, focused, daily and final broad gates; see the T2-A report.

This is the first T2 lifecycle step. Existing resolution catalog/ontology
providers read versioned artifacts, but their executable binding-value map is
supplied independently. Pin these inputs together so a runtime cannot silently
combine a new catalog with old entity/schema/source/scalar bindings.

Scope: a small offline publisher and read-only bundle loader, existing provider
contracts, a catalog-backed wrapper around the existing semantic goal loop,
toy agent/native integration and failure tests. No new algebra, query type,
model invocation, external download, Freebase scan or catalog ranking change.
The finite support clarification remains in bounded_system_scope_v1.md; this
step does not declare the whole T1 or T2 complete.

A bundle contains the existing catalog JSON, typed binding values and optional
ontology JSON. Every reachable catalog/ontology candidate has exactly one
compatible executable binding. Providers retain their current validation and
candidate-authority semantics. Provenance/versions and the content hashes of
all files determine a bundle hash. Runtime must receive an expected hash from
caller-owned configuration; reading a digest from the same manifest does not
count as pinning. The hash is version identity, not a signature or trust oracle.

Publishing is an explicit offline operation. Validate a copied snapshot of the
inputs first, exclusively create the output directory, write content and publish
the complete manifest last. Existing output is never overwritten, even if it
has the same bytes. An interrupted output remains incomplete and cannot be
loaded; a future intentional build uses a new output. No implicit rebuild/retry.

Runtime opens only the small frozen files, checks the supplied version and
contents, and uses the existing local providers plus typed bindings. It neither
imports the builder nor accesses the unfrozen input paths. Missing, incompatible,
incomplete or mismatched bundles stop before model/database dispatch. The
catalog-backed query entry assembles catalog tools and bindings from one bundle;
only an explicit user-clarification tool may be supplied separately. Provenance
includes the bundle identity. Deterministic gold-program execution remains
available through its existing LLM/catalog-independent API.

Acceptance: offline build→freeze→remove preparation inputs→load→query; immutable
version/no overwrite; missing/tampered/cross-kind inputs stop before dispatch;
optional ontology bindings validated; runtime read/write/import isolation;
five existing agent toy goals, independent binding/answer gold and native
Neo4j/Fuseki execution with the permanent original slice. Focused, daily and final
broad checks follow stabilization. Saved minimal failure inputs are replayed
locally. This does not yet migrate the large GrailQA SQLite catalog, implement
general transcript replay or measure true-model Interpretation quality; those
remain explicit T2/T3 work, without a large-data development run.
