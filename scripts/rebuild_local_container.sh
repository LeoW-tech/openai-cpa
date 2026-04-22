#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${PROJECT_ROOT}/data"
CONFIG_FILE="${DATA_DIR}/config.yaml"
STAMP="$(date +%Y%m%d-%H%M%S)"
CONTAINER_NAME="openai-cpa-local"
IMAGE_NAME="openai-cpa-local:latest"

find_docker_bin() {
  local candidate=""

  candidate="${OPENAI_CPA_DOCKER_BIN:-}"
  if [[ -n "${candidate}" ]]; then
    if [[ -x "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
    return 1
  fi

  candidate="$(command -v docker 2>/dev/null || true)"
  if [[ -n "${candidate}" && -x "${candidate}" ]]; then
    printf '%s\n' "${candidate}"
    return 0
  fi

  for candidate in /opt/homebrew/bin/docker /usr/local/bin/docker; do
    if [[ -x "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  return 1
}

if ! DOCKER_BIN="$(find_docker_bin)"; then
  cat >&2 <<'EOF'
[ERROR] 未找到 docker 命令。
[ERROR] 请先确认当前 mac 本地环境满足以下条件：
[ERROR] 0. 如果你手动设置了 OPENAI_CPA_DOCKER_BIN，请确认它指向一个可执行文件
[ERROR] 1. 已安装 Homebrew Docker CLI
[ERROR] 2. 当前 shell 已加载 Homebrew 环境（建议在 ~/.zprofile 中加入：eval "$(/opt/homebrew/bin/brew shellenv)"）
[ERROR] 3. Colima 已启动，可执行：colima status
[ERROR] 4. command -v docker 可返回：/opt/homebrew/bin/docker
EOF
  exit 127
fi

cd "${PROJECT_ROOT}"

mkdir -p "${DATA_DIR}"

"${DOCKER_BIN}" stop -t 15 "${CONTAINER_NAME}" >/dev/null 2>&1 || true

if [[ -f "${CONFIG_FILE}" ]]; then
  cp "${CONFIG_FILE}" "${CONFIG_FILE}.bak-${STAMP}"
fi

"${DOCKER_BIN}" rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
"${DOCKER_BIN}" build -t "${IMAGE_NAME}" .
"${DOCKER_BIN}" run -d \
  --name "${CONTAINER_NAME}" \
  -p 8000:8000 \
  -v "${DATA_DIR}:/app/data" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --add-host=host.docker.internal:host-gateway \
  "${IMAGE_NAME}"
