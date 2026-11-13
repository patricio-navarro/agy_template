---
name: template-initializer
description: >-
  Programmatically initializes a forked agy_template repository for a chosen
  tech stack (frontend, backend, data, cloud, issue tracker, and git hosting)
  and prunes all unused skills, hooks, CI pipelines, and template scaffolding.
  Use when the user asks to configure, initialize, set up, or clean up this
  template for their new application.
---

# Template Initializer Runbook

Follow these steps whenever a user asks to set up or clean up `agy_template` for their new project.

## 1. Discover Available Modules

Run the catalog discovery command to inspect exact category rules, module IDs, and required/optional parameters:

```sh
./agy-init --list-modules --json
```

## 2. Map User Intent to Stack Flags

Match the user's request against the discovered module IDs:
- `--project-name "<Name>"` (optional `--project-slug "<slug>"`)
- `--frontend <id|none>` (e.g., `react-vite-ts`, `none`)
- `--backend <id|none>` (e.g., `python-fastapi`, `node-express-ts`, `none`)
- `--data <id[,id...]|none>` (multi-select allowed, e.g., `firebase`, `none`)
- `--cloud <id|none>` (e.g., `gcp-cloudrun`, `none`)
- `--issue-tracker <id>` (e.g., `github-issues`, `jira`)
- `--git-hosting <id>` (e.g., `github`, `bitbucket`)
- `--param KEY=VALUE` for module parameters (e.g., `--param JIRA_PROJECT_KEY=ACME` or `--jira-key ACME`)

If any required choice is missing or ambiguous (for example, whether they have a frontend or prefer a specific Jira project key), ask a brief clarifying question before executing.

## 3. Preview Before Pruning

Run a dry-run first to inspect the exact files, skills, hooks, CI configuration, and cleanup targets:

```sh
./agy-init \
  --project-name "<Name>" \
  --frontend <frontend> \
  --backend <backend> \
  --data <data> \
  --cloud <cloud> \
  --issue-tracker <tracker> \
  --git-hosting <git> \
  --dry-run
```

## 4. Execute Programmatic Cleanup & Verify

Run `./agy-init ... --yes` to generate the tailored governance harness and prune `modules/`, `core/`, `tests/`, `agy-init`, and this bootstrap skill atomically.

After execution:
1. Verify `.agy-manifest.json` and `AGENTS.md` exist at the repository root.
2. Confirm `git config --get core.hooksPath` reports `.githooks` (when inside a git repository).
3. Summarize the active skills, hooks, CI pipeline, and next steps (e.g., filling `.env.example` -> `.env` or running cloud provisioning scripts if enabled).
