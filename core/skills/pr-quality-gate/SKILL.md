---
name: pr-quality-gate
description: >-
  Mandatory pre-merge quality gate, right-sized multi-agent code review,
  disjoint refactoring orchestration, documentation and skeptical ticket
  validation, and post-feature-wave CTO architecture review. Use before marking
  any Pull Request ready to merge or when auditing a feature wave.
---

# PR Quality Gate & Multi-Agent Review Playbook

Before requesting user approval to merge any non-trivial Pull Request, execute this end-to-end quality gate using the active stack configuration in [`.agents/stack-profile.md`](../../stack-profile.md).

---

## Step 1: Stack Pre-Flight & Domain Standards Check

Read [`.agents/stack-profile.md`](../../stack-profile.md) to identify:
- Active **Verification Commands**
- Active **Domain Skills** (e.g., frontend accessibility/mobile checks, backend API contracts, data security rules)
- Active **Issue Tracker** and **Git Hosting** skills

If a frontend module is active and the branch touches UI/client files, run the active frontend skill's accessibility, semantic HTML, and mobile viewport checks first.

---

## Step 2: Right-Sized Independent Domain Evaluators

- **Small / Single-Domain PRs ($\le 3$ production files, no new API endpoints or security/infra rule changes):**
  Skip Steps 2–3 and proceed directly to **Step 4** (full verification + 1 Independent Final PR Reviewer).
- **Multi-Domain PRs ($\ge 4$ production files, new API endpoints, or security/infra rule changes):**
  Spawn **parallel read-only `research` subagents** (omitting `Model` so they inherit the active session model), partitioned by the **Domain Evaluators** listed in [`.agents/stack-profile.md`](../../stack-profile.md).
  Instruct every evaluator to read [`.agents/skills/engineering-philosophy/SKILL.md`](../engineering-philosophy/SKILL.md) first and audit its domain against **DRY**, **KISS**, **YAGNI**, **CAZZ**, security boundaries, and test quality, returning findings categorized by **High / Medium / Low** severity with exact `file:line` references.

---

## Step 3: Applying Refactorings (In-Turn First, Disjoint Subagents When Large)

Synthesize evaluator findings into a concrete refactoring plan:
- **Default (Standard Branches):** Apply fixes directly in the main execution turn to avoid unnecessary subagent overhead.
- **Large Multi-Domain Fixes:** Spawn `self` refactoring subagents in parallel (omitting `Model`) **only** when fixes span large, strictly disjoint file sets:
  - **Rule of Disjoint Ownership:** Never assign the same file to two concurrent refactoring subagents. Update shared contracts/types before spawning parallel workers.
  - Instruct refactoring subagents **not** to run `git commit` or `git push`—only edit their assigned files and run targeted tests.

---

## Step 4: Verification, Independent Final PR Reviewer & Pre-Merge Gate

1. **In-Turn Regression Verification:**
   Run every verification command declared in [`.agents/stack-profile.md`](../../stack-profile.md) using compact output flags (respecting any single-concurrency locks such as local emulators). All checks must pass with 0 errors.
2. **Independent Final PR Reviewer (`research` or `self` subagent, `Model: 'inherit'`):**
   Spawn 1 fresh reviewer subagent (never the author) to inspect the full branch diff against `main` (or the stacked base branch) against **DRY**, **KISS**, **YAGNI**, **CAZZ**, security, and tests. It must return an explicit `APPROVED` or `CHANGES_REQUESTED` verdict and post its summary on the PR via the active **Git Hosting** skill.
3. **Sandbox Verification (When Cloud Module Is Active):**
   Deploy to Sandbox from a clean atomic checkout (skipping pure documentation/skill-only PRs) and verify health endpoints and live behavior.
4. **Pre-Merge Production Readiness & Follow-Up Gate:**
   - **Zero Unautomated Manual Steps:** Never merge to `main` if the PR relies on manual cloud/database console configuration not yet codified in provisioning/deploy scripts and active in both Sandbox and Production.
   - **Documentation Sync:** Ensure architectural or user-facing changes update `docs/*.md` in the PR or a tracked `Documentation` ticket.
5. **Post-Merge Lifecycle (Only After Explicit User Approval):**
   - Merge via the active **Git Hosting** skill (for stacked PR chains, follow the safe retarget + rebase protocol in [`parallel-pr-orchestrator`](../parallel-pr-orchestrator/SKILL.md)).
   - Post a concise delivery summary on the linked ticket via the active **Issue Tracker** skill, update affected downstream tickets, close completed milestones/epics, and prune merged branches (`git fetch --prune origin`).

---

## Step 5: Batch / Stacked PR Mode

When orchestrating multiple tickets in parallel or stacked PR chains, follow [`.agents/skills/parallel-pr-orchestrator/SKILL.md`](../parallel-pr-orchestrator/SKILL.md).

---

## Step 6: Documentation & Skeptical Ticket Validation Gate

When authoring repository docs or generating audit/refactoring backlog tickets:
1. **Committed Markdown Hygiene:** Never write machine-local `file:///...` links in committed `.md` files (use portable relative links). Use valid Mermaid syntax (quote labels containing parentheses/brackets and use `<br/>` instead of `\n`). Reference symbol names instead of volatile line numbers, and keep one canonical section per topic (**DRY**).
2. **Deduplicate First:** Read full bodies and comments of open tickets and recent closed tickets in the active **Issue Tracker** before proposing new tickets.
3. **Skeptical Ticket Validators (`research` subagents, `Model: 'inherit'`):** Verify every candidate finding against `git ls-files`, `git log`, actual compiler/test output, reachability guards, and **DRY**/**KISS**/**YAGNI**/**CAZZ**.
   - **Valid -> Small-PR Ticket:** File 1 focused ticket per cohesive concern with `file:line` evidence.
   - **Overlap -> Enrich Existing Ticket:** Comment on the existing open ticket rather than creating a conflicting duplicate.
   - **Invalid / YAGNI / High-Churn -> Discard:** Drop false positives and speculative churn.

---

## Step 7: Post-Feature-Wave Multi-Agent Audit & CTO Architecture Review

After shipping a major wave of features (4+ PRs across domains):
1. **Phase 1 — Parallel Domain Experts:** Inspect existing open/closed tickets, then spawn parallel read-only `research` subagents matching the **Domain Evaluators** in [`.agents/stack-profile.md`](../../stack-profile.md) covering 100% of `git ls-files`.
2. **Phase 2 — CTO Architecture Review:** Adjudicate every proposal against [`engineering-philosophy`](../engineering-philosophy/SKILL.md) and [`product-strategy-gate`](../product-strategy-gate/SKILL.md) into a **Master Decision Matrix**:
   - `Implement Now (Bug / Security / CAZZ)`
   - `Implement Now (High-ROI DRY / KISS Refactor)`
   - `Implement If / When Extending <Ticket>`
   - `Discard (YAGNI / Premature Abstraction / High Churn)`
3. **Phase 3 — Disjoint Bundling:** Group `Implement Now` items into small, 100% file-disjoint backlog tickets and fold `Implement If Extending` notes into their target open tickets.
