#!/usr/bin/env bash
set -euo pipefail

if ! git diff --cached --name-only --diff-filter=ACM | grep -qx "firestore.rules"; then
  exit 0
fi

if ! grep -qE "rules_version\s*=\s*'2'\s*;" firestore.rules; then
  echo "Error: firestore.rules must declare rules_version = '2';." >&2
  exit 1
fi

if grep -qE "allow\s+(read,\s*write|read|write)\s*:\s*if\s+true\s*;" firestore.rules; then
  echo "Error: Open 'allow ...: if true;' rule detected in firestore.rules." >&2
  exit 1
fi
