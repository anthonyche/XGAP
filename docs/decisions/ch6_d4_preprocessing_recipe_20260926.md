# D4 offline recipe, prepared while 3886776 runs

2026-09-26. This is subsequent preprocessing, not a change to the running small
study, not a new submission, and not measured scalability results.

The independent graph grid stays 16,384 / 65,536 / 262,144 vertices, degree 8,
seed 20260926: 131,072 / 524,288 / 2,097,152 directed edges. Each graph uses the
materializer's **scale 1** and two RDF sources. Applying materializer scale 4 to
the largest graph would incorrectly multiply the already chosen factor again.

`prepare_ch6_d4_recipe.py prepare` writes an immutable recipe; `run` validates it
without execution by default. Only `run --execute` performs preprocessing, and
only inside an explicit CPU allocation and clean checkout matching its commit.
The new recipe does not start method evaluations, make LLM calls, submit Slurm,
or change any old stores. It fails without retries and retains partial outputs.

## Existing interfaces and frozen runtime

The recipe reuses `generate_ch6_synthetic.generate`,
`ch6_materialize.materialize` (the implementation of `materialize_ch6_core.py`),
and `prepare_ch6_core_services.prepare` for RDF-only offline TDB2 loading.
Runtime pins come from the already downloaded Linux service admission, not
new guesses:

- `linux-admission-v4/receipt.json`: `8f470e779c7b91bded8c1cb496497de8d980e40f8c74c0a36b0137f2241af515`
- `linux-runtime-v3/receipt.json`: `1a66283611a50d30c134ce7201777127db61d29874a0c2cf953404c698df6602`
- Java: `90d0a6d25da103678013f193db078b90ed8aeb27b66ebe78e0149616c9c1b811`
- Fuseki: `d28c1eaf703122ee628895a460c20fa4aa60a892f435d403ea8c036f241da1f8`

Paths, trained parent profile and external-runtime pins are recorded in the
recipe. The helper's actual JAR path is `linux-runtime-v3/inputs/fuseki-server.jar`;
its bytes must match the admitted v1 JAR. It is checked before generation.
The existing RDF loader limits are explicit: 10 GiB store allowance per size,
900 seconds per source, 2 GiB Java heap, six-GiB free-space reserve. Materialization
requires 22 GiB free before each size. These are safety bounds, not predicted
space/time usage. Proposed CPU allocation is 8 CPUs / 24 GiB / 2 h, no fixed
node and no GPU. Account quota must actually permit the writes; filesystem free
space is not account quota.

## Minimal execution after review and a new committed revision

Create the recipe outside the checkout, with an unused server output directory:

```bash
PYTHONPATH=src:scripts python scripts/prepare_ch6_d4_recipe.py prepare --output /home/hxc859/xgap-ch6-artifacts/D4-recipe-v1 --source-commit <new-40-character-commit> --remote-output /home/hxc859/xgap-ch6-artifacts/D4-offline-v1
```

Use the returned recipe path and SHA in an independent CPU job:

```bash
PYTHONPATH=src:scripts python scripts/prepare_ch6_d4_recipe.py run --recipe-path /home/hxc859/xgap-ch6-artifacts/D4-recipe-v1/recipe.json --recipe-sha256 <returned-sha256> --execute
```

The job sequence for each size is generation → same-facts materialization → two
independent SQLite references → generic profile publication → offline TDB2 load.
Both reference queries use the same fixed anchor and query text at every size:
ordered direct neighbors, and ordered neighbors with `isMarked=true`. Returned
neighbors may legitimately change because these are independent regular graphs,
not replicas. The two queries only check integration and provide fixed scale
inputs; they are not a replacement for the mixed W1–W4 workload. Generic lowering
may place identity/type access on the control source even without a marked
predicate, so source-count labels must come from actual plans, not these names.

## Concrete remaining gaps

1. Serve copies of these newly sealed stores under the current frozen direct-file
   and lazy-range Jena runtime contract; the offline loader does not do this.
2. Publish actual method input/configuration pins and run graph-backend answer
   checks and measurements. The independent SQL reference is not backend success.
3. The existing `publish_ch6_factor_inputs.py` generates 28 N/u points. Running it
   at every D4 size would conflate a candidate-count sweep with a graph-size sweep;
   it is not the default next step. Freeze a fixed input family/query set for the
   three sizes instead. Reuse N/u publisher only for its separate declared axis.

A necessary tiny test generated 32 vertices / 256 edges, materialized actual RDF
and native-load files, checked the source schema through existing compact
lowering, and compared independent SQL answers to the generator's known neighbor
sets. A second test verified dry-run refusal to execute and the unchanged size
grid. Both passed (0.22 s). Only the tiny test's free-capacity predicate was
mocked; materialization, schema, query lowering and SQL evaluation were real.
No large graph, graph service, model call, remote command or job was run.
