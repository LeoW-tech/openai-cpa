#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_BRANCH="upstream-main"

cd "${PROJECT_ROOT}"

git fetch upstream --prune --tags

if git show-ref --verify --quiet "refs/heads/${TARGET_BRANCH}"; then
  git branch -f "${TARGET_BRANCH}" upstream/main
else
  git branch --track "${TARGET_BRANCH}" upstream/main
fi

git push origin "${TARGET_BRANCH}:${TARGET_BRANCH}"
