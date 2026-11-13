---
name: firebase-platform
description: >-
  Guides Firebase Authentication, named Cloud Firestore databases, bounded
  query patterns, batch chunking, and emulator testing across Node, Python, or
  Web backends. Use whenever interacting with Firebase CLI, Auth, or Firestore.
---

# Firebase Platform Playbook

## 1. Named Firestore Database Discipline

- Explicitly pass the configured `FIREBASE_DATABASE_ID` (never rely implicitly on `(default)` unless intentionally targeting it) across Client SDK, Admin SDK (`firebase-admin` / `google-cloud-firestore`), and Firebase CLI commands.
- Keep `scripts/lib-firebase.sh` as the single source of truth for rules/indexes deployment and TTL policies.

## 2. Query & Write Unit Economics

- Never introduce unbounded collection listeners or N+1 client reads; apply explicit `limit()` bounds and composite indexes in `firestore.indexes.json`.
- Chunk Firestore `WriteBatch` operations to at most 500 operations per batch (or 250–400 when updating indexed fields) and handle empty inputs cleanly.

## 3. Security Rules Authoring & Emulator Mutex

- Whenever `firestore.rules` must be created or modified, **delegate authoring to the `firestore-rules-author` subagent** and audit the result with [`firestore-security-auditor`](../firestore-security-auditor/SKILL.md).
- Run security rules integration tests against the local Firebase Firestore Emulator (`npm run test:rules` or `npx -y firebase-tools@latest emulators:exec --only firestore ...`).
- **Concurrency Lock:** Only **one** subagent at a time may run the Firebase Emulator to avoid port `8080` / Hub collisions.
