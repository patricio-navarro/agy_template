#!/usr/bin/env bash
set -euo pipefail

STAGED_PY=$(git diff --cached --name-only --diff-filter=ACM | grep -E '\.py$' || true)
if [[ -z "$STAGED_PY" ]]; then
  exit 0
fi

if command -v ruff >/dev/null 2>&1; then
  # shellcheck disable=SC2086
  ruff check $STAGED_PY
fi
