---
name: backend-node-express
description: >-
  Enforces Express API controller/service separation, Bearer and cron secret
  auth middleware, rate limiting, Promise.allSettled cleanup, and graceful
  SIGTERM shutdown for Node.js + TypeScript backends. Use whenever editing server
  routes, middleware, or backend services.
---

# Backend Node.js + Express + TypeScript Playbook

## 1. Route & Service Decomposition

- Keep HTTP routing files focused on request parsing, middleware enforcement, and status mapping. Move business logic into dedicated domain service modules so handlers never bloat into monoliths.
- Validate request bodies, path params, and query strings explicitly at the boundary before calling domain services.

## 2. Authentication, Tenant Isolation & Rate Limiting

- Separate user authentication middleware (Bearer token verification + tenant/role lookup) from scheduled job authentication (`verifyCronAuth` with constant-time secret comparison).
- Apply rate limiting and security headers (`helmet`, strict CORS origins) on public and authenticated mutation routes.

## 3. Resilience & Lifecycle

- Use `Promise.allSettled` for non-critical fan-out or cascade cleanup steps so one downstream failure does not silently abort independent cleanup work, and log partial failures with context.
- Implement graceful `SIGTERM`/`SIGINT` shutdown closing HTTP servers and background clients cleanly.
- Run targeted Vitest suites (`npx vitest run <file> --reporter=dot`) while iterating, and finish with `npm run lint`, `npx vitest run --reporter=dot`, and `npm run build`.
