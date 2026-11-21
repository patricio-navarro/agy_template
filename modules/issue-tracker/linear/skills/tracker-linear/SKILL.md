---
name: tracker-linear
description: >-
  Manages Linear issues, cycles, projects, deduplication, branch/commit key
  conventions ({{LINEAR_TEAM_KEY}}-<num>), and post-merge status transitions via
  Linear MCP or the Linear GraphQL API. Use whenever inspecting, creating,
  updating, or closing Linear issues.
---

# Linear Playbook (`{{LINEAR_TEAM_KEY}}`)

## 1. Single Source of Truth

- Track all projects, cycles, features, bugs, and audit findings in Linear team **`{{LINEAR_TEAM_KEY}}`** via Linear MCP (`https://mcp.linear.app/mcp`), Linear GraphQL API (`https://api.linear.app/graphql`), or configured Linear CLI tooling (never local `tickets/*.md` files).
- Inspect the target issue (`{{LINEAR_TEAM_KEY}}-123`) and its comments before starting implementation, and update its acceptance criteria or comments if scope changes.

## 2. Issue Deduplication (Skeptical Ticket Validation)

- Before filing audit or refactoring issues, search open and recently completed issues in team `{{LINEAR_TEAM_KEY}}` (including full descriptions and comments) via Linear MCP or GraphQL issue search.
- Fold overlapping minor findings into existing open issues as comments instead of creating duplicates.

## 3. Branch, Commit & PR/MR Linkage

- **Branch Naming:** `feature/{{LINEAR_TEAM_KEY}}-<num>-<short-slug>` or `fix/{{LINEAR_TEAM_KEY}}-<num>-<short-slug>`.
- **Commit Messages:** Include `{{LINEAR_TEAM_KEY}}-<num>` (enforced by `.githooks/commit-msg` on `feat`, `fix`, and `refactor` commits), e.g., `feat({{LINEAR_TEAM_KEY}}-123): add request validation`.
- **Pull / Merge Requests:** Include `{{LINEAR_TEAM_KEY}}-<num>` (or `Closes {{LINEAR_TEAM_KEY}}-<num>` for auto-linking) in the PR/MR title and description.

## 4. Post-Merge Hygiene

- After a PR/MR merges to `main`, verify `{{LINEAR_TEAM_KEY}}-<num>` transitions to `Done`, post a concise delivery summary comment with the PR/MR link and verification results, and update any unblocked downstream issues.
