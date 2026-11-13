---
name: parallel-pr-orchestrator
description: >-
  Orchestrates multi-issue feature and tech-debt backlogs in parallel using
  isolated git worktrees (Workspace: 'share'), persistent track workers
  (Model: 'inherit'), conflict-free stacked PR chains, and independent PR
  reviewers. Use when executing multiple tickets in parallel or overnight batch
  mode.
---

# Parallel & Stacked PR Orchestrator Playbook

Use this skill to execute multiple tracked tickets autonomously, producing **1 focused Pull Request per ticket** with **zero merge conflicts**, **independent multi-agent PR reviews**, and **strict worktree isolation**.

---

## Core Architecture & Non-Negotiable Guardrails

1. **Model Inheritance (`Model: 'inherit'`):**
   - The **Coordinator** (main conversation) plans dependency waves, tracks branch stacks, and coordinates handoffs.
   - Omit `Model` (leaving `Model: 'inherit'`) on every **Worker** (`TypeName: 'self'`), **Evaluator / Independent Reviewer** (`TypeName: 'research'` or `'self'`), and specialist subagent so they inherit the active session model.
2. **Strict Git Isolation (`Workspace: 'share'`) & Persistent Track Workers:**
   - Launch parallel Worker subagents with `Workspace: 'share'` so each track runs in an isolated git worktree sharing the `.git` object store.
   - **Reuse 1 Persistent Worker per Track:** For a sequential stacked track $S = [T_1, T_2, \dots, T_k]$, spawn **one** Worker for $T_1$ and advance that same subagent through $T_2 \dots T_k$ via `send_message` to preserve warm context and avoid redundant worktrees.
   - Cap concurrency at **3–4 simultaneous Worker subagents** to avoid CPU/RAM exhaustion during builds and test suites.
   - Respect all **Single-Concurrency Locks** declared in [`.agents/stack-profile.md`](../../stack-profile.md) (e.g., only 1 subagent at a time may run local database/emulator tests).
3. **1 Ticket = 1 Stacked PR (Zero Merge Conflicts):**
   - **Across Parallel Tracks:** Concurrent tracks **MUST** own strictly disjoint files. No file may be modified by two active tracks.
   - **Within a Track (Stacked PRs):** Dependent tickets run sequentially:
     - $T_1$ branches from `origin/main` and targets `--base main`.
     - After $T_1$'s PR is open and `APPROVED`, $T_2$ branches from `origin/<branch-1>` and targets `--base <branch-1>`.
     - Never amend or force-push a parent branch after a child branch has been created from it.
4. **Hard Prohibitions:**
   - **NEVER merge any PR** (`gh pr merge`, `bkt pr merge`, `git merge` into `main`, or `git push origin main`).
   - **NEVER deploy to Sandbox or Production** inside parallel worker subagents.

---

## Phase 1: Ticket Triage & Disjoint Stack Planning

1. Fetch open target tickets using the active **Issue Tracker** skill.
2. Partition tickets into **Disjoint Parallel Tracks** ($1 \dots N$) where no two tracks touch the same files. Order tickets within each track from foundational (schema, security rules, shared types, services) to surface-level (endpoints, UI, docs).
3. Create a live tracking artifact (`pr_batch_dashboard.md`) in the conversation artifact directory listing Ticket, Track, Base Branch, Head Branch, PR URL, Verification Status, and Independent Review Verdict.

---

## Phase 2: Scoped Worker Subagent Execution (`Workspace: 'share'`)

Instruct each persistent Track Worker to:
1. Read [`.agents/skills/engineering-philosophy/SKILL.md`](../engineering-philosophy/SKILL.md) and [`.agents/stack-profile.md`](../../stack-profile.md), plus the full ticket details.
2. Fetch and checkout a clean stacked branch:
   ```sh
   git fetch origin
   git checkout -B <branch-name-from-stack-profile> origin/<base-branch>
   ```
3. Modify **only** files authorized for its track; reuse existing shared helpers (**DRY**); write or update unit/integration tests.
4. Run all verification commands from [`.agents/stack-profile.md`](../../stack-profile.md) using compact output flags, then verify clean scope via `git status --short` and `git diff --name-only origin/<base-branch>...HEAD`.
5. Commit with a Conventional Commit referencing the ticket ID, push to `origin`, and open a Pull Request against `<base-branch>` using the active **Git Hosting** skill (with a Stack Navigation Header at the top of the PR body: ``> **Stacked PR Chain:** `main` ← ... ← **<TICKET> (this PR)**``).

---

## Phase 3: Right-Sized Review, In-Place Fixes & Independent Approval

When a Worker reports an open PR:
- **Tier 1 ($\le 3$ production files, no new API endpoints or security/infra rules):** Spawn 1 **Independent Final PR Reviewer** (`TypeName: 'self'`, `Model: 'inherit'`) directly.
- **Tier 2 ($\ge 4$ production files, new API endpoints, or security/infra rules):** Spawn 2–3 parallel read-only `research` Evaluators matching [`.agents/stack-profile.md`](../../stack-profile.md), message the persistent Track Worker via `send_message` to apply fixes in-place and push, then spawn 1 **Independent Final PR Reviewer** (`Model: 'inherit'`).
- The Independent Reviewer posts its structured review + explicit `APPROVED` or `CHANGES_REQUESTED` verdict on the PR. Advance to $T_{k+1}$ only after $T_k$ is `APPROVED`.

---

## Phase 4: Combined Sandbox Verification & Safe Stacked Merge Guide

1. **Combined Sandbox Verification (If Cloud Module Active & Requested):**
   Combine all disjoint track head branches into a temporary local verification branch without touching `main`:
   ```sh
   git fetch origin
   git checkout -B sandbox/verify-batch origin/main
   git merge --no-edit origin/<track-1-head> ... origin/<track-N-head>
   ```
   Deploy to Sandbox once, verify, and return to `main`.
2. **Safe Stacked Merge & Rebase Protocol (When User Approves Merge):**
   - **Step 0 — Clean Up Subagent Worktrees:** Run `manage_subagents({ Action: 'kill_all' })` and `git worktree prune` so local branch deletions succeed.
   - **Step 1 — Retarget Child PRs Before Deleting Parent Branches:** **NEVER** squash-merge and delete a parent branch while a child PR still targets `<parent-branch>`, as Git hosting platforms may auto-close the child PR. Retarget the immediate child PR's base/destination to `main` **first** using the active **Git Hosting** skill.
   - **Step 2 — Rebase Child Branch After Squash-Merge:** Once parent PR $P_1$ (old head SHA `<old-p1-sha>`) is squash-merged to `main`, rebase the child branch onto `origin/main` so pre-squash ancestor commits do not conflict:
     ```sh
     git fetch origin
     git checkout <child-branch>
     git rebase --onto origin/main <old-p1-sha> <child-branch>
     git push --force-with-lease origin <child-branch>
     ```
