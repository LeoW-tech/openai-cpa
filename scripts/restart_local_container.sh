#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTAINER_NAME="openai-cpa-local"
RELAY_MANAGER="${PROJECT_ROOT}/scripts/manage_local_relays.py"

cd "${PROJECT_ROOT}"

if [[ -f "${RELAY_MANAGER}" ]]; then
  python3 "${RELAY_MANAGER}" restart --project-root "${PROJECT_ROOT}"
fi

docker restart "${CONTAINER_NAME}"
