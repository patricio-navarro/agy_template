# Infrastructure & DevOps — {{PROJECT_NAME}}

## Environments

| Environment | Env File (Git-Ignored) | Purpose |
| :--- | :--- | :--- |
| **Sandbox** | `.env.sandbox` | Pre-merge verification of Cloud Run, secrets, and integrations. |
| **Production** | `.env.production` | Live customer environment; deploy only after explicit approval. |

## Scripts

- `./scripts/provision.sh <sandbox|production> [region]` — Enables required Google Cloud APIs, provisions Secret Manager secrets, configures least-privilege IAM, and writes `.env.<env>`.
- `./scripts/deploy.sh <sandbox|production>` — Performs fast-path API verification, deploys Firestore rules if present, builds and deploys to Google Cloud Run (`{{PROJECT_SLUG}}`), and enforces Artifact Registry image retention.
