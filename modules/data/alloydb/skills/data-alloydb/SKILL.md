---
name: data-alloydb
description: >-
  Guides Google Cloud AlloyDB for PostgreSQL connectivity via Auth Proxy or
  Language Connectors, IAM database authentication, connection pooling,
  transactional migrations, pgvector indexing, and columnar engine workloads.
  Use whenever configuring AlloyDB connections, migrations, vector search, or
  analytical queries.
---

# Google Cloud AlloyDB Playbook

## 1. Auth Proxy, Language Connectors & IAM Authentication

- **Encrypted Private Connectivity:** Connect applications using the **AlloyDB Language Connector** (Python, Go, Node.js, Java) or run the **AlloyDB Auth Proxy** sidecar/local daemon (`alloydb-auth-proxy "$ALLOYDB_CONNECTION_NAME" --auto-iam-authn`) rather than exposing public IP allowlists or unencrypted TCP connections.
- **IAM Database Auth:** Prefer IAM database authentication (`ALLOYDB_USE_IAM_AUTH=true`) mapped to dedicated runtime service accounts (`roles/alloydb.client` + `roles/alloydb.databaseUser`) with least-privilege PostgreSQL schema/table grants instead of shared `postgres` superuser credentials.
- **Read Pool Routing:** Route read-heavy reporting or embedding similarity queries to an AlloyDB read pool instance URI while keeping writes and transactional reads on the primary instance.

## 2. Connection Pooling & Migration Safety

- **Right-Sized Pools:** Size per-instance pools (`pool_size`, `max_overflow`, `pool_recycle`, `connect_timeout`) against maximum expected Cloud Run/GKE replica count so concurrent connections stay comfortably below the instance `max_connections` limit.
- **PostgreSQL Compatibility & Zero-Downtime Migrations:** Keep local Docker PostgreSQL major versions aligned with AlloyDB's PostgreSQL target version. Wrap DDL in transactions with short `lock_timeout`/`statement_timeout`, use expand-and-contract for breaking schema changes, and use `CREATE INDEX CONCURRENTLY` for live index builds.

## 3. `pgvector` Embeddings & Indexing

- **Fixed Dimensions & Distance Matching:** Enable `CREATE EXTENSION IF NOT EXISTS vector;` in a tracked migration, declare explicit vector dimensions (`embedding vector(1536)` or `vector(768)`), and match the query distance operator (`<=>` cosine, `<->` L2, `<#>` inner product) to the index operator class (`vector_cosine_ops`, `vector_l2_ops`, `vector_ip_ops`).
- **Indexed ANN Search:** Create `scann` (`alloydb_scann`) or `hnsw` indexes with benchmarked build/query parameters (`num_leaves` / `m`, `ef_construction`) and enforce selective metadata pre-filters or `LIMIT` bounds so hot paths never fall back to full sequential scans.

## 4. Columnar Engine Workloads

- **Targeted Analytical Acceleration:** Enable and populate the AlloyDB columnar engine selectively for large analytical tables/columns (`google_columnar_engine_add(...)` dynamically or `google_columnar_engine.relations` persistently / auto-columnarization) instead of adding excessive OLTP B-tree composite indexes that slow down writes.
- **Plan & Memory Verification:** Confirm analytical queries actually use `Columnar Scan` via `EXPLAIN (ANALYZE, BUFFERS)` and size `google_columnar_engine.memory_size_in_mb` within instance RAM budgets.

## 5. Production Guardrails & Concurrency Lock

- **Destructive Cloud Operations:** Never execute `gcloud alloydb` `delete` (`clusters`, `instances`, `backups`, `users`) or topology mutations (`failover`, `promote`, `switchover`, `restore`) without explicit human confirmation.
- **Concurrency Lock:** Only **one** subagent at a time may bind the local AlloyDB Auth Proxy port (`5432`) or run stateful migrations against a shared test database instance.
