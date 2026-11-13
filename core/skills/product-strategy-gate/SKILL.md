---
name: product-strategy-gate
description: >-
  Enforces alignment with the project's Product Strategy, Target ICP, Unit
  Economics, and Phased Go-To-Market (GTM) Gates (docs/product_strategy.md).
  Use whenever evaluating feature ideas, prioritizing backlog tickets, or
  running a Post-Feature-Wave CTO/PO review.
---

# Product Strategy & Business YAGNI Gate

Before proposing new features, filing enhancement tickets, modifying pricing/quota logic, or running a Post-Feature-Wave architecture review, read [`docs/product_strategy.md`](../../../docs/product_strategy.md) and apply these guardrails.

---

## When to Trigger

1. **Feature Ideation & Ticket Creation:** Before opening new enhancement/feature tickets.
2. **Post-Feature-Wave Audit & CTO Review:** Alongside [`pr-quality-gate`](../pr-quality-gate/SKILL.md) (Step 7) to filter proposals through **Business YAGNI**.
3. **Phase-Gate Transitions:** When checking if the active GTM/delivery gate in [`docs/product_strategy.md`](../../../docs/product_strategy.md) is complete before unlocking later-stage scope.

---

## Core Guardrails

1. **Core Positioning & Simplicity Rule:** Reject features that violate the product's primary value proposition, introduce unnecessary operational support overhead, or bloat the user workflow beyond the target persona defined in `docs/product_strategy.md`.
2. **Active Phase-Gate Enforcement (Business YAGNI):** Only build features required by the currently active Execution Gate in `docs/product_strategy.md`. Defer valid later-stage ideas explicitly instead of building them prematurely.
3. **Unit Economics & Cost-Per-Tenant Guardrail:** Reject architectures that introduce unbounded polling, N+1 queries, un-capped external API fan-out, or infrastructure cost spikes misaligned with the project's unit economics target.

---

## Verdict Taxonomy

Classify every reviewed proposal with one explicit **Strategy Alignment Verdict**:
- **`Aligned — Active Gate`:** Directly advances the active Execution Gate without violating positioning or unit economics.
- **`Defer — Later Gate`:** Valuable future capability, but blocked until earlier gates ship.
- **`Reject — Scope Bloat / Violates Positioning`:** Adds complexity, support burden, or cost outside the product's mission.
