# Product Requirement Document

We are solving the following problem:

**Goal:**
Build a multi-user TODO list application where a user can register, log in, and manage their own TODO items (create, read, update, delete). Auth is JWT-based, data is persisted in a local SQLite database, and the UI is a minimal, functional React frontend. Target environment is local development only.

---

## Boundaries

### Product
- **In scope:**
  - User registration and login (username/email + password).
  - JWT issuance on login; protected API endpoints require a valid token.
  - CRUD on TODO items scoped to the authenticated user.
  - A TODO item has: `id`, `title` (required), `description` (optional), `completed` (bool, default false), `created_at`, `updated_at`, `owner` (FK to user).
  - Minimal functional React UI: login/register view + a todo list view with add / edit / toggle-complete / delete.
- **Out of scope:**
  - Sharing TODOs between users, collaboration, teams, roles/permissions beyond per-user ownership.
  - Due dates, reminders, tags, priorities, attachments, sub-tasks, search/filter (beyond completed toggle).
  - Email verification, password reset, OAuth/social login, MFA.
  - Production hardening: HTTPS, refresh-token rotation, rate limiting, horizontal scaling.
  - Mobile apps, offline mode, real-time sync.

### User / Action
- **Mode:** Execute. The system performs CRUD directly on user request — no draft/recommend step, since users act only on their own data.
- **Approval required for:** None at the app level. Destructive UI actions (delete) get a client-side confirmation prompt, but no server-side approval workflow.

### Data / PII
- **Reads:** The authenticated user's own profile (id/username) and their own TODO items.
- **Writes:** New users (registration), the user's own TODO items.
- **Sensitive-data rules:**
  - Passwords stored only as salted hashes (Django's default PBKDF2 hasher); never logged or returned in responses.
  - JWT secret kept in environment/.env, not committed.
  - A user can never read or mutate another user's TODOs — every TODO query is filtered by `owner == request.user`.

### Tool
- **Allowed tools/APIs:**
  - Backend: Django + Django REST Framework, `djangorestframework-simplejwt` for JWT.
  - DB: SQLite (Django default `db.sqlite3`).
  - Frontend: React (Vite), `fetch`/axios to call the REST API.
- **Disallowed actions:**
  - No external network calls, third-party data sharing, or analytics/telemetry.
  - No raw SQL string interpolation (use the ORM).
  - No serving over the public internet in this scope.

### Policy
- **Pre-execution checks (per request):**
  1. Valid, unexpired JWT present on all `/todos` endpoints.
  2. Requested TODO belongs to the authenticated user (404, not 403, on mismatch to avoid leaking existence).
  3. Input validation: `title` non-empty and length-bounded; types coerced/validated by DRF serializers.

### Cost / Time
- **Latency target:** API responses < 200 ms locally (single-user, local SQLite).
- **Runtime/limits:**
  - Access token lifetime ~30 min; no refresh tokens in scope (re-login on expiry).
  - No retry logic needed; single local process.
  - Pagination on list endpoint (e.g. page size 50) to bound payloads.

### Trust / Failure
- **Low confidence:** Not applicable — this is deterministic CRUD, no ML/probabilistic decisions.
- **Invalid input:** Return `400` with a structured error body (DRF serializer errors); the React UI shows inline field/form errors.
- **Dependency failure:** If SQLite is unreachable/locked, return `500` with a generic message (no stack traces to client); the UI shows a retryable error state. Auth failures return `401`.

### Audit / Spike
- **Logs/monitoring:** Console logging of requests and errors via Django's default logger (dev only). No external monitoring stack.
- **Fallback/spike behavior:** None required for local single-user scope.

### Success
- **Tests/metrics/user-visible behavior:**
  - A new user can register, log in, and receive a JWT.
  - An authenticated user can create, list, edit, toggle, and delete TODOs; changes persist across page reload (DB-backed).
  - User A cannot see or modify User B's TODOs (verified by test).
  - Requests without a valid token to protected endpoints return `401`.
  - Backend test suite (pytest/DRF `APITestCase`) covers: auth flow, CRUD happy paths, ownership isolation, and input validation — all passing.

---

## Compact Implementation Brief

**Architecture:** Django + DRF backend exposing a JSON REST API, consumed by a React (Vite) SPA. SQLite as the local DB. JWT auth via `djangorestframework-simplejwt`.

**Backend**
- App `accounts`: registration endpoint + SimpleJWT token endpoints (`/api/auth/register`, `/api/auth/token`).
- App `todos`: `Todo` model (`title`, `description`, `completed`, `created_at`, `updated_at`, `owner` FK).
- `TodoViewSet` (DRF ModelViewSet) with `IsAuthenticated`; `get_queryset` filters by `request.user`; `perform_create` sets owner.
- Endpoints: `GET/POST /api/todos/`, `GET/PATCH/DELETE /api/todos/{id}/`.
- Serializers validate `title` (non-empty, max length).

**Frontend (React + Vite)**
- Views: `Login/Register` and `TodoList`.
- Store JWT in memory + localStorage; attach `Authorization: Bearer <token>` to API calls; redirect to login on `401`.
- Todo list: add input, per-item checkbox (toggle complete), inline edit, delete with confirm.
- Minimal CSS only.

**Config / run**
- Secrets (`SECRET_KEY`, JWT settings) from `.env`; SQLite file gitignored.
- CORS configured for the local Vite dev origin.

**Tests:** DRF `APITestCase` for auth, CRUD, and cross-user isolation.

**Open assumptions carried forward (flag if wrong):** no refresh tokens (re-login on expiry); username+password auth (no email verification); single local deployment.
