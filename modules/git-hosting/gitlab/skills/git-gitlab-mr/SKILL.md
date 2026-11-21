---
name: git-gitlab-mr
description: >-
  Manages GitLab Merge Requests, review notes and threads, stacked MR target
  retargeting/rebase, and CI/CD pipeline checks using the glab CLI. Use whenever
  creating, inspecting, reviewing, or merging Merge Requests on GitLab.
---

# GitLab Merge Requests & Stacked Merge Playbook

## 1. Opening Merge Requests

- Work on a dedicated branch matching [`.agents/stack-profile.md`](../../stack-profile.md).
- Follow [`.gitlab/merge_request_templates/Default.md`](../../../.gitlab/merge_request_templates/Default.md), including the tracked ticket reference (`{{PR_TICKET_SYNTAX}}`).
- Create the MR using `glab mr create --target-branch main` and monitor [`.gitlab-ci.yml`](../../../.gitlab-ci.yml) pipelines with `glab ci status` and `glab mr view`.

## 2. Independent Final MR Review Comments

- Independent Final Reviewers must post their structured verdict (`APPROVED` or `CHANGES_REQUESTED`) directly on the MR and verify open discussion threads are resolved:
  ```sh
  glab mr note <mr-iid> --message "..."
  ```

## 3. Safe Stacked MR Merge & Rebase Protocol (After Explicit User Approval)

- **Single MR:** Merge only after explicit user approval (`glab mr merge` is gated by `force_ask`):
  ```sh
  glab mr merge <mr-iid> --squash --remove-source-branch
  ```
- **Stacked MR Chain (`main <- MR1 <- MR2`):**
  1. Clean up subagent worktrees first (`manage_subagents({ Action: 'kill_all' })` + `git worktree prune`) so local branch deletion succeeds.
  2. **Before** merging `<parent-mr>` with `--remove-source-branch`, retarget the immediate child MR's target branch to `main` so GitLab does not auto-close it when the parent branch is deleted:
     ```sh
     glab mr update <child-mr-iid> --target-branch main
     ```
  3. Squash-merge `<parent-mr>` (`<old-parent-sha>`), then rebase `<child-branch>` onto `origin/main`:
     ```sh
     git fetch origin
     git checkout <child-branch>
     git rebase --onto origin/main <old-parent-sha> <child-branch>
     git push --force-with-lease origin <child-branch>
     ```
- After merging, sync `main` (`git pull --ff-only origin main`) and prune stale branches (`git fetch --prune origin`).
