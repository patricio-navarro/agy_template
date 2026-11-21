---
name: backend-go-service
description: >-
  Enforces Go 1.22+ HTTP and gRPC service architecture, context.Context
  propagation, explicit %w error wrapping, race-safe concurrency, and
  golangci-lint verification. Use whenever creating or modifying Go services,
  HTTP/gRPC handlers, domain packages, or tests.
---

# Backend Go Service Playbook

## 1. Service Structure & Explicit Dependencies

- Keep entrypoints thin in `cmd/<service>/main.go` and isolate domain/infrastructure packages under `internal/` to prevent unintended external coupling.
- Wire dependencies explicitly through constructors (`NewService(repo, cfg)`); avoid package-level mutable state and `init()` side effects.
- Define narrow interfaces on the consumer side (1–3 methods) and use Go 1.22+ `net/http` `ServeMux` method/path patterns (`"GET /v1/items/{id}"`, `r.PathValue("id")`) or typed gRPC handlers that separate transport mapping from domain logic.

## 2. `context.Context` Propagation & Timeouts

- Accept `ctx context.Context` as the first parameter of every I/O, database, RPC, and service call; never store a `context.Context` inside a struct field.
- Always propagate the caller's `ctx` (`r.Context()` in HTTP, incoming RPC `ctx` in gRPC) downstream rather than replacing it with `context.Background()`.
- Enforce explicit timeouts on every outbound client (`http.Client{Timeout: ...}`, `context.WithTimeout`) and server (`ReadHeaderTimeout`, `IdleTimeout`) so slow peers cannot exhaust goroutines or sockets.

## 3. Error Wrapping & Boundary Hygiene

- Wrap actionable errors with lower-case context using `fmt.Errorf("operation %s: %w", id, err)` without trailing punctuation.
- Inspect sentinel or typed errors exclusively via `errors.Is` and `errors.As`—never compare error strings or use `==` on potentially wrapped errors.
- Translate internal errors into structured HTTP/gRPC status codes at the transport boundary; never leak raw SQL messages, stack traces, or internal endpoints to clients.

## 4. Race-Safe Concurrency & Graceful Shutdown

- Never launch unbounded background goroutines: coordinate concurrent work with `errgroup.WithContext`, bounded worker pools, and `select` on `<-ctx.Done()`.
- Guard shared mutable state explicitly (`sync.Mutex`, `sync.RWMutex`, `sync/atomic`) or isolate ownership to a single goroutine communicating over channels.
- Handle `SIGINT`/`SIGTERM` via `signal.NotifyContext`, drain active requests with `srv.Shutdown(shutdownCtx)` / `grpcServer.GracefulStop()`, and close database pools cleanly before exit.

## 5. Testing & Verification Gate

- Write deterministic table-driven tests (`t.Run(...)`) with `t.Helper()` on shared assertions and `httptest` / `bufconn` for transport integration tests.
- Run the full verification suite before opening a PR:

```sh
go vet ./...
golangci-lint run
go test -race ./...
```
