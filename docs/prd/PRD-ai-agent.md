# Product Requirement Document — AI Agent

> Follow-up to [`PRD.md`](PRD.md). The base app (multi-user TODO: Django + DRF + SimpleJWT +
> SQLite backend, React + Vite frontend, per-user isolation, 21 passing tests) is unchanged and
> remains the foundation. This document adds an **AI agent** driven from a chatbox on a single
> **dashboard**, following the agent patterns in the reference `code.py` (tool-calling loop,
> dynamic system-prompt assembly, per-user memory, cron scheduling, LLM error recovery).

We are solving the following problem:

**Goal:**
Add an AI assistant to the existing per-user TODO app. From a chatbox on a single dashboard
screen, an authenticated user can converse with an agent that: performs CRUD on **their own**
todos via tools; schedules cron jobs that later fire **agentically** and push notifications to the
web app; remembers per-user facts and recalls them; and operates under a system prompt that is
assembled fresh each turn from live state (identity, tool catalog, current time, todo stats, and the
memories most relevant to the turn — selected by a **secondary, cheaper LLM call**). Every change the
agent makes is **reflected reactively in the UI** — the affected item is
highlighted and then updated, so the user watches the agent act. The agent uses Anthropic (Claude)
and is hardened with LLM error recovery (retry, backoff, model fallback). The app stays
local-development only, keeps strict per-user data isolation, and **degrades gracefully without an
API key** (the rest of the app keeps working).

---

## Boundaries

### Product
- **In scope:**
  - A **chatbox** where the agent does CRUD on the user's todos via tools
    (`create_todo`, `list_todos`, `update_todo`, `complete_todo`, `delete_todo`).
  - **Reactive UI feedback:** when the agent creates / updates / completes / deletes a todo (from
    chat or from a fired cron job), the affected row is **highlighted first** (a yellow box that
    flashes and fades) and **then the change is applied** — so agent actions are visible in real time
    rather than appearing via a silent reload. Creates highlight the new row; deletes fade out before
    removal. The same flash-then-apply pattern applies to **reminder rows** (when the agent
    schedules or cancels a cron job) and **memory rows** (when the agent stores a fact) — not just
    todos. When a cron fires, its reminder row also receives the flash to signal it triggered.
  - **Agentic cron:** the agent schedules 5-field cron jobs (`schedule_cron`/`list_crons`/`cancel_cron`);
    when a job fires, a real agent turn runs for that user with the job's prompt, may modify todos,
    and calls a `notify_user` tool to create a notification.
  - **Memory:** per-user durable facts (`remember`/`recall`), upserted by key.
  - **Secondary-LLM memory retrieval:** once per turn, a secondary (cheaper/faster) Claude
    model selects the stored facts relevant to the current message; only those are injected
    into the system prompt. When a user has at most `AGENT_MEMORY_RETRIEVAL_THRESHOLD` facts,
    all are injected directly (no extra call). Retrieval is **best-effort** — any failure (an
    unparseable reply, an LLM error, or a missing key) falls back to injecting all facts
    (length-capped). This is the `Secondary LLM → Memory` (load / retrieval) path in the design.
  - **Dynamic system-prompt assembly:** rebuilt each turn from identity + tool catalog +
    current UTC time + todo stats + the retrieved (relevant) subset of memories.
  - **LLM error recovery:** 429 backoff with jitter, 529/overload → fallback model after N retries,
    `max_tokens` escalation/continuation, prompt-too-long → one reactive trim, and graceful
    degradation when `ANTHROPIC_API_KEY` is absent.
  - **Persisted conversation** per user (history seeds context across turns).
  - **Notifications** surfaced in the dashboard via two distinct mechanisms:
    - **Header bell popover** (360 px wide): lists notifications with title, body, relative
      timestamp, and unread dot per item; includes a "Mark all read" button (visible only when
      unread items exist) and a "Clear" button; closes on outside click; the bell badge animates
      (`badgePop` scale-in) when a new notification arrives.
    - **Bottom-left toasts**: each toast slides in from the left (220 ms), shows bell icon + title
      + body, and has a dismiss button; stacked vertically, positioned clear of the chat FAB.
    - Frontend polls `GET /api/notifications/` every ~10 s to drive both surfaces.
  - A **single dashboard** screen composed of:
    - **Greeting section**: "Today's focus" H1 + muted subtitle above the stats grid.
    - **Stats grid**: three stat cards (open count, done count, total count) with large numbers;
      below them a **momentum bar** — a gradient-fill linear progress bar showing `done / total`
      percentage with a smooth 400 ms transition on change.
    - **Todo list**: the existing todo card (add bar + todo rows) in the left column.
    - **Reminders sidebar panel** (right column, 332 px): persistent card listing the user's
      scheduled cron jobs; each row shows a clock icon, the reminder label, a human-readable
      schedule string (e.g. "every hour"), a next-fire-time label (e.g. "next in ~1h"), and a
      hover-reveal cancel (×) button; new rows slide in (`rowRise`) and flash yellow when the
      agent creates a job; empty state: "No reminders yet. Try 'remind me to stretch every hour.'"
    - **Memory sidebar panel** (right column, below Reminders): persistent card listing the user's
      remembered facts; each row shows a bookmark icon (purple accent), the full fact text
      (wrapping), and a hover-reveal forget (×) button; same flash + slide-in animations as
      Reminders; empty state: "Nothing remembered yet. Try 'remember I prefer short titles.'"
    - **Floating chat widget** (see below) and the **notifications** surfaces above.
    - Two-column CSS grid (left: `1fr`, right: 332 px); collapses to single column below 880 px.
