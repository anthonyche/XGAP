# Necessary primitive row screening at native sources

2026-09-14. The saved 8-node/16-relation request reads Account.id and
Medium.isBlocked before applying mandatory equalities after joins. This bounded
change asks whether native screening reduces returned rows/bytes without losing
answers. Factor: necessary string/boolean equality screening; outcomes: independent
gold equality, actual source calls/rows/bytes. New cold-session latency is recorded
only, not compared as a speed result. No estimator fitting or candidate probing.

Scope: compiler wrapper, runtime proof pass, new practical strong baseline and
optional domain, focused tiny tests and one native boundary. No new semantic
operator, discrepancy metric, baseline, source facts, model weights or population.
Both modes benefit; this optimization does not change either mode's permissions.

Retain every original semantic constraint and final typed coordinator filter.
Only take string/boolean constant equalities occurring as mandatory AND atoms.
For a Match scalar projection, prove that every consumer route reaches the
enforcing Filter without an independent output root or a field-changing operator.
Permit Filter, Union, identity field Project and inner Join with preserved column
identity. Decline a renamed right collision, except an identically named join key
whose typed equality establishes preservation. Decline limits, aggregates, paths,
renames, OR/NOT, field-to-field comparisons, numeric comparisons and temporal
coercion. Take at most64 proved source/condition applications in input order.

Wrap the complete unbudgeted native Match query. For Cypher, screen only values
whose native type is STRING/BOOLEAN; let all other types and nulls through.
For SPARQL, screen xsd:string by sameTerm and valid xsd:boolean lexical values by
their truth value; preserve other literals, resources, missing values and invalid
boolean lexical values. The existing decoder/final typed filter still decides
them. String/native-temporal serialization and bool-versus-number equality are
therefore not silently reinterpreted. Never substitute the existing path predicate
compiler: its equality and existential RDF-property semantics differ. Projected
RDF multivalues remain separate rows, subject to the unchanged final filter.

Proof: every removed row has a recognized primitive value that cannot satisfy a
mandatory downstream equality. Every intervening allowed operator preserves that
field, and all consumers require the same filter. Thus it cannot contribute a
surviving output; induction through the unchanged DAG preserves answer rows and
multiplicity under valid typed source decoding. This is necessary screening,
not a general predicate-equivalence theorem or arbitrary corrupted-data failure
equivalence. Unknown values may cost extra work but cannot justify a false
negative. The pass does not estimate selectivity or reduce a retrieval budget.

Apply before identical-read sharing: only requests with the same entire guarded
artifact may share. Retain native bind parameters and VALUES placeholders.
Unrecognized/budgeted artifacts decline; no external call is made by the proof
or compiler. Strong baseline and optional candidates use the same pass. Refresh
actual plan features without a fabricated selectivity discount. Legacy one-shot
defaults source_row_prefilters=False. No candidate is added and call count does
not increase; old conservative call admission remains unchanged.

For P input predicate atoms, N semantic operators, E semantic dependencies,
runtime plan size L and native text bytes B, memoized field preservation costs
at most O(P*N*(N+E)); rewriting/serialization is polynomial in L+B with at most64
added guards. Space is O(P*N + E + L + B), conservatively. This adds no exponential
enumeration and gives no latency approximation ratio/global optimality claim.

Acceptance: actual in-process SPARQL type/multivalue cases, preserved side outputs,
field collisions, barriers, shared identical guarded reads, real bind serialization,
and both strong modes' one-plan tiny slice. Then one frozen-store Neo4j/Fuseki
request with three proved source applications, eleven source calls and the same
four-row independent gold. Do not repeat the six-cell cost diagnostic.
