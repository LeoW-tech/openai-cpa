#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTAINER_NAME="openai-cpa-local"

cd "${PROJECT_ROOT}"

docker restart "${CONTAINER_NAME}"
