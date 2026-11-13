---
name: cloud-gcp-cloudrun
description: >-
  Guides Google Cloud Run provisioning, Secret Manager integration,
  Sandbox/Production environment parity, and atomic deployment via
  scripts/provision.sh and scripts/deploy.sh. Use whenever changing cloud
  infrastructure, deployment scripts, secrets, or environment variables.
---

# Google Cloud Run Playbook

## 1. Environment Parity (`sandbox` vs `production`)

- Keep `.env.sandbox` and `.env.production` strictly untracked locally; only `.env.example` belongs in Git.
- Provision new environments idempotently with `./scripts/provision.sh <sandbox|production> [region]`.
- Never merge a feature to `main` if it relies on manual Google Cloud Console changes not yet codified in `scripts/provision.sh` and `scripts/deploy.sh`.

## 2. Secret Manager & Least-Privilege IAM

- Store sensitive runtime secrets (`{{PROJECT_SLUG}}-cron-secret`, API keys) in **Google Cloud Secret Manager** and mount them via `--set-secrets`, granting `roles/secretmanager.secretAccessor` exclusively to the Cloud Run runtime service account.
- Use fast-path API enablement (`gcloud services list --enabled`) in deploy scripts to avoid redundant long-running operations.

## 3. Atomic Deployment Guardrails

- Because `gcloud run deploy --source .` archives the current working directory, always run `git checkout <target-branch> && ./scripts/deploy.sh sandbox` as a single atomic command in the main turn.
- **Never** run `./scripts/deploy.sh sandbox` or `./scripts/deploy.sh production` inside parallel worker subagents.
- Deploying to `production` requires explicit user approval.
