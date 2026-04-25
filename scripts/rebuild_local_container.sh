#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${PROJECT_ROOT}/data"
CONFIG_FILE="${DATA_DIR}/config.yaml"
RELAY_MANAGER="${PROJECT_ROOT}/scripts/manage_local_relays.py"
STAMP="$(date +%Y%m%d-%H%M%S)"
CONTAINER_NAME="openai-cpa-local"
IMAGE_NAME="openai-cpa-local:latest"
MOUNT_DOCKER_SOCK="${OPENAI_CPA_MOUNT_DOCKER_SOCK:-1}"
LOCAL_WEB_PORT="${OPENAI_CPA_LOCAL_PORT:-18000}"
PUBLIC_HOST="${OPENAI_CPA_PUBLIC_HOST:-127.0.0.1}"

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

if [[ -f "${RELAY_MANAGER}" ]]; then
  python3 "${RELAY_MANAGER}" restart --project-root "${PROJECT_ROOT}"
fi

"${DOCKER_BIN}" stop -t 15 "${CONTAINER_NAME}" >/dev/null 2>&1 || true

if [[ -f "${CONFIG_FILE}" ]]; then
  cp "${CONFIG_FILE}" "${CONFIG_FILE}.bak-${STAMP}"
fi

"${DOCKER_BIN}" rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
"${DOCKER_BIN}" build -t "${IMAGE_NAME}" .

docker_run_args=(
  run -d
  --name "${CONTAINER_NAME}"
  -p "${LOCAL_WEB_PORT}:8000"
  -e "OPENAI_CPA_PUBLIC_HOST=${PUBLIC_HOST}"
  -e "OPENAI_CPA_PUBLIC_PORT=${LOCAL_WEB_PORT}"
  -e "HOST_PROJECT_PATH=${PROJECT_ROOT}"
  -v "${DATA_DIR}:/app/data"
  --add-host=host.docker.internal:host-gateway
)

if [[ "${MOUNT_DOCKER_SOCK}" != "0" ]]; then
  docker_run_args+=(-v /var/run/docker.sock:/var/run/docker.sock)
fi

docker_run_args+=("${IMAGE_NAME}")

"${DOCKER_BIN}" "${docker_run_args[@]}"
