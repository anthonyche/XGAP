# Backend Environment Setup

This document describes how to prepare a GPU/server machine to run the
two graph backends used for XGAP backend experiments:

- Neo4j, exposed on ports `7474` and `7687`;
- Apache Jena Fuseki, exposed on port `3030`.

This setup is environment scaffolding only. It does not implement an
XGAP compiler, planner, semantic-deviation layer, ontology reasoning,
LLM planning, or KGQA evaluation.

## Server Layout

The server scripts default to the repository checkout that contains the
script you run. If the repo is cloned at `/home/chl/XGAP`, that path is
used automatically.

```text
/home/chl/XGAP
```

You normally do not need environment variables. If you intentionally
keep the repo elsewhere, override `XGAP_REPO_ROOT`:

```bash
export XGAP_REPO_ROOT=/home/chl/XGAP
```

## Clone The Repo

On the server:

```bash
cd ~
git clone <repo-url> XGAP
cd XGAP
```

## Configure Environment Variables

Bootstrap creates `services/.env` from `services/.env.example` if it is
missing:

```bash
bash scripts/server/bootstrap_xgap_lab.sh
```

The bootstrap script no longer creates `/xgap-lab`. It uses the current
repo path by default, so running it from `/home/chl/XGAP` keeps all
repository-relative paths under `/home/chl/XGAP`.

Review `services/.env` before exposing the services beyond a trusted
lab network. The default credentials are intentionally simple:

```text
NEO4J_USER=neo4j
NEO4J_PASSWORD=xgap-lab-password
FUSEKI_ADMIN_USER=admin
FUSEKI_ADMIN_PASSWORD=xgap-lab-password
```

`services/.env` is the development configuration and may use floating image
tags. A paper run must instead use `services/.env.paper`, created from
`services/.env.paper.example`, with both images filled from the CURRENT
validated containers as `repository@sha256:<digest>`. The repository does not
guess or upgrade those versions.

## Start Backends

```bash
bash scripts/server/start_backends.sh
bash scripts/server/healthcheck_backends.sh
```

For a frozen paper deployment, first capture and review the current identities:

```bash
bash scripts/server/inspect_backend_versions.sh

NEO4J_IMAGE_ID="$(sudo docker inspect --format '{{.Image}}' xgap-neo4j)"
FUSEKI_IMAGE_ID="$(sudo docker inspect --format '{{.Image}}' xgap-fuseki)"
sudo docker image inspect "$NEO4J_IMAGE_ID" --format '{{json .RepoDigests}}'
sudo docker image inspect "$FUSEKI_IMAGE_ID" --format '{{json .RepoDigests}}'
```

Fill the paper environment from the matching repository digests:

```bash
NEO4J_PIN="$(sudo docker image inspect "$NEO4J_IMAGE_ID" --format '{{range .RepoDigests}}{{println .}}{{end}}' | awk '/(^|\/)neo4j@sha256:/ {print; exit}')"
FUSEKI_PIN="$(sudo docker image inspect "$FUSEKI_IMAGE_ID" --format '{{range .RepoDigests}}{{println .}}{{end}}' | awk '/(^|\/)stain\/jena-fuseki@sha256:/ {print; exit}')"
test -n "$NEO4J_PIN" && test -n "$FUSEKI_PIN"
cp services/.env.paper.example services/.env.paper
printf '\nNEO4J_IMAGE=%s\nFUSEKI_IMAGE=%s\n' "$NEO4J_PIN" "$FUSEKI_PIN" >> services/.env.paper
```

Use that configuration without pulling or upgrading an image:

```bash
XGAP_PAPER_ENV=1 bash scripts/server/start_backends.sh
XGAP_PAPER_ENV=1 bash scripts/server/healthcheck_backends.sh
```

If the current user cannot access `/var/run/docker.sock`, the server
scripts automatically fall back to `sudo docker` and may ask for your
sudo password. To avoid sudo prompts permanently, add the user to the
Docker group on the server and log in again:

```bash
sudo usermod -aG docker "$USER"
```

Expected healthcheck success:

- Docker Compose lists `xgap-neo4j` and `xgap-fuseki`.
- Neo4j accepts `cypher-shell` queries over Bolt.
- Neo4j HTTP on `http://127.0.0.1:7474/` is reported when reachable,
  but it is not used as the blocking readiness signal.
- `http://127.0.0.1:3030/$/ping` responds for Fuseki.

If a container keeps restarting, inspect logs:

