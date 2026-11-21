#!/usr/bin/env bash
set -euo pipefail

STAGED_TS=$(git diff --cached --name-only --diff-filter=ACM | grep -E '\.(ts|tsx)$' || true)
if [[ -z "$STAGED_TS" ]]; then
  exit 0
fi

if [[ -f "tsconfig.json" && -x "node_modules/.bin/tsc" ]]; then
  npx --no-install tsc --noEmit
fi
