---
name: engineering-philosophy
description: >-
  Core software engineering principles (DRY, KISS, YAGNI, CAZZ), pragmatic
  testing requirements, and AI anti-boilerplate discipline. Activate before
  designing, writing, or reviewing code in this repository.
---

# Engineering Philosophy

## Quality Over Quantity

Less code is better code. Every line you do not write is a line that never needs to be debugged, tested, or maintained. Prefer deletions over additions when solving a problem.

## Core Principles

- **DRY — Don't Repeat Yourself:** Every piece of knowledge must have a single, unambiguous representation in the system. If you find yourself writing the same logic twice, extract a clean shared helper.
- **KISS — Keep It Simple, Stupid:** The simplest solution that solves the real problem is the right solution. Complexity is a liability.
- **YAGNI — You Aren't Gonna Need It:** Do not add speculative abstractions, feature flags, or configuration knobs for hypothetical future requirements.
- **CAZZ — Cut All Zombie Zones:** Delete dead code, unused imports, commented-out blocks, stale docs, and orphaned configs without hesitation.

## In Practice

- Favor small, focused functions with shallow nesting and early returns.
- Prefer explicit over implicit, without verbose boilerplate.
- Names should reveal intent; comment the non-obvious *why*, not the *what*.
- Tests are not optional—they are part of the definition of done.
- Leave the codebase cleaner than you found it.

## Testing Philosophy

A feature without a test is not done—it is a bug waiting to fail in production. Think critically about edge cases, failure modes, and security boundaries, and write targeted tests that prove invariants hold.

## For AI Agents

You are an amplifier of the engineer's intent, not a generator of volume. Resist the urge to scaffold unnecessary abstractions or "helpfully" modify unrelated code. Every line of code you write is technical debt unless it solves a verified requirement.
