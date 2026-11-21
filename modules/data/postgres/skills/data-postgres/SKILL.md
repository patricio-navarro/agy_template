---
name: data-postgres
description: >-
  Enforces PostgreSQL schema design, parameterized queries, transactional
  zero-downtime migrations, connection pooling, and local Docker to Cloud SQL
  parity. Use whenever creating or modifying database schemas, migrations, SQL
  queries, or connection pool configurations.
---

# PostgreSQL Data & Migration Playbook

## 1. Schema Design & Integrity

- **Explicit Constraints & Types:** Define `PRIMARY KEY`, `FOREIGN KEY` constraints (`ON DELETE` behavior chosen intentionally), `NOT NULL`, and `CHECK` constraints in the database rather than relying solely on application checks.
- **Temporal & Numeric Precision:** Use `timestamptz` for all timestamps (never bare `timestamp`), `numeric(p, s)` or integer minor units for currency/financial values (never `float`/`double precision`), and `text` instead of arbitrary `varchar(n)` unless a business length constraint is enforced via `CHECK`.
- **Indexing Discipline:** Index every foreign-key column used in joins or cascading deletes, match composite index column order to query selectivity (equality predicates before range/sort predicates), and verify non-trivial plans with `EXPLAIN (ANALYZE, BUFFERS)`.

## 2. Parameterized Queries & Read Bounds

- **Zero SQL Interpolation:** Always bind user inputs and dynamic values via driver/ORM query parameters (`$1`, `:param`, `%s` placeholders). Never concatenate or f-string values into SQL statements; allowlist dynamic identifiers (`ORDER BY` columns/directions) via an explicit static mapping.
- **Bounded Reads & N+1 Avoidance:** Apply explicit `LIMIT` bounds and prefer keyset/cursor pagination over deep `OFFSET` scans. Batch or join related lookups instead of issuing queries inside loops.

## 3. Transactional & Zero-Downtime Migrations

- **Immutable History:** Never edit or delete a migration that has already been applied to any shared or production environment; always author a new forward migration.
- **Transactional & Lock-Safe DDL:** Wrap standard DDL in explicit transactions with a short `SET LOCAL lock_timeout = '2s';` and `SET LOCAL statement_timeout = '30s';` so lock queues cannot stall live traffic.
- **Zero-Downtime Expand-and-Contract:**
  - Never perform breaking column renames, column drops, or immediate `NOT NULL` additions on populated tables in a single release.
  - Add nullable columns/new tables first (**expand**), backfill in bounded batches, deploy dual-read/write code, validate constraints (`ADD CONSTRAINT ... NOT VALID` followed by `VALIDATE CONSTRAINT`), and drop legacy columns only in a later release (**contract**).
  - Build indexes on live tables with `CREATE INDEX CONCURRENTLY` (outside a transaction block) so writes are not blocked.
- **Rollback Readiness:** Include verified `down` migrations or document an explicit forward-fix strategy before applying destructive schema changes.

## 4. Connection Pooling & Docker / Cloud SQL Parity

- **Bounded Connection Pools:** Configure explicit `DB_POOL_MIN`, `DB_POOL_MAX`, acquire timeouts, idle timeouts, and `statement_timeout` per service instance so total replicas never exhaust `max_connections` (or use PgBouncer / Cloud SQL Proxy pooling).
- **Environment Parity:** Pin the same PostgreSQL major version and extensions in local Docker Compose (`postgres:<major>`) as in Cloud SQL / production. Keep TLS settings (`sslmode=require`/`verify-full` in cloud, `disable` only for local Docker/Unix sockets) driven by `DATABASE_URL` and `.env`, never hardcoded.
- **Concurrency Lock:** Only **one** subagent at a time may run migrations, container resets, or stateful DB integration tests against a shared local PostgreSQL container or port `5432`.
