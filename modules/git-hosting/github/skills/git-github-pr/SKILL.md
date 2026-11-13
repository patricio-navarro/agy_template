---
name: git-github-pr
description: >-
  Manages GitHub Pull Requests, review comments, stacked PR retargeting/rebase,
  and branch cleanup using the gh CLI. Use whenever creating, reviewing,
  updating, or merging Pull Requests on GitHub.
---

# GitHub Pull Requests & Stacked Merge Playbook

## 1. Opening Pull Requests

- Work on a dedicated branch matching [`.agents/stack-profile.md`](../../stack-profile.md).
- Open PRs using `gh pr create` following [`.github/pull_request_template.md`](../../../.github/pull_request_template.md), including the ticket linkage (`{{PR_TICKET_SYNTAX}}`) and matching labels/milestones when applicable.

## 2. Independent Final PR Review Comments

- Independent Final PR Reviewers must post their structured verdict (`APPROVED` or `CHANGES_REQUESTED`) directly on the PR:
  ```sh
  gh pr comment <pr-number> --body "..."
  ```

## 3. Safe Stacked PR Merge & Rebase Protocol (After Explicit User Approval)

- **Single PR:** Merge via `gh pr merge <pr> --squash --delete-branch`.
- **Stacked PR Chain (`main <- PR1 <- PR2`):**
  1. Clean up subagent worktrees first (`manage_subagents({ Action: 'kill_all' })` + `git worktree prune`) so local branch deletion succeeds.
  2. **Before** merging `<parent-pr>` with `--delete-branch`, retarget the immediate child PR to `main` so GitHub does not auto-close the child PR when the parent branch is deleted:
     ```sh
     gh pr edit <child-pr> --base main
     ```
  3. Squash-merge `<parent-pr>` (`<old-parent-sha>`), then rebase `<child-branch>` onto `origin/main`:
     ```sh
     git fetch origin
     git checkout <child-branch>
     git rebase --onto origin/main <old-parent-sha> <child-branch>
     git push --force-with-lease origin <child-branch>
     ```
- After merging, sync `main` (`git pull --ff-only origin main`) and prune stale branches (`git fetch --prune origin`).