- **Out of scope:**
  - Streaming chat responses (SSE/WebSockets); real-time push (notifications use polling).
  - Multi-conversation / multi-thread chat UI (one conversation per user).
  - Sharing/collaboration, voice, and **vector/embedding-based RAG** — memory retrieval is a
    lightweight secondary-LLM relevance pass over the user's own stored facts, not embeddings.
  - The heavier `code.py` mechanisms: worktrees, teammates/message-bus, MCP, subagents, skills,
    hook/permission pipeline, full context compaction, background tasks.
  - Celery/Redis or any new scheduling/broker infrastructure.
  - Production hardening (HTTPS, rate limiting, async task offload, horizontal scaling).

### User / Action
- **Mode:** Execute. The agent acts directly on the user's own data on request — no draft/approve
  step — consistent with the base app's direct CRUD (users only ever act on their own data).
- **Approval required for:** None at the server level. The existing client-side delete confirmation
  on the todo list is retained for manual UI deletes; the agent's `delete_todo` operates only on the
  requesting user's own todos.

### Data / PII
- **Reads:** the authenticated user's todos, todo stats, memories, scheduled jobs, notifications,
  and chat history.
- **Writes:** the same set, always with `owner = request.user` (todos, memories, jobs,
  notifications, chat messages).
- **Sensitive-data rules:**
  - `ANTHROPIC_API_KEY` is read from environment/`.env`, never committed, never logged, never
    returned in responses.
  - Conversation history and memories are user data and are **never** exposed across users.
  - **Every tool handler is bound to `request.user`** (a closure over the user); the model is given
    no user identifier it can override, and any cross-user object id resolves to a benign
    "not found" — the agent-layer analog of the base app's 404-on-mismatch isolation.
  - Passwords remain salted hashes (Django default); JWT secret stays in env (unchanged from base).

### Tool
- **Allowed tools/APIs:**
  - Anthropic Messages API (tool use) via the `anthropic` Python SDK; a primary model, an optional
    fallback model, and a **secondary model** (for memory retrieval) — all configurable by env.
  - A **fixed tool catalog** (12 tools): `create_todo`, `list_todos`, `update_todo`,
    `complete_todo`, `delete_todo`, `get_todo_stats`, `remember`, `recall`, `schedule_cron`,
    `list_crons`, `cancel_cron`, `notify_user`. Each handler runs Django ORM operations scoped to
    the user (todo validation reuses `TodoSerializer`).
