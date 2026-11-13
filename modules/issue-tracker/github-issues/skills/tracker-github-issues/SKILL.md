---
name: tracker-github-issues
description: >-
  Manages epics, milestones, issues, deduplication, and post-merge ticket
  hygiene using GitHub Issues via the gh CLI. Use whenever inspecting,
  creating, updating, or closing tickets.
---

# GitHub Issues & Milestones Playbook

## 1. Single Source of Truth

- Track all Epics, features, bugs, and audit findings in **GitHub Milestones & Issues** via `gh issue` (do not create local `tickets/*.md` files).
- Before implementing work, inspect the issue (`gh issue view <id> --comments`) or create one with matching `epic:*` labels and Milestone.

## 2. Skeptical Deduplication

- Before filing audit or refactoring issues, inspect full bodies and comments of open issues (`gh issue list --state open --json number,title,body`) and recent closed issues (`gh issue list --state closed --limit 30`).
- Fold overlapping minor findings into existing open issues (`gh issue comment <id>`) instead of creating duplicates.

## 3. Branch, PR & Post-Merge Hygiene

- Work on `feature/issue-<id>-<short-slug>` or `fix/issue-<id>-<short-slug>`.
- Include `Closes #<id>` in the PR description.
- After merging a PR to `main`, post a concise delivery summary (`gh issue comment <id>`), update affected downstream open issues (`gh issue edit`), and close any Milestone with `0` remaining open issues.
