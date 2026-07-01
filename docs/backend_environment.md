# Backend Environment Setup

This document describes how to prepare a GPU/server machine to run the
two graph backends used for XGAP backend experiments:

- Neo4j, exposed on ports `7474` and `7687`;
- Apache Jena Fuseki, exposed on port `3030`.

This setup is environment scaffolding only. It does not implement an
XGAP backend adapter, capability profile, protocol layer, descriptor
manager, planner, semantic-deviation layer, ontology reasoning, LLM
planning, or KGQA evaluation.

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

## Start Backends

```bash
bash scripts/server/start_backends.sh
bash scripts/server/healthcheck_backends.sh
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
- `http://127.0.0.1:7474/` responds for Neo4j.
- `http://127.0.0.1:3030/$/ping` responds for Fuseki.

## Load Toy Financial-Risk Data

The toy dataset is in `examples/financial_risk/`.

```bash
bash scripts/server/load_financial_risk_neo4j.sh
bash scripts/server/load_financial_risk_fuseki.sh
```

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
backend environment is checked through shell syntax validation and by
running the scripts on the target server.
