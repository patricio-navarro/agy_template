---
name: learn
description: >-
  Persist reusable behaviors, user corrections, architectural constraints, or
  troubleshooting fixes from the current session into repository rules
  (AGENTS.md) or modular skills (.agents/skills/<name>/SKILL.md). Use when the
  user runs /learn or asks to codify a lesson from the conversation.
---

# Continuous Learning Workflow (`/learn`)

Use this workflow to turn a session correction, recurring gotcha, or newly discovered invariant into durable repository guidance without bloating `AGENTS.md`.

## Step 1: Identify What to Learn

1. Scan recent user corrections or constraints (e.g., *"no"*, *"instead"*, *"always do X first"*, *"never do Y"*).
2. Isolate the root cause and the exact verified command, guardrail, or pattern that resolved it.
3. If the session produced no new reusable lesson, explain briefly and stop.

## Step 2: Classify Rule vs. Skill (Protect Context Budget)

- **Always-On Rule (`AGENTS.md`):** Only for universal invariants or a 1-line pointer to a skill. Keep `AGENTS.md` concise.
- **Modular Skill (`.agents/skills/<skill-name>/SKILL.md`):** For multi-step workflows, CLI conventions, domain checks, or troubleshooting runbooks that should load on demand.
- **Deterministic Guard (`.agents/hooks/guard_rules.json` or `.githooks/`):** Prefer deterministic hook rules over prose prompts whenever a rule can be enforced mechanically (e.g., blocking forbidden commands or link patterns).

## Step 3: Update Existing Before Creating New (DRY)

Inspect `AGENTS.md` and existing `.agents/skills/*/SKILL.md` files first. Update an existing skill or rule whenever the lesson extends an existing domain; create a new skill only for a genuinely distinct workflow.

## Step 4: Proposal & Approval Gate

**Do not edit rule or skill files until the user confirms.** Present:
1. **Session Takeaway:** What failed or was corrected, and why.
2. **Target & Rationale:** Rule vs. Skill vs. Hook, and why updating vs. creating.
3. **Proposed Diff:** Exact diff to apply.

Apply the edits only after explicit user approval.