- **Disallowed actions:**
  - No shell/file/network/arbitrary-code tools, no raw SQL, no MCP/external integrations.
  - No tool that accepts a target user, owner, or id outside the caller's own scope.
  - No external data sharing, analytics, or telemetry.

### Policy
- **Pre-execution checks (per request / per turn):**
  1. Valid, unexpired JWT on every agent endpoint (inherits the base DRF `IsAuthenticated` default).
  2. Ownership filtering on every conversation/message/memory/job/notification query
     (`owner == request.user`; 404, not 403, on mismatch — no existence leak).
  3. `schedule_cron` validates the 5-field expression (`validate_cron`) before persisting a job;
     an invalid expression returns the validator's message and creates nothing.
  4. `create_todo`/`update_todo` reuse `TodoSerializer` validation (title non-empty, ≤255).
  5. Each agent turn is bounded by a maximum tool-loop turn count to prevent runaway loops.

### Cost / Time
- **Latency target:** existing REST endpoints stay < 200 ms locally. A **chat turn is synchronous**
  and may take seconds (one or more LLM calls plus bounded retries); the UI shows a "thinking…"
  state during the turn.
- **Runtime/limits:**
  - `MAX_RETRIES = 3` with exponential backoff capped at ~32 s; `MAX_CONSECUTIVE_529` before
    switching to the fallback model; `max_tokens` 8000 escalating to 16000 once, then a bounded
    continuation; bounded tool-loop turns per request.
  - Injected memory is length-capped (~2000 chars) to bound prompt size/cost.
  - **Memory retrieval** calls the secondary model **at most once per turn**, and only when stored
    facts exceed `AGENT_MEMORY_RETRIEVAL_THRESHOLD` (default 5); it is best-effort and **not** retried
    (any failure falls back to injecting all facts, capped), so it adds at most one short, bounded
    call to a turn's latency.
  - The scheduler polls every ~30 s and matches cron at minute granularity; jobs only fire while
    `run_scheduler` is running (no missed-minute backfill).
  - The reactive-highlight animation is purely client-side (CSS, ~1.5 s) and adds no server cost.
  - **Known limitation:** retry sleeps and the LLM call block the request worker thread —
    acceptable for local single-user use; production would offload turns to a task queue.

### Trust / Failure
- **Low confidence:** the agent may misinterpret a request. Mitigations: a small fixed tool set,
  structural per-user scoping, and **visible feedback** — the chat shows the tool calls it made and
  the affected todos flash in place — so the user can immediately see and correct what the agent did.
- **Invalid input:** tool handlers return descriptive error strings the model can recover from
  (e.g. "Todo 5 not found.", validation messages, the cron validator message) — they never raise
  raw DB exceptions into the loop.
- **Dependency failure:**
  - **Missing `ANTHROPIC_API_KEY`:** chat returns `503` (the user message is still persisted) and
    the scheduler logs a warning and skips firing — **the rest of the app remains fully functional.**
  - **429 (rate limit):** exponential backoff + jitter, then retry.
  - **529 / overloaded:** retry; after `MAX_CONSECUTIVE_529`, switch to the fallback model (if set).
  - **Prompt too long:** one reactive trim of older history, then retry once.
  - **Other LLM errors:** an assistant error message is persisted to the transcript and the turn
    ends cleanly; the app keeps running.

### Audit / Spike
- **Logs/monitoring:** Python `logging` (logger `agent`) in the runner and scheduler records tool
  calls, retries, model switches, and fired jobs — no ANSI, no secrets. Conversation history,
  notifications, and each job's `last_fired_at` provide an audit trail of agent actions. No external
  monitoring stack (dev-only, consistent with the base app).
- **Fallback/spike behavior:** none beyond the retry/backoff/fallback-model recovery above.

