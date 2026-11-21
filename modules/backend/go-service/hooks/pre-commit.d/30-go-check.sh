#!/usr/bin/env bash
set -euo pipefail

STAGED_GO=$(git diff --cached --name-only --diff-filter=ACM | grep -E '\.go$' || true)
if [[ -z "$STAGED_GO" ]]; then
  exit 0
fi

if command -v gofmt >/dev/null 2>&1; then
  UNFORMATTED=""
  while IFS= read -r file; do
    [[ -f "$file" ]] || continue
    if [[ -n "$(gofmt -l "$file")" ]]; then
      UNFORMATTED+="$file"$'\n'
    fi
  done <<< "$STAGED_GO"
  if [[ -n "$UNFORMATTED" ]]; then
    echo "Error: The following Go files are not gofmt-formatted:" >&2
    printf '%s' "$UNFORMATTED" >&2
    echo "Run 'gofmt -w' on these files before committing." >&2
    exit 1
  fi
fi
