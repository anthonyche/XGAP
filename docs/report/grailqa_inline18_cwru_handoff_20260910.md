# Fixed-v1 inline18 real-service handoff

The locally accepted producer is
`6b32b973d4fd1a979b714570d3edcd2e684c1b07`, pushed successfully to the existing
`codex/m13e4-grailqa-semantic-paper-protocol` branch. D200 acceptance is
184 focused tests, 2700 passed / 37 skipped in the full suite, harness and
19 examples. This handoff is not a submitted job or model result.

The prepared operator package is
`/Users/anthonyche/Developer/XGAP-deliverables/xgap-inline18-6b32b97.zip`
(6,237 bytes, SHA-256
`fe56a9323d93f2f8a386b637f2511359a825d5b2502d30b9884b1f5df46525cc`).
It contains `submit.sh`, `audit.sh`, `README.md`, and `verification.json`.
Shell syntax and embedded Python parse checks pass; exact frozen spec/commit,
single submission site and input-pin-before-submission order were checked.
The ZIP was reread and its entries compared with the prepared files. These
checks do not claim that the operator scripts have run on CWRU.

Upload the ZIP to `/home/hxc859` and run once in the existing OnDemand terminal:

```bash
unzip -n ~/xgap-inline18-6b32b97.zip -d ~ && bash ~/xgap-inline18-6b32b97/submit.sh
```

The helper creates `/home/hxc859/XGAP-inline18-6b32b97`, clones the existing
branch and detaches at the exact accepted producer. It does not switch the old
checkout. It validates the preserved v1 catalog, checks development18 readiness,
and saves the catalog manifest digest and actual tokenizer identity outside
the run before submitting. The model revision is pinned from the existing
shared cache. No catalog build or model download is performed.

The existing guarded Slurm entrypoint requests one H100, 8 CPUs, 64 GB, and a
four-hour ceiling. The frozen inline spec retains 18 questions, Top-20 retrieval,
Top-4 prompt candidates, three proposals and at most one repair per question.
Bounds remain 36 generation attempts and 36 tokenizer probes, with startup
health observations accounted separately. There is no graph execution or
full150 authorization in this development run.

Submission intent, stdout, stderr and exit code are retained in the package.
The helper never retries. An existing checkout or prior attempt causes it to
stop. Do not delete partial output merely to rerun it.

After the job is COMPLETED / 0:0, run:

```bash
bash ~/xgap-inline18-6b32b97/audit.sh
```

This reads that job's current scheduler state and invokes the accepted D200
entrypoint using prelaunch pins. Tokenizer files/template/library identity must
still match the prelaunch identity. Results are written outside the original
run to `~/xgap-inline18-6b32b97/audit/whole_run_evidence.json`. A complete job
may still have zero useful candidates; report all 18 outcomes and their costs.

## Why a server-side action is currently required

The browser inventory shows authenticated OnDemand pages, but control of both
dedicated shells and the existing file page times out before content/actions.
The alternate provider-ID lookup returned tab-not-found. A single noninteractive
SSH attempt with strict host verification and no configuration change timed
out connecting to Pioneer port 22. No server command, upload or job submission
occurred. This is not evidence of expired credentials and does not justify
asking the user to log in again. User authorization for uploads and reading
results remains valid; the missing capability is a functioning control route.

## Independent answer-execution work

Do not wait by extending D200 or rebuilding the unchanged catalog. The current
`parquet_row_to_triple` adapter intentionally retains URI objects and
language-tagged literals only; it drops ordinary and datatype-bearing literals
to match the historical catalog parser. It cannot be reused unchanged as a
complete fact loader for numeric/year/date constraints. The next target-data
implementation needs a separately selected typed fact reader, preservation of
RDF identity through dataset-owned Neo4j/Fuseki encodings, and execution of
generated queries with independent answer checks. Existing catalog and frozen
semantic-only experiment behavior must remain unchanged. Selecting facts from
gold references or answers remains forbidden.
