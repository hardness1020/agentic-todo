# Implementation Review — Boundary Compliance

A review of the final implementation against the agreed boundaries in [`PRD.md`](PRD.md).
Scope: review only, no code changes. Backend suite status at time of review: **21/21 passing**.

## Boundary Matrix

| Boundary | Implemented? | Evidence in code | Test coverage | Remaining risk |
|---|---|---|---|---|
| Registration (username + password) | ✅ Yes | `accounts/serializers.py:6-19`; `accounts/views.py` `RegisterView` (AllowAny); route `config/urls.py:15` | `accounts/tests.py` `RegistrationTests` (5 tests) | None notable |
| JWT issuance on login | ✅ Yes | SimpleJWT `TokenObtainPairView` `config/urls.py:16`; `SIMPLE_JWT` `config/settings.py:153-155` | `TokenTests.test_obtain_token_with_valid_credentials` | Token response includes a **refresh** token that nothing consumes (cosmetic; PRD says no refresh) |
| Protected endpoints require valid JWT → 401 | ✅ Yes | JWT auth + `IsAuthenticated` defaults `config/settings.py:142-148` | `todos/tests.py` `AuthRequiredTests` (list + create → 401) | Only list/create explicitly asserted for 401; detail/patch/delete unauth covered transitively by the global default |
| CRUD on todos | ✅ Yes | `TodoViewSet(ModelViewSet)` `todos/views.py:7`; router `config/urls.py:11` | `TodoCrudTests` (create/list/retrieve/patch/delete) | None notable |
| Todo fields (id, title, description, completed, created_at, updated_at, owner) | ✅ Yes | `todos/models.py`; serializer fields `todos/serializers.py:9-16` | `test_create_sets_owner_and_defaults_completed_false` | None |
| Per-user ownership isolation (404 not 403) | ✅ Yes | `get_queryset` filters `owner=request.user` `todos/views.py:10-12`; `perform_create` sets owner `:14-15` | `OwnershipIsolationTests` — retrieve/patch/delete other user → **404** (3 tests) | Strong; relies on `get_queryset` everywhere — no current override bypasses it |
| Passwords stored as salted hashes, never returned/logged | ✅ Yes | `password` `write_only` `accounts/serializers.py:7`; `create_user` → PBKDF2 | `test_register_persists_salted_hash_not_plaintext`, `test_register_creates_user_and_omits_password` | Not logged anywhere; no explicit "logs are clean" test (low risk) |
| Input validation: title non-empty + length-bounded | ✅ Yes | `validate_title` rejects blank `todos/serializers.py:19-21`; `max_length=255` on model | `ValidationTests` (empty / missing / >255 → 400) | None |
| JWT secret / `SECRET_KEY` from env | ⚠️ Partial | `load_dotenv` + `os.environ.get('SECRET_KEY', <insecure default>)` in `config/settings.py` | — | **Falls back to a committed insecure default** if `.env` is absent; SimpleJWT signs with `SECRET_KEY`, so a missing `.env` silently uses a public key. `.env.example` provided but real `.env` required |
| Pagination on list (page size 50) | ✅ Yes | `PAGE_SIZE: 50` + PageNumberPagination `config/settings.py:149-150` | `test_list_returns_only_own_todos` reads `resp.data['results']` (confirms paginated shape) | Page-size boundary itself not asserted |
| Access token ~30 min, no refresh | ✅ Yes | `ACCESS_TOKEN_LIFETIME: timedelta(minutes=30)` `config/settings.py:154` | — | Expiry behaviour not tested (would need time-travel); acceptable |
| CORS for local Vite origin only | ✅ Yes | `CORS_ALLOWED_ORIGINS` defaults to `:5173` `config/settings.py:157-161`; middleware ordered correctly | — (verified manually via browser OPTIONS 200) | No automated test; correct middleware ordering confirmed only by live run |
| ORM only, no raw SQL | ✅ Yes | All access via `Todo.objects` / `User.objects`; no `raw()`/cursor | — | None |
| No external network calls / telemetry | ✅ Yes | No outbound HTTP in backend; frontend `fetch` hits local API only `frontend/src/api.js` | — | None |
| Execute mode (direct CRUD, no draft step) | ✅ Yes | ViewSet performs writes immediately | CRUD tests | None |
| Client-side delete confirmation | ✅ Yes | `window.confirm('Delete this todo?')` `frontend/src/TodoList.jsx` | — (verified manually; dialog fired) | Frontend has **no automated tests** |
| Invalid input → 400 structured; UI shows errors | ✅ Yes | DRF serializer errors → 400; `AuthView.formatError` renders field errors | `ValidationTests` (backend); UI side untested | Frontend error rendering untested |
| Auth failure → 401; UI redirects to login | ✅ Yes | `UnauthorizedError` clears token + `onUnauthorized` logs out `frontend/src/api.js`, `TodoList.jsx` | — | Untested in frontend |
| Dependency (SQLite) failure → 500, no stack traces to client | ⚠️ Partial | Default Django 500 handling | — | Dev runs with `DEBUG=True`, which **does** leak stack traces to the client. PRD's "no stack traces" only holds with `DEBUG=False`; not enforced |
| Console logging of requests/errors (dev) | ✅ Yes | Django dev-server request logging (observed in run) | — | Django defaults; no custom logging config |
| Latency < 200 ms locally | ⚠️ Unverified | Local SQLite, single process, small payloads | — | No latency assertion/benchmark; assumed met, not measured |

## Summary

**Fully met:** all in-scope product features, JWT protection, ownership isolation
(the security-critical boundary — solidly tested with 404-not-403), input validation,
pagination, password hashing, ORM-only access, and no external calls. 21/21 backend
tests pass.

**Watch items:**

1. **`SECRET_KEY` fallback** — silently uses a committed insecure key if `.env` is
   missing; this same key signs JWTs. Highest-value hardening point.
2. **`DEBUG=True` in dev leaks stack traces**, contradicting the "no stack traces to
   client" rule on dependency failure. Acceptable for local-only scope, but not enforced.
3. **No frontend tests** — delete-confirm, 401-redirect, and error rendering are
   verified only by a manual browser run. The PRD mandated backend tests only, so this
   is in-spec but a coverage gap.

**Out-of-scope items correctly absent:** sharing/collaboration, refresh-token rotation,
OAuth/MFA, due dates/tags/search, HTTPS/rate limiting.
