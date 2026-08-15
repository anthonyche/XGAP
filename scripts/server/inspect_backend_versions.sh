#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_SH="$SCRIPT_DIR/common.sh"
# shellcheck source=scripts/server/common.sh
. "$COMMON_SH"

load_env_file
ensure_docker_cmd

print_image_identity() {
  local service="$1"
  local container_id image_id
  container_id="$(compose ps -q "$service")"
  if [ -z "$container_id" ]; then
    echo "$service: container is not running" >&2
    return 1
  fi
  image_id="$("${DOCKER_CMD[@]}" inspect --format '{{.Image}}' "$container_id")"
  echo "$service.container_id=$container_id"
  echo "$service.image_id=$image_id"
  "${DOCKER_CMD[@]}" image inspect "$image_id" \
    --format "$service.repo_digests={{json .RepoDigests}}"
}

print_image_identity neo4j
print_image_identity fuseki

echo "neo4j.backend_version:"
printf '%s\n' \
  'CALL dbms.components() YIELD name, versions, edition RETURN name, versions[0] AS version, edition;' \
  | compose exec -T neo4j cypher-shell \
      -u "${NEO4J_USER:-neo4j}" \
      -p "${NEO4J_PASSWORD:-xgap-lab-password}"

echo "fuseki.container_version_hints:"
compose exec -T fuseki sh -lc \
  'env | grep -E "^(FUSEKI|JENA).*VERSION=" || true; java -version 2>&1 | head -n 1'
