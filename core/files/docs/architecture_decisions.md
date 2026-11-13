# Architecture Decision Records (ADRs) — {{PROJECT_NAME}}

Record significant architectural choices here so human engineers and AI agents understand *why* boundaries exist before modifying them.

---

## ADR-001: Modular Governance & Quality-Gate Harness

- **Status:** Accepted
- **Context:** AI coding agents degrade in accuracy when loaded with irrelevant skills, stale task markdown, or unchecked self-reviews.
- **Decision:** Keep `AGENTS.md` as a concise router, load domain workflows lazily via `.agents/skills/*/SKILL.md`, enforce mechanical invariants via `.agents/hooks.json` and `.githooks/*`, and require independent PR review via `pr-quality-gate`.
- **Consequences:** All non-trivial PRs pass deterministic verification and independent evaluation before merge.

---

## ADR-002: *(Template — Replace or Append New ADRs)*

- **Status:** Proposed
- **Context:** *(What forces or constraints motivate this decision?)*
- **Decision:** *(What concrete choice was made?)*
- **Consequences:** *(Trade-offs, operational requirements, and invariants to preserve.)*
