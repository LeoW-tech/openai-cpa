#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTAINER_NAME="openai-cpa-local"
RELAY_MANAGER="${PROJECT_ROOT}/scripts/manage_local_relays.py"
LOCAL_WEB_PORT="${OPENAI_CPA_LOCAL_PORT:-18000}"

cd "${PROJECT_ROOT}"

if [[ -f "${RELAY_MANAGER}" ]]; then
  python3 "${RELAY_MANAGER}" restart --project-root "${PROJECT_ROOT}"
fi

if docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
  current_host_port="$(docker inspect -f '{{(index (index .NetworkSettings.Ports "8000/tcp") 0).HostPort}}' "${CONTAINER_NAME}" 2>/dev/null || true)"
  if [[ "${current_host_port}" != "${LOCAL_WEB_PORT}" ]]; then
    exec "${PROJECT_ROOT}/scripts/rebuild_local_container.sh"
  fi
fi

docker restart "${CONTAINER_NAME}"
