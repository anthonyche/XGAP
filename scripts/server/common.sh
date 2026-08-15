#!/usr/bin/env bash

XGAP_SERVER_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
XGAP_DEFAULT_REPO_ROOT="$(cd "$XGAP_SERVER_SCRIPT_DIR/../.." && pwd)"

REPO_ROOT="${XGAP_REPO_ROOT:-$XGAP_DEFAULT_REPO_ROOT}"
COMPOSE_FILE="${XGAP_COMPOSE_FILE:-$REPO_ROOT/services/docker-compose.yml}"
PAPER_ENVIRONMENT="${XGAP_PAPER_ENV:-0}"
if [ "$PAPER_ENVIRONMENT" = "1" ]; then
  ENV_FILE="${XGAP_ENV_FILE:-$REPO_ROOT/services/.env.paper}"
  ENV_EXAMPLE="$REPO_ROOT/services/.env.paper.example"
else
  ENV_FILE="${XGAP_ENV_FILE:-$REPO_ROOT/services/.env}"
  ENV_EXAMPLE="$REPO_ROOT/services/.env.example"
fi

DOCKER_CMD=()

ensure_env_file() {
  if [ ! -f "$ENV_FILE" ]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    echo "Created $ENV_FILE from $(basename "$ENV_EXAMPLE")"
  fi
}

require_paper_image_digests() {
  if [ "$PAPER_ENVIRONMENT" != "1" ]; then
    return 0
  fi
  load_env_file
  local invalid=0
  for variable in NEO4J_IMAGE FUSEKI_IMAGE; do
    local value="${!variable:-}"
    if [[ ! "$value" =~ @sha256:[0-9a-fA-F]{64}$ ]]; then
      echo "$variable must be a repository@sha256:<64-hex-digest> reference in paper mode." >&2
      invalid=1
    fi
  done
  if [ "$invalid" -ne 0 ]; then
    echo "Fill $ENV_FILE from the currently validated server images before paper startup." >&2
    exit 1
  fi
}

ensure_docker_cmd() {
  if [ "${#DOCKER_CMD[@]}" -gt 0 ]; then
    return 0
  fi

  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    DOCKER_CMD=(docker)
    return 0
  fi

  if command -v sudo >/dev/null 2>&1 && command -v docker >/dev/null 2>&1; then
    if sudo -n docker info >/dev/null 2>&1; then
      DOCKER_CMD=(sudo docker)
      return 0
    fi

    if [ -t 0 ]; then
      echo "Docker requires elevated permission; trying sudo docker."
      if sudo docker info >/dev/null 2>&1; then
        DOCKER_CMD=(sudo docker)
        return 0
      fi
    fi
  fi

  echo "Docker is required, but this user cannot access the Docker daemon." >&2
  echo "Either run with sudo-capable access or add the user to the docker group." >&2
  exit 1
}

compose() {
  ensure_env_file
  ensure_docker_cmd
  require_paper_image_digests

  if "${DOCKER_CMD[@]}" compose version >/dev/null 2>&1; then
    "${DOCKER_CMD[@]}" compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
    return
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    if docker-compose version >/dev/null 2>&1; then
      docker-compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
      return
    fi
    if command -v sudo >/dev/null 2>&1 && sudo -n docker-compose version >/dev/null 2>&1; then
      sudo docker-compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
      return
    fi
  fi

  echo "Docker Compose is required." >&2
  exit 1
}

load_env_file() {
  ensure_env_file
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
}
