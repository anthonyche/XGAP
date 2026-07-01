#!/usr/bin/env bash

XGAP_SERVER_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
XGAP_DEFAULT_REPO_ROOT="$(cd "$XGAP_SERVER_SCRIPT_DIR/../.." && pwd)"

REPO_ROOT="${XGAP_REPO_ROOT:-$XGAP_DEFAULT_REPO_ROOT}"
COMPOSE_FILE="${XGAP_COMPOSE_FILE:-$REPO_ROOT/services/docker-compose.yml}"
ENV_FILE="${XGAP_ENV_FILE:-$REPO_ROOT/services/.env}"

DOCKER_CMD=()

ensure_env_file() {
  if [ ! -f "$ENV_FILE" ]; then
    cp "$REPO_ROOT/services/.env.example" "$ENV_FILE"
    echo "Created $ENV_FILE from .env.example"
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
