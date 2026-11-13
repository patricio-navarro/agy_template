---
name: tracker-jira
description: >-
  Manages Jira Epics, Stories, Bugs, JQL deduplication, branch/commit key
  conventions ({{JIRA_PROJECT_KEY}}-<num>), and post-merge transitions via
  Atlassian MCP, acli, or Jira REST API v3. Use whenever inspecting, creating,
  updating, or transitioning Jira tickets.
---

# Atlassian Jira Playbook (`{{JIRA_PROJECT_KEY}}`)

## 1. Single Source of Truth

- Track all Epics, Stories, Bugs, and audit findings in Jira project **`{{JIRA_PROJECT_KEY}}`** via Atlassian MCP (`mcp.atlassian.com`), `acli`, or Jira REST API v3 (never local `tickets/*.md` files).
- Inspect the target ticket before starting implementation and update its acceptance criteria or comments if scope changes.

## 2. JQL Deduplication (Skeptical Ticket Validation)

- Before filing audit or refactoring tickets, query open and recently resolved tickets in `{{JIRA_PROJECT_KEY}}` (including full descriptions and comments) via JQL:
  `project = {{JIRA_PROJECT_KEY}} AND statusCategory != Done ORDER BY updated DESC`
- Fold overlapping minor findings into existing open tickets via a Jira comment instead of creating duplicates.

## 3. Branch, Commit & PR Linkage

- **Branch Naming:** `feature/{{JIRA_PROJECT_KEY}}-<num>-<short-slug>` or `fix/{{JIRA_PROJECT_KEY}}-<num>-<short-slug>`.
- **Commit Messages:** Include `{{JIRA_PROJECT_KEY}}-<num>` (enforced by `.githooks/commit-msg` on `feat`, `fix`, and `refactor` commits), e.g., `feat({{JIRA_PROJECT_KEY}}-101): add request validation`.
- **Pull Requests:** Include `{{JIRA_PROJECT_KEY}}-<num>` in the PR title and body.

## 4. Post-Merge Hygiene

- After a PR merges to `main`, transition `{{JIRA_PROJECT_KEY}}-<num>` to `Done` (or your board's final status), post a concise delivery summary comment with PR link and verification results, and update any blocked downstream tickets.