### Success
- **Tests (offline — a fake LLM client is injected; the real API is never called):**
  - Cron `validate_cron` / `cron_matches` (including the day-of-month-or-day-of-week semantics).
  - A chat turn persists user + assistant + tool messages and a scripted `create_todo` actually
    creates a todo owned by the caller and returns it in the response `actions`; the no-API-key path
    returns `503` and still persists the user message.
  - **Agent tool isolation:** user A's scripted `update`/`delete`/`complete_todo` against user B's id
    mutates nothing; `list_todos`/`recall`/`list_crons`/stats never cross users.
  - Memory upsert by `(owner, key)` and per-user isolation, including in the assembled prompt.
  - **Secondary-LLM memory retrieval:** below the threshold all facts are injected with **no**
    secondary call; above it, the secondary model's scripted selection drives which facts are
    injected; an LLM error or unparseable reply falls back to injecting all facts. (Fake client,
    offline.)
  - Scheduler firing: a matching job fires once (double-fire guard), a one-shot deactivates,
    a recurring job stays active, and the fire creates a notification owned by the job's owner.
  - Notification and stats endpoints are owner-scoped; `401` without a token.
  - The **existing 21 backend tests still pass.**
- **User-visible behavior:**
  - "add a todo to buy milk, then mark my oldest todo done" → the affected rows **flash yellow and
    then update**; the todo list and stats reflect the change; the chat shows the tool calls it made.
  - "remind me to stretch every hour" (or a one-shot a minute out) → a scheduled job is created;
    when it fires, a notification toast appears in the dashboard within one poll interval (and any
    todos the fire changed flash on the next refresh).
  - "remember that I prefer short titles" → the fact is stored and reflected in later turns.
  - User A can never see or modify user B's todos, memories, jobs, or notifications.

---

## Compact Implementation Brief

**Architecture:** A new DRF app (`agent`) adds owner-scoped models and RESTful endpoints. A single
**agent runner** (tool-calling loop) is reused by both the chat endpoint and a `run_scheduler`
management command, so chat turns and agentic cron fires share the same tools, prompt assembly, and
error recovery. The React app gains one **dashboard** screen that polls for notifications and
reactively highlights agent-driven changes. Anthropic is the LLM provider; SQLite and JWT auth are
unchanged.

**Backend**
- App `agent` with models: `Conversation`, `ChatMessage` (role + JSON content blocks), `Memory`
  (`UniqueConstraint(owner, key)`), `ScheduledJob` (5-field cron + `last_fired_marker` double-fire
  guard), `Notification`. All carry `owner` FK like `Todo`.
- RESTful ViewSets (DefaultRouter, all owner-scoped, 404 on cross-user, JWT + `IsAuthenticated`):
  `GET/POST /api/chat/messages/`, `GET/DELETE /api/memories/`, `GET/DELETE /api/scheduled-jobs/`,
  `GET/PATCH /api/notifications/` (+ `mark-all-read`), and an additive `GET /api/todos/stats/`
  action on the existing `TodoViewSet`. Only `config/urls.py` is edited (an additive include).
- The chat `POST` returns the new messages **plus an `actions` summary** (`{action, resource:'todo',
  id}` for each todo mutation this turn) so the frontend can target its reactive highlights.
- Service layer: `llm.py` (Anthropic client factory + `RecoveryState` + `with_retry`),
  `memory.py` (`candidate_memories` / `format_memories` / `retrieve_relevant` — the secondary-LLM
  relevance pass with a below-threshold short-circuit and best-effort fallback),
  `prompt.py` (`assemble_system_prompt(user, memory_block)`), `tools.py` (static `TOOL_SCHEMAS` +
  `build_handlers(user)` closure — the isolation guardrail), `runner.py` (`run_agent_turn` retrieves
  the relevant memories once per turn, then runs the tool loop and collects `actions`),
  `cron.py` (pure cron validate/match ported from `code.py`).
- Scheduler: `python manage.py run_scheduler` polls active jobs (~30 s), sets the minute marker and
  deactivates one-shots **before** firing each matching job agentically via the shared runner.

