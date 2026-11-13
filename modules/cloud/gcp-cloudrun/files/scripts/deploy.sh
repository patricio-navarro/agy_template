#!/usr/bin/env bash
set -euo pipefail
export CLOUDSDK_CORE_DISABLE_PROMPTS=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

if [ -f "${SCRIPT_DIR}/lib-firebase.sh" ]; then
  # shellcheck source=scripts/lib-firebase.sh
  . "${SCRIPT_DIR}/lib-firebase.sh"
fi

ENV_NAME="${1:-sandbox}"
ENV_FILE=".env.${ENV_NAME}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Error: $ENV_FILE not found. Generate it with ./scripts/provision.sh $ENV_NAME" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

if [ -z "${PROJECT_ID:-}" ]; then
  echo "Error: PROJECT_ID is not defined in $ENV_FILE" >&2
  exit 1
fi

DEPLOY_REGION="${DEPLOY_REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-{{PROJECT_SLUG}}}"
MIN_INSTANCES="${MIN_INSTANCES:-0}"
MAX_INSTANCES="${MAX_INSTANCES:-$([ "$ENV_NAME" = "production" ] && echo 5 || echo 2)}"
CONCURRENCY="${CONCURRENCY:-80}"
MEMORY="${MEMORY:-512Mi}"
CPU="${CPU:-1}"
USE_SECRET_MANAGER="${USE_SECRET_MANAGER:-false}"
SECRET_NAME="${SERVICE_NAME}-cron-secret"

if [ "$USE_SECRET_MANAGER" = "true" ] || gcloud secrets describe "$SECRET_NAME" --project="$PROJECT_ID" --quiet >/dev/null 2>&1 </dev/null; then
  USE_SECRET_MANAGER="true"
elif [ -z "${CRON_SECRET:-}" ]; then
  echo "Error: CRON_SECRET missing in $ENV_FILE and '$SECRET_NAME' not found in Secret Manager" >&2
  exit 1
fi

echo "============================================="
echo "{{PROJECT_NAME}} Cloud Run Deployment"
echo "Environment:   $ENV_NAME"
echo "Project ID:    $PROJECT_ID"
echo "Service:       $SERVICE_NAME"
echo "Region:        $DEPLOY_REGION"
echo "Instances:     $MIN_INSTANCES..$MAX_INSTANCES"
echo "============================================="

REQUIRED_APIS=(artifactregistry.googleapis.com cloudbuild.googleapis.com run.googleapis.com)
ENABLED_APIS=$(gcloud services list --enabled --project "$PROJECT_ID" --format="value(config.name)" --quiet 2>/dev/null || true)
MISSING_APIS=()
for api in "${REQUIRED_APIS[@]}"; do
  if ! printf '%s\n' "$ENABLED_APIS" | grep -qx "$api"; then
    MISSING_APIS+=("$api")
  fi
done
if [ "${#MISSING_APIS[@]}" -gt 0 ]; then
  gcloud services enable "${MISSING_APIS[@]}" --project "$PROJECT_ID" --quiet
fi

if [ -f "${ROOT_DIR}/firebase.json" ] && declare -F deploy_firestore_rules_and_indexes >/dev/null 2>&1; then
  TARGET_DB="${FIREBASE_DATABASE_ID:-{{PROJECT_SLUG}}-db}"
  deploy_firestore_rules_and_indexes "$PROJECT_ID" "$TARGET_DB" "$ROOT_DIR"
fi

BASE_ENV_VARS="APP_ENV=$ENV_NAME,PROJECT_ID=$PROJECT_ID"
if [ -n "${APP_URL:-}" ]; then
  BASE_ENV_VARS="$BASE_ENV_VARS,APP_URL=$APP_URL"
fi
if [ "$USE_SECRET_MANAGER" != "true" ]; then
  BASE_ENV_VARS="$BASE_ENV_VARS,CRON_SECRET=$CRON_SECRET"
fi

DEPLOY_CMD=(
  gcloud run deploy "$SERVICE_NAME"
  --source .
  --region "$DEPLOY_REGION"
  --allow-unauthenticated
  --min-instances "$MIN_INSTANCES"
  --max-instances "$MAX_INSTANCES"
  --concurrency "$CONCURRENCY"
  --memory "$MEMORY"
  --cpu "$CPU"
  --project "$PROJECT_ID"
  --set-env-vars "$BASE_ENV_VARS"
  --quiet
)

if [ "$USE_SECRET_MANAGER" = "true" ]; then
  DEPLOY_CMD+=(--set-secrets="CRON_SECRET=${SECRET_NAME}:latest")
fi

"${DEPLOY_CMD[@]}"

if declare -F configure_artifact_registry_cleanup_policy >/dev/null 2>&1; then
  configure_artifact_registry_cleanup_policy "$PROJECT_ID" "$DEPLOY_REGION" "cloud-run-source-deploy"
fi

echo "Deployment finished for $ENV_NAME ($SERVICE_NAME)."
