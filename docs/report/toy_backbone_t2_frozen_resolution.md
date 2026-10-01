# T2-A: fixed-version resolution inputs in the real agent query chain

2026-09-11; base ffb7b47. Accepted: native, focused, daily and final broad gates passed.

## Implemented behavior

The existing artifact catalog was read-only, but its candidate identifiers and
executable binding values were supplied separately. The new offline publisher
validates and freezes the existing catalog, typed bindings and optional ontology
as one content version. Every catalog/ontology candidate must have one binding
of the correct kind. Existing authority and ambiguity rules remain unchanged.

`python -m xgap.catalog.build --catalog CATALOG --bindings BINDINGS --output NEW_PATH`
publishes an explicit offline snapshot. `--ontology` is optional. It validates a
copy of the input bytes, reserves a new output directory, writes its contents,
then atomically publishes the complete manifest. It never replaces an existing
output, including a failed/incomplete one. Version identity is a content hash;
new intentional versions require explicit caller configuration.

`run_frozen_semantic_query` takes the snapshot path and expected hash. It loads
the read-only snapshot, creates the existing resolution tools, binds through
the existing semantic binder and runs the normal costed planner/executor.
Catalog inputs and executable values cannot be independently substituted through
this entry. Only an explicit user-clarification tool may be supplied alongside
the frozen providers. The result and bound program include the bundle identity.
Missing/corrupt/incompatible preparation produces `catalog_unavailable` before
any model/backend dispatch. It does not call or import a builder.

Artifact provider hashing/parsing now consume the same bounded byte snapshot,
preventing the reader from identifying one file version but parsing another.
The direct deterministic API remains independent of catalogs and LLMs. No path
or binding algebra changed. No Freebase/GrailQA dataset scan or model call ran.

The separate [finite query profile](../bounded_query_profile_v1.md) now records
the first-system language, exclusions, resource bounds and operator-by-layer
evidence. It does not classify a query by whether the compiler succeeds, install
a new universal3-hop cap, or drop any benchmark obligation. Scope outside that
language is not an endless T1 feature backlog.

## Independent validation and real execution

The frozen `backbone_binding_bundle_v1` snapshot copies only the old catalog and
bindings, not expected answers or native queries. The old B01–B05 programs,
independently authored binding/answer gold and native reference files remain
unchanged. The existing native harness now runs these goals through the frozen
entry rather than independently assembling an unpinned value map and provider.

| Gate | Actual result |
|---|---|
| Focused99761 |87 passed in2.79s |
| Daily61671 |517 passed in27.82s, plus18 original toy demo cases |
| Native23609 |5/5 agent programs,18/18 candidate answers,10/10 independent Cypher/SPARQL targets |
| Permanent vertical slice |Original two-engine query remains correct |
| Final broad2851 |Exit0:3362 passed/38 skipped in673.89s; all24 harness/example entrypoints passed |

The native run is `/Users/anthonyche/xgap-data/t2-frozen-resolution-native-20260911`.
It uses owned fresh Neo4j5.26.30/Fuseki5.6.0 stores and Java21.0.10. All5 runs
record the expected bundle hash
`8cfb17e9dd780546f3dedb2accc924055bc8a67d930c385f39882a826b0734bf`.
Counts are18 observations +9 serving calls +25 additional candidate-validation
calls +10 independent references +2 old-slice calls. The controlled user-selection
case is separately recorded; no genuine LLM output or mobile interaction is implied.
Both services stopped normally without KILL. All measured native source hashes
match current code. No external failure or retry occurred in this native gate.

Local tests independently exercise:

- offline publication, deletion of all owned preparation copies, and a complete
  query while forbidding any catalog/binding read outside the pinned snapshot;
- read-only files with unchanged bytes and modification times after loading;
- missing/tampered/incomplete/wrong-version inputs, including rehashed cross-kind
  corruption, without rebuilding or database calls;
- optional ontology candidates with matching bindings, and conflicting/missing
  values rejected before publication;
- an interrupted manifest publication that cannot be loaded or overwritten;
- a clean process that loads the runtime/catalog reader without importing the
  builder, GrailQA catalog builders or raw Freebase source readers;
- preserved entity ambiguity and one controlled backend failure observed once.

Initial focused gates98465 and1586 passed62/2.17s and86/2.72s as tests were added.
These are not extra benchmark samples. All deliberate failures use owned local
test inputs. No expensive external failure is rerun. General transcript replay
is not claimed by these narrower failure checks.

Receipt: `experiments/artifacts/toy_backbone_t2_frozen_resolution_20260911.json`.
No source/test edits after the final broad launch. All test/native handles are
terminal; final36 source hashes and5 bundle fixture hashes match. Original tracked
fixtures are unchanged. Full log: `/tmp/xgap-t2-frozen-resolution-acceptance.log`.

## Remaining work

This step supplies an executable small-catalog lifecycle in the real generic
agent query chain. The historical GrailQA SQLite reader/build modules and every
legacy experiment entry have not been migrated here; global catalog/runtime
separation is therefore still a T2 obligation. Source snapshot/mapping assertions
remain caller-owned, and content hashing does not certify catalog truth.

Next add the common Interpretation contract and minimal recorded-provider/tool
failure replay on the same toy programs, then migrate legacy catalog runtime
dependencies without a large rebuild. Real-model/GrailQA-mini integration, UI,
streaming/cancellation and the full EQ1–EQ5 baseline/ablation evaluation remain
separate unfinished gates. Overall system Goal stays active.
