---
name: backend-python-fastapi
description: >-
  Enforces FastAPI architecture, Pydantic v2 strict validation, dependency
  injection, async event-loop safety, virtual environment isolation, and
  ruff/mypy/pytest verification. Use whenever creating or modifying Python
  services, FastAPI routers, schemas, or tests.
---

# Backend Python + FastAPI Playbook

## 1. Environment & Dependency Hygiene

- Never run global `pip install`. Use project virtual environments (`uv`, `poetry`, or `python -m venv .venv && .venv/bin/pip install ...`).
- Pin dependencies cleanly in `pyproject.toml` (preferred) or `requirements.txt` + `requirements-dev.txt`.

## 2. FastAPI & Domain Architecture

- **Thin Routers, Focused Services:** Keep `APIRouter` handlers thin (HTTP parsing, auth dependency, response serialization) and move business logic into typed domain service modules.
- **Strict Pydantic v2 Contracts:** Use explicit request/response `BaseModel` schemas (`model_config = ConfigDict(extra="forbid")` on external request payloads) and never return raw database documents directly without response models.
- **Dependency Injection (`Depends`):** Inject authentication, tenant/RBAC context, database clients, and settings via `Depends(...)` so tests can cleanly swap dependencies with `app.dependency_overrides`.

## 3. Async & Concurrency Safety

- Never call blocking synchronous I/O (sync `requests`, `time.sleep`, heavy CPU work) inside `async def` endpoints—use `async` clients (`httpx.AsyncClient`) or explicitly run sync endpoints as `def` so FastAPI offloads them to the threadpool.
- Bound external calls with explicit timeouts and propagate structured `HTTPException` or domain error handlers without leaking internal tracebacks.

## 4. Verification Gate

Run compact checks during iteration and the full suite before PRs:
```sh
ruff check . && ruff format --check .
mypy .
pytest -q
```