**Frontend (React + Vite, vanilla `fetch`, plain CSS, no new deps)**
- `App.jsx` renders a new `Dashboard` when authenticated, composing a two-column grid:
  left column (`StatsBar` + greeting + momentum bar + existing `TodoList`), right sidebar
  (`Reminders` + `Memory`), floating `ChatWidget`, and `Notifications` (header popover + toasts).
- `Reminders` and `Memory` components each render a persistent card in the right sidebar, polling
  `GET /api/scheduled-jobs/` and `GET /api/memories/` respectively (or driven by the chat
  response's `actions`). Cancel/forget buttons call `DELETE` on the respective endpoint and
  trigger the fade-out animation before removal.
- `ChatWidget` is a floating collapsible widget:
  - **Collapsed FAB** (60 px, fixed bottom-right): sparkles icon; unread-message badge count;
    `.busy` class triggers an animated pulsing ring (`fabRing`, 1.4 s infinite) while the agent
    is working.
  - **Expanded panel** (392 × 620 px, fixed): header shows agent avatar, "ToDo assistant" name,
    green "Online" status dot; a **reset conversation** button (refresh-cw icon, disabled while
    thinking or when the transcript is fresh) clears history back to the initial greeting; a
    minimize button collapses back to the FAB.
  - **Message transcript**: user messages as right-aligned dark bubbles; assistant messages as
    left-aligned light bubbles with avatar; each tool call renders as an **activity row** with a
    tool-specific icon (create→plus, complete→check, delete→trash, update→pencil,
    schedule\_cron→clock, cancel\_cron→×, remember→bookmark, recall→brain,
    list\_todos→list, get\_todo\_stats→bar-chart, notify\_user→bell), a pending spinner + label
    during execution, and a completion checkmark + label + monospace tool name when done.
  - **Thinking state**: three animated bobbing dots; send button and reset button disabled;
    FAB shows busy ring.
  - **Suggestion chips**: four hardcoded preset prompts shown only when the conversation is fresh
    (initial greeting only) and the agent is not thinking — clicking one fires it as a user message:
    "Add buy milk, then mark my oldest done", "Remind me to stretch every hour",
    "Remember I prefer short titles", "What's on my list today?".
  - Composer pill (border-radius 999 px): text input + send button (disabled when empty or
    thinking); submits on Enter.
- **Reactive highlight:** the chat response's `actions` (and, for cron-driven changes detected by
  the notification poll, a diff of the refreshed list against the previous one) apply a transient
  yellow flash (~1.5 s, `#fff3c4` background + `#f4cf57` ring) to each affected row — highlight
  first, then apply the create/update/complete/delete; deletes fade before removal. The same
  mechanism applies to Reminders and Memory rows when the agent creates or removes them, and to a
  reminder row when its cron fires. A shared refresh signal reloads the todo list, stats,
  reminders, and memories.
- `Notifications`: header bell popover + bottom-left `Toasts` component as described in Product
  scope above; both driven by the same polling call.
- `api.js` is extended with the new endpoint methods using the existing `request()` helper.

**Config / run**
- `requirements.txt`: add `anthropic`. `settings.py`: add `agent` to `INSTALLED_APPS` (no DRF
  changes). `.env.example`: add `ANTHROPIC_API_KEY` (blank = run without the assistant),
  `ANTHROPIC_MODEL` (default a current Claude model), `ANTHROPIC_FALLBACK_MODEL` (optional),
  `ANTHROPIC_SECONDARY_MODEL` (memory-retrieval model, default a fast Claude e.g. `claude-haiku-4-5`),
  `AGENT_MEMORY_RETRIEVAL_THRESHOLD`, `AGENT_SCHEDULER_INTERVAL`.
- Run three processes locally: `manage.py runserver`, `manage.py run_scheduler`, and `npm run dev`.

**Tests:** DRF `APITestCase` mirroring the base suite, plus runner tests that inject a fake Anthropic
client scripting tool calls — fully offline and deterministic.

**Open assumptions carried forward (flag if wrong):** single local instance (so the scheduler needs
no distributed lock); synchronous chat turns; one conversation per user; minute-granular cron that
fires only while the scheduler runs; the app must boot and serve todos with no API key configured.
