#!/usr/bin/env bash
set -euo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Avoid duplicate tsc run if frontend-react-vite already ran it
if [[ -f "${HOOK_DIR}/20-frontend-check.sh" ]]; then
  exit 0
fi

STAGED_TS=$(git diff --cached --name-only --diff-filter=ACM | grep -E '\.(ts|tsx)$' || true)
if [[ -z "$STAGED_TS" ]]; then
  exit 0
fi

if [[ -f "tsconfig.json" && -x "node_modules/.bin/tsc" ]]; then
  npx --no-install tsc --noEmit
fi
