#!/usr/bin/env bash
set -euo pipefail

USER_NAME="${USER:-$(id -un)}"
GROUP_NAME="$(id -gn)"
DATA_ROOT="${XGAP_SERVER_DATA_ROOT:-/data/$USER_NAME/xgap-artifacts}"
LINK_PATH="${XGAP_DATA_LINK:-$HOME/xgap-data}"

if ! mkdir -p "$DATA_ROOT" 2>/dev/null; then
  if [ -z "${XGAP_SERVER_DATA_ROOT:-}" ] && command -v sudo >/dev/null 2>&1; then
    echo "Creating $DATA_ROOT requires elevated permission; trying sudo."
    if ! sudo install -d -o "$USER_NAME" -g "$GROUP_NAME" "$DATA_ROOT"; then
      echo "Could not create the XGAP data directory: $DATA_ROOT" >&2
      exit 1
    fi
  else
    cat >&2 <<EOF
Cannot create the XGAP data directory: $DATA_ROOT

Create it once with elevated permission, then rerun this script:
  sudo install -d -o '$USER_NAME' -g '$GROUP_NAME' '$DATA_ROOT'
EOF
    exit 1
  fi
fi

mkdir -p "$(dirname "$LINK_PATH")"
if [ -L "$LINK_PATH" ]; then
  CURRENT_TARGET="$(readlink "$LINK_PATH")"
  if [ "$CURRENT_TARGET" != "$DATA_ROOT" ]; then
    echo "Existing data link points elsewhere: $LINK_PATH -> $CURRENT_TARGET" >&2
    echo "Expected target: $DATA_ROOT" >&2
    exit 1
  fi
elif [ -e "$LINK_PATH" ]; then
  echo "Cannot create data link because this path already exists: $LINK_PATH" >&2
  echo "Move that path aside or set XGAP_DATA_LINK to a new location." >&2
  exit 1
else
  ln -s "$DATA_ROOT" "$LINK_PATH"
fi

mkdir -p "$LINK_PATH/grailqa-m13d-v1"

echo "XGAP server data storage is ready."
echo "physical_root=$DATA_ROOT"
echo "home_link=$LINK_PATH"
echo "artifact_cache=$LINK_PATH/grailqa-m13d-v1"
