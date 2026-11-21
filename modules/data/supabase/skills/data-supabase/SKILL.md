---
name: data-supabase
description: >-
  Enforces Supabase Auth verification, PostgreSQL Row-Level Security (RLS)
  policy auditing, declarative SQL migrations, and local Supabase CLI
  workflows. Use whenever authoring Supabase migrations, RLS policies, Auth
  checks, Edge Functions, or database client code.
---

# Supabase Auth, RLS & Migrations Playbook

## 1. Auth & Key Isolation

- **Never Expose `SUPABASE_SERVICE_ROLE_KEY`:** Keep `service_role` (or `sb_secret_...`) keys strictly in server-side/Edge Function environments. Only `SUPABASE_URL` and `SUPABASE_ANON_KEY` (publishable key) may be exposed to browser or mobile clients.
- **Verify Users Server-Side:** In backend services and server-rendered routes, verify incoming tokens with `supabase.auth.getUser()` (or verified JWT signature + `aud`/`exp` checks) rather than trusting client-supplied `user_id` fields or unverified `getSession()` cookies.

## 2. Row-Level Security (RLS) Auditing Checklist

Audit every migration that creates or alters tables, views, or functions in `public` or any PostgREST-exposed schema:

1. **Mandatory RLS Enablement:** Every exposed table must execute `ALTER TABLE <schema>.<table> ENABLE ROW LEVEL SECURITY;`. Never disable RLS on user/tenant tables or add permissive `USING (true)` policies for `anon` or `authenticated` write paths.
2. **Explicit Per-Command Policies:** Define separate `SELECT`, `INSERT`, `UPDATE`, and `DELETE` policies scoped explicitly `TO authenticated` (or `TO anon` only when intentionally public). Avoid `FOR ALL` unless every command has identical `USING` and `WITH CHECK` invariants.
3. **Anti-Escalation `WITH CHECK` & Immutability:**
   - Every `INSERT` and `UPDATE` policy must include an explicit `WITH CHECK (...)` verifying ownership/tenant membership (`(select auth.uid()) = user_id` or membership subquery).
   - Prevent privilege escalation on `UPDATE` by ensuring immutable columns (`user_id`, `tenant_id`, `role`) cannot be reassigned to another user/tenant or elevated.
4. **Performance & Indexing:** Wrap `auth.uid()` and `auth.jwt()` inside scalar subqueries (`(select auth.uid())`) so PostgreSQL evaluates them once per statement (`initPlan`) rather than per row, and index all columns referenced in policy predicates (`user_id`, `tenant_id`).
5. **Views & `SECURITY DEFINER` Functions:** Set `WITH (security_invoker = true)` on PostgreSQL views exposed to PostgREST. Any `SECURITY DEFINER` helper used by policies must set `SET search_path = ''`, qualify all schema objects (`public.memberships`), and revoke unnecessary `EXECUTE` privileges from `PUBLIC`, `anon`, and `authenticated`.

## 3. Migrations & Local CLI Workflow

- **Local Development Loop:**
  ```sh
  supabase start
  supabase migration new <descriptive_name>
  # Author idempotent, transactional SQL in supabase/migrations/<timestamp>_<name>.sql
  supabase db reset
  supabase test db
  ```
- **Clean Replay Invariant:** Every PR touching `supabase/migrations/` or `supabase/seed.sql` must replay from a clean slate (`supabase db reset`) and pass pgTAP/integration RLS tests proving both authorized access and cross-tenant/anonymous denial.
- **Production & Linked Guards:** Never run `supabase db push` (without previewing `--dry-run` first) or `supabase db reset --linked` without explicit human confirmation.
- **Concurrency Lock:** Only **one** subagent at a time may run `supabase start`, `supabase stop`, `supabase db reset`, or `supabase test db` on the local Docker stack.
