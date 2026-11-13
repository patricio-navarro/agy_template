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
REGION="${2:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-{{PROJECT_SLUG}}}"
ENV_FILE=".env.${ENV_NAME}"

if [ -z "${PROJECT_ID:-}" ]; then
  RAND_SUFFIX="$(date +%s | tail -c 5)$((RANDOM % 10))"
  PROJECT_ID="{{PROJECT_SLUG}}-${ENV_NAME}-${RAND_SUFFIX}"
fi

echo "============================================="
echo "Provisioning {{PROJECT_NAME}} Infrastructure"
echo "Environment:  $ENV_NAME"
echo "Project ID:   $PROJECT_ID"
echo "Service Name: $SERVICE_NAME"
echo "Region:       $REGION"
echo "Output File:  $ENV_FILE"
echo "============================================="

echo "Enabling required Google Cloud APIs..."
REQUIRED_APIS=(
  artifactregistry.googleapis.com
  cloudbuild.googleapis.com
  run.googleapis.com
  secretmanager.googleapis.com
)
if [ -f "${ROOT_DIR}/firebase.json" ]; then
  REQUIRED_APIS+=(firestore.googleapis.com identitytoolkit.googleapis.com)
fi
gcloud services enable "${REQUIRED_APIS[@]}" --project "$PROJECT_ID" --quiet

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)" --quiet)
CLOUD_RUN_SA="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="$CLOUD_RUN_SA" \
  --role="roles/secretmanager.secretAccessor" \
  --quiet >/dev/null 2>&1 || true

CRON_SECRET_VAL=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))")
SECRET_NAME="${SERVICE_NAME}-cron-secret"

if declare -F sync_secret_manager_secret >/dev/null 2>&1; then
  sync_secret_manager_secret "$PROJECT_ID" "$SECRET_NAME" "$CRON_SECRET_VAL"
  ensure_secret_accessor "$PROJECT_ID" "$SECRET_NAME" "$CLOUD_RUN_SA"
fi

cat > "$ENV_FILE" <<EOF
PROJECT_ID="${PROJECT_ID}"
DEPLOY_REGION="${REGION}"
SERVICE_NAME="${SERVICE_NAME}"
USE_SECRET_MANAGER="true"
CRON_SECRET="${CRON_SECRET_VAL}"
EOF

if [ -f "${ROOT_DIR}/firebase.json" ] && declare -F deploy_firestore_rules_and_indexes >/dev/null 2>&1; then
  DATABASE_ID="${FIREBASE_DATABASE_ID:-{{PROJECT_SLUG}}-${ENV_NAME}-db}"
  echo "FIREBASE_DATABASE_ID=\"${DATABASE_ID}\"" >> "$ENV_FILE"
  deploy_firestore_rules_and_indexes "$PROJECT_ID" "$DATABASE_ID" "$ROOT_DIR" || true
fi

if declare -F configure_artifact_registry_cleanup_policy >/dev/null 2>&1; then
  configure_artifact_registry_cleanup_policy "$PROJECT_ID" "$REGION" "cloud-run-source-deploy"
fi

echo "Provisioning complete. Saved configuration to $ENV_FILE."
