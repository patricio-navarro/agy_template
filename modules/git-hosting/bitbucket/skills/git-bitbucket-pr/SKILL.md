---
name: git-bitbucket-pr
description: >-
  Manages Bitbucket Cloud/Data Center Pull Requests, review comments, stacked
  PR destination retargeting/rebase, and Bitbucket Pipelines checks via bkt CLI
  or Bitbucket REST API v2.0. Use whenever creating, reviewing, updating, or
  merging Pull Requests on Bitbucket.
---

# Bitbucket Pull Requests & Stacked Merge Playbook

## 1. Opening Pull Requests

- Work on a dedicated branch matching [`.agents/stack-profile.md`](../../stack-profile.md).
- Follow [`.bitbucket/pull_request_template.md`](../../../.bitbucket/pull_request_template.md), including the tracked ticket reference (`{{PR_TICKET_SYNTAX}}`).
- Create the PR using `bkt` (Bitbucket CLI) or Bitbucket REST API v2.0 (`POST /2.0/repositories/{workspace}/{repo_slug}/pullrequests`).

## 2. Independent Final PR Review Comments

- Independent Final PR Reviewers must post their structured verdict (`APPROVED` or `CHANGES_REQUESTED`) directly on the PR via `bkt pr comment` or `POST /2.0/repositories/{workspace}/{repo_slug}/pullrequests/{id}/comments`.

## 3. Safe Stacked PR Merge & Rebase Protocol (After Explicit User Approval)

- **Single PR:** Squash-merge via `bkt` or Bitbucket UI/REST API with source branch deletion.
- **Stacked PR Chain (`main <- PR1 <- PR2`):**
  1. Clean up subagent worktrees first (`manage_subagents({ Action: 'kill_all' })` + `git worktree prune`).
  2. **Before** merging and deleting `<parent-branch>`, retarget the immediate child PR's destination branch to `main` via Bitbucket UI, `bkt`, or `PUT /2.0/repositories/{workspace}/{repo_slug}/pullrequests/{child_id}` (`{"destination": {"branch": {"name": "main"}}}`).
  3. After squash-merging `<parent-pr>` (`<old-parent-sha>`), rebase `<child-branch>` onto `origin/main`:
     ```sh
     git fetch origin
     git checkout <child-branch>
     git rebase --onto origin/main <old-parent-sha> <child-branch>
     git push --force-with-lease origin <child-branch>
     ```
- After merging, sync `main` (`git pull --ff-only origin main`) and prune stale branches (`git fetch --prune origin`).
