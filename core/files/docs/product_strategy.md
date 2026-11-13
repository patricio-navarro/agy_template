# Product Strategy & Phased Execution Plan — {{PROJECT_NAME}}

This document defines the product boundaries and **Business YAGNI** guardrails enforced by [`.agents/skills/product-strategy-gate/SKILL.md`](../.agents/skills/product-strategy-gate/SKILL.md).

---

## 1. Mission & Target Positioning

- **Target Ideal Customer Profile (ICP):** *(Define who this application serves and what problem it eliminates.)*
- **Core Value Proposition:** *(Define the primary differentiator and what complexity you deliberately refuse to build.)*
- **North Star Metric:** *(Define the measurable outcome that proves traction.)*

---

## 2. Unit Economics & Cost Guardrails

- **Infrastructure Cost Target per Active Tenant/User:** *(e.g., keep variable cloud/API cost bounded via caching, rate limits, and batching.)*
- **Operational Overhead Rule:** *(e.g., self-serve workflows requiring zero manual support intervention.)*

---

## 3. 4-Phase Execution Gates

| Gate | Scope | Rule |
| :--- | :--- | :--- |
| **Gate 1: Core Trust & Onboarding** | Auth, primary user journey, security boundaries, observability | **Must ship before external launch.** |
| **Gate 2: Monetization / Value Capture** | Self-serve billing, quotas, webhooks, customer portal | **Must ship before scaling acquisition.** |
| **Gate 3: Scalable Acquisition** | Referral loops, SEO/integrations, analytics funnel | **Activate after Gate 1–2 are live.** |
| **Gate 4: Post-Traction Expansion** | Advanced retention, multi-platform clients, enterprise features | **Strictly deferred until Gate 3 traction is proven.** |