```bash
bash scripts/server/log_backends.sh neo4j
bash scripts/server/log_backends.sh fuseki
```

Neo4j load and smoke scripts stream local `.cypher` files into
`cypher-shell`; the repository dataset directory is not mounted into the
Neo4j import directory. This avoids Neo4j startup ownership changes on
read-only host files.

## Load Toy Financial-Risk Data

The toy dataset is in `examples/financial_risk/`.

```bash
bash scripts/server/load_financial_risk_neo4j.sh
bash scripts/server/load_financial_risk_fuseki.sh
```

The Fuseki data includes reified Transfer records for the native smoke query
and a direct `transfersTo` predicate for the bounded M9 path fragment. Both are
intentional. The DatasetBundle backend mapping owns the RDF IRI contract.

Inspect the actual financial-risk predicates loaded into Fuseki:

```bash
curl -fsS -G \
  -H 'Accept: application/sparql-results+json' \
  --data-urlencode 'query=SELECT DISTINCT ?p WHERE { ?s ?p ?o FILTER(STRSTARTS(STR(?p), "http://xgap.example.org/financial-risk/")) } ORDER BY ?p' \
  'http://127.0.0.1:3030/xgap/sparql'
```

Run the static three-way data/mapping/M9 audit:

```bash
PYTHONPATH=src python -m xgap.experiments.backend_mapping_audit \
  --dataset datasets/financial_risk_dev
```

Success reports no mismatches and, for example, identical `URI_data`,
`URI_mapping`, and `URI_m9` values for `TRANSFER`.

The dataset models Alice, her account, several companies, company
accounts, and transfer records. It is designed to support:

```text
Find high-risk companies connected to Alice by recent transfers.
```

## Run Smoke Queries

```bash
bash scripts/server/smoke_neo4j.sh
bash scripts/server/smoke_fuseki.sh
```

Success means both smoke scripts print at least one expected high-risk
company. The expected toy-data results include:

- `Redstone Analytics`
- `BlackPeak Trading`

## Run Python Smoke Harness

After the shell smoke queries pass, the Python experiment harness can
record normalized run outputs. The harness reads `services/.env` if it
exists and uses exported environment variables as overrides.

Install test dependencies before running pytest on a fresh server clone:

```bash
python -m pip install --user -e ".[test]"
```

The two direct harness commands below do not require pytest; they only
need the repository source on `PYTHONPATH`.

```bash
XGAP_RUN_BACKENDS=1 python -m pytest tests/test_backend_live.py
PYTHONPATH=src python -m xgap.experiments.backend_smoke --backend neo4j
PYTHONPATH=src python -m xgap.experiments.backend_smoke --backend fuseki
```

Success means each harness command writes:

- `runs/<run_id>/query_logs.jsonl`
- `runs/<run_id>/results/<backend>_financial_risk_toy_smoke_results.json`

The normalized result rows contain:

- `company`
- `amount`
- `currency`
- `occurred_on`

## Stop Or Reset

Stop containers without deleting data:

```bash
bash scripts/server/stop_backends.sh
```

Delete containers and persistent volumes:

```bash
bash scripts/server/reset_backends.sh
```

The reset script asks for confirmation. To use it in disposable CI or a
throwaway lab, pass:

```bash
bash scripts/server/reset_backends.sh --yes
```

## Default Tests

Live Neo4j and Fuseki services are not required by default pytest. The
backend environment and infrastructure records are checked by unit
tests. Live backend smoke tests run only when `XGAP_RUN_BACKENDS=1`.

After loading the updated data, run the M9-generated expected-nonempty
calibration sanity and paper readiness checks:

```bash
XGAP_RUN_BACKENDS=1 XGAP_RUN_CALIBRATION=1 PYTHONPATH=src \
python -m pytest tests/test_m12c_live.py -v

set -a
. services/.env.paper
set +a
PYTHONPATH=src python -m xgap.experiments.readiness \
  --config experiments/matrices/financial_risk_pilot.json \
  --check-backends

XGAP_RUN_BACKENDS=1 PYTHONPATH=src \
python -m pytest tests/test_backend_live.py -v
```

The calibration live test compiles through M9 and asserts `row_count > 0`
only for the controlled cases listed as expected-nonempty. A successful empty
result remains valid for other queries.

Any M12-C calibration produced before the mapping hardening is retained only
as historical development evidence. Regenerate the canonical development D0
after reloading the RDF data; paper readiness checks the mapping hash embedded
in its Fuseki query artifacts.
