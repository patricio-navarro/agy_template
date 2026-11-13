---
name: firestore-security-auditor
description: >-
  Audits firestore.rules for privilege escalation, role bypasses, create vs
  update inconsistencies, missing hasOnly allowlists, type/size limits, and
  multi-tenant isolation gaps. Use whenever reviewing or modifying
  firestore.rules.
---

# Firestore Security Rules Auditor

Run this checklist whenever `firestore.rules` is created, edited, or reviewed:

1. **Deny-by-Default Root:** Confirm a catch-all `match /{document=**} { allow read, write: if false; }` exists and no wildcard `allow read, write: if true;` exists.
2. **Authentication & Tenant Isolation:** Every tenant-scoped path verifies `request.auth != null` and checks tenant membership/role from trusted server-controlled documents or custom claims (never trusting client-supplied `tenantId` or `role` fields without validation).
3. **Create vs Update Invariants:** Verify `update` rules check `affectedKeys().hasOnly(...)` or immutable field equality (`request.resource.data.ownerId == resource.data.ownerId`) so users cannot escalate roles or reassign ownership on update.
4. **Field Allowlists, Types & Size Limits:** Use `keys().hasOnly([...])` / `hasAll([...])`, enforce `is string`, `is int`, `.size() <= ...`, and validate numeric bounds (`>= 0`, `<= max`) to prevent resource exhaustion.
5. **Emulator Proof:** Every rule path and negative security invariant (cross-tenant read/write denial, role escalation denial) must have a corresponding test executed in the local Firestore Emulator.
