#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${PROJECT_ROOT}/data"
CONFIG_FILE="${DATA_DIR}/config.yaml"
STAMP="$(date +%Y%m%d-%H%M%S)"
CONTAINER_NAME="openai-cpa-local"
IMAGE_NAME="openai-cpa-local:latest"

cd "${PROJECT_ROOT}"

mkdir -p "${DATA_DIR}"

if [[ -f "${CONFIG_FILE}" ]]; then
  cp "${CONFIG_FILE}" "${CONFIG_FILE}.bak-${STAMP}"
fi

docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
docker build -t "${IMAGE_NAME}" .
docker run -d \
  --name "${CONTAINER_NAME}" \
  -p 8000:8000 \
  -v "${DATA_DIR}:/app/data" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --add-host=host.docker.internal:host-gateway \
  "${IMAGE_NAME}"
