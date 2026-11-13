#!/usr/bin/env bash
# scripts/lib-firebase.sh
# Shared DevOps and Firebase automation helper functions for {{PROJECT_NAME}}.

deploy_firestore_rules_and_indexes() {
  local project_id="$1"
  local database_id="$2"
  local root_dir="${3:-$PWD}"

  echo "Deploying Firestore security rules and indexes to database: $database_id..."
  local tmp_fb_config="${TMPDIR:-/tmp}/firebase.deploy.$$.json"
  printf '{"firestore":[{"database":"%s","rules":"%s/firestore.rules","indexes":"%s/firestore.indexes.json"}]}\n' \
    "$database_id" "$root_dir" "$root_dir" > "$tmp_fb_config"

  local firebase_cmd
  if [ -x "${root_dir}/node_modules/.bin/firebase" ]; then
    firebase_cmd=("${root_dir}/node_modules/.bin/firebase")
  elif [ -x "./node_modules/.bin/firebase" ]; then
    firebase_cmd=("./node_modules/.bin/firebase")
  else
    firebase_cmd=(npx -y firebase-tools)
  fi

  local exit_code=0
  "${firebase_cmd[@]}" deploy --config "$tmp_fb_config" --only firestore:rules,firestore:indexes --project "$project_id" --non-interactive || exit_code=$?
  rm -f "$tmp_fb_config" 2>/dev/null || true
  return $exit_code
}

configure_firestore_ttl() {
  local project_id="$1"
  local database_id="$2"
  local collection_group="$3"
  local field_name="$4"

  echo "Configuring Cloud Firestore native TTL policies on '${collection_group}.${field_name}'..."
  local existing_ttls
  existing_ttls=$(gcloud firestore fields ttls list --database="$database_id" --project="$project_id" --format="value(name)" --quiet 2>/dev/null || true)
  if printf '%s\n' "$existing_ttls" | grep -q "/collectionGroups/${collection_group}/fields/${field_name}$"; then
    echo "Firestore TTL on '${collection_group}.${field_name}' is already configured."
  else
    echo "Enabling Firestore TTL on '${collection_group}.${field_name}' (database: $database_id)..."
    gcloud firestore fields ttls update "$field_name" \
      --collection-group="$collection_group" \
      --database="$database_id" \
      --enable-ttl \
      --async \
      --project="$project_id" \
      --quiet >/dev/null 2>&1 || echo "Notice: Firestore TTL operation for '${collection_group}.${field_name}' already in progress or not supported." >&2
  fi
}

configure_artifact_registry_cleanup_policy() {
  local project_id="$1"
  local region="$2"
  local repo_name="${3:-cloud-run-source-deploy}"

  echo "Configuring Artifact Registry cleanup policy on '$repo_name' (keep 10 most recent images)..."
  if ! gcloud artifacts repositories describe "$repo_name" --location="$region" --project="$project_id" --quiet >/dev/null 2>&1; then
    gcloud artifacts repositories create "$repo_name" \
      --repository-format=docker \
      --location="$region" \
      --description="Cloud Run Source Deploy" \
      --project="$project_id" \
      --quiet >/dev/null 2>&1 || true
  fi

  local tmp_ar_policy="${TMPDIR:-/tmp}/ar-cleanup-policy.$$.json"
  cat > "$tmp_ar_policy" <<'EOF'
[
  {
    "name": "delete-old-images",
    "action": { "type": "Delete" },
    "condition": { "tagState": "any" }
  },
  {
    "name": "keep-10-most-recent",
    "action": { "type": "Keep" },
    "mostRecentVersions": { "keepCount": 10 }
  }
]
EOF
  gcloud artifacts repositories set-cleanup-policies "$repo_name" \
    --location="$region" \
    --project="$project_id" \
    --policy="$tmp_ar_policy" \
    --no-dry-run \
    --quiet >/dev/null 2>&1 || echo "Notice: Could not apply Artifact Registry cleanup policy on '$repo_name' (non-fatal)." >&2
  rm -f "$tmp_ar_policy" 2>/dev/null || true
}

sync_secret_manager_secret() {
  local project_id="$1"
  local secret_name="$2"
  local secret_value="$3"

  if [ -z "$secret_value" ]; then
    return 0
  fi

  if gcloud secrets describe "$secret_name" --project "$project_id" --quiet >/dev/null 2>&1 </dev/null; then
    local current_sm_secret
    current_sm_secret=$(gcloud secrets versions access latest --secret="$secret_name" --project="$project_id" --quiet 2>/dev/null || true)
    if [ "$current_sm_secret" != "$secret_value" ]; then
      if printf '%s' "$secret_value" | gcloud secrets versions add "$secret_name" --data-file=- --project="$project_id" --quiet >/dev/null 2>&1; then
        echo "Updated Secret Manager secret '$secret_name'."
      else
        echo "Notice: Could not update Secret Manager secret '$secret_name' (non-fatal)." >&2
      fi
    else
      echo "Secret Manager secret '$secret_name' is already up to date."
    fi
  else
    if printf '%s' "$secret_value" | gcloud secrets create "$secret_name" --data-file=- --replication-policy="automatic" --project "$project_id" --quiet >/dev/null 2>&1; then
      echo "Created Secret Manager secret '$secret_name'."
    else
      echo "Notice: Could not create Secret Manager secret '$secret_name' (non-fatal)." >&2
    fi
  fi
}

ensure_secret_accessor() {
  local project_id="$1"
  local secret_name="$2"
  local member="$3"

  if [ -z "$project_id" ] || [ -z "$secret_name" ] || [ -z "$member" ]; then
    return 0
  fi

  local formatted_member="$member"
  if [[ "$formatted_member" != serviceAccount:* && "$formatted_member" != user:* && "$formatted_member" != group:* ]]; then
    formatted_member="serviceAccount:${formatted_member}"
  fi

  echo "Ensuring secretAccessor role on secret '$secret_name' for $formatted_member..."
  if ! gcloud secrets add-iam-policy-binding "$secret_name" \
    --project="$project_id" \
    --member="$formatted_member" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet >/dev/null 2>&1; then
    echo "Notice: Could not grant 'roles/secretmanager.secretAccessor' on secret '$secret_name' to $formatted_member (non-fatal)." >&2
  fi
}
