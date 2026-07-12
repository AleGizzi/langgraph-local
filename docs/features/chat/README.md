# Chat
> Part of Local Agents Studio. Read docs/index.md for the doc map.

## What it is

A one-shot conversational endpoint that reuses the provider/tool/skill
machinery from team runs, without a team, a run row, or persisted events —
just a streamed assistant turn over an arbitrary message history. Chat
*sessions* (title, agent config, message list) are persisted separately in
their own `chats` table so the Chat page can keep a history sidebar.

## Key files

| Path | Role |
|------|------|
| `engine.py` (`chat_stream`) | Standalone generator (not a LangGraph) for one assistant turn: same tool loop, skill injection, `<think>` stripping as team runs. |
| `app.py` | `POST /api/chat` (SSE) and `/api/chats` CRUD (`_validate_chat`). |
| `storage.py` | `chats` table: `title, agent (json), messages (json), created_at, updated_at`. |
| `frontend/src/pages/Chat.jsx` | History sidebar, message list, fetch-reader SSE parsing, persona quick-load, save-as-persona. |
| `frontend/src/components/AgentFields.jsx` | Shared config editor (model/prompt/params/tools/skills) — same component teams and personas use. |

## API

### `POST /api/chat` — SSE, but via `fetch` + `body.getReader()`, not `EventSource`

Request:
```json
{"agent": {"model": "qwen2.5:7b", "provider": "ollama", "params": {...},
           "tools": ["knowledge"], "skills": ["Concise Mode"]},
 "messages": [{"role": "user", "content": "..."}]}
```
`agent.model` and `messages` (≥1) are required; `provider` defaults to
`ollama`; `params` cleaned via `providers.clean_params`; `tools`/`skills`
filtered to currently-valid names (invalid ones silently dropped) — same
validation shape as team agents, but chat agents have **no `temperature`
top-level field**, only `params.temperature`.

**Event types actually emitted** (verified against `engine.chat_stream` and
`app.py`'s `chat()` route — this differs from the run/SSE event set, see
Gotchas):

| type | content |
|------|---------|
| `token` | one streamed chunk |
| `tool_call` | `"name(args json, ≤300ch)"` |
| `tool_result` | result text (≤1000ch) |
| `done` | the full final assistant text (emitted once, always last on success) |
| `error` | error message (emitted by `app.py`'s wrapper around the generator, not by `chat_stream` itself) |

There is **no** `run_start`, `agent_start`, `agent_end`, or `run_end` in chat
— those are run-only event types.

### `/api/chats` — session persistence

- `GET /api/chats` — up to 100, newest first, `{id, title, agent,
  message_count, created_at, updated_at}` (no `messages` array — see
  `GET /api/chats/<id>` for the full one).
- `POST /api/chats` `{title?, agent, messages}` — `title` auto-derived from
  the first user message (first 64 chars) if blank.
- `GET/PUT/DELETE /api/chats/<id>`.

## How it works

- System prompt: `agent.system_prompt` (or a default) plus
  `\n\n## Skill: <name>\n<instructions>` per attached skill — same
  convention as team agents, but **without** the file-delivery rules block
  that `engine._agent_system_prompt` appends for team runs (chat has no
  concept of a run workspace with artifacts).
- Workspace: `chat_stream` is given `os.path.join(WORKSPACES, "chat")` — a
  **single shared folder for every chat session**, not one per conversation
  (contrast with runs, which get `workspace/<run_id>`). If a chat agent has
  the `files` tool, its reads/writes land in that shared folder.
- Runs in the **Flask request thread** — the SSE generator calls
  `engine.chat_stream` directly, with no background thread or `RunManager`
  involved (unlike runs). A long chat generation occupies one of gunicorn's
  worker threads for its full duration.
- **No tool delegation.** Team runs fall back to a delegate model when the
  chosen model can't bind tools (`docs/features/teams-runs/`); chat does not
  — if the model rejects `bind_tools`, the raised error propagates and
  `app.py`'s wrapper appends a guidance suffix when the message contains
  "does not support tools", suggesting the user remove tools or switch to a
  team run.
- Tool loop bounded by the same `MAX_TOOL_ROUNDS` (5) constant as team runs.
- History persistence is **client-driven**: `Chat.jsx` calls
  `POST /api/chats` (new) or `PUT /api/chats/:id` (existing) after a turn
  finishes streaming, wrapped in a best-effort try/catch — the server never
  writes to `chats` on its own.

## Gotchas

- **Chat's SSE event set is not the same as runs'.** `docs/api.md` used to
  claim chat streams the identical `run_start/agent_start/token/tool_call/
  tool_result/agent_end/run_end/error` set as team runs — that was wrong.
  Chat only ever emits `token`, `tool_call`, `tool_result`, `done`, and
  `error`. Fixed here; if you're writing a client against `/api/chat`, don't
  copy the run-event handling verbatim.
- **All chats share one workspace folder** (`data/workspaces/chat`) — the
  `files` tool has no per-conversation isolation, unlike runs. Two chats
  using `write_file` with the same relative path will clobber each other.
- Selecting a non-tool-capable model with tools enabled produces a plain
  error, not a delegated fallback — this is intentional (see CLAUDE.md), but
  easy to mistake for a bug if you expect run-like delegation behavior.
- **Chat is very slow while the Fooocus image server is running**: the GPU
  coexistence guard forces Ollama to CPU-only, and Fooocus's resident SDXL
  eats most RAM — a 7B reply can take minutes or time out. Stop the image
  server (Models page) when you're done generating.
- **Deep link `#/chat/<personaId>`** (used by the Personas page's 💬
  buttons) starts a fresh conversation as that persona — it applies the
  persona and clears any open chat, so don't link to it from flows that
  expect to preserve the current conversation.
- Chat runs synchronously in the request thread; with gunicorn's 16 threads
  (per `docs/architecture.md`), many concurrent long chat streams can starve
  other requests. There is no per-chat cancellation endpoint — the client
  simply aborts its own `fetch` (`AbortController`), which stops rendering
  but does **not** signal the server to stop generating.
- Persistence is best-effort and client-triggered — closing the tab mid-turn
  or a network drop before the `PUT/POST /api/chats` call means that turn is
  lost from history even though tokens were already streamed to the user.

## How to verify

1. Open `#/chat`, pick a tool-capable model (`qwen2.5:7b`), send a message
   that needs a tool (e.g. "what's 12*7?" with `calculator` enabled) and
   confirm the tool line renders before the answer.
2. `curl -N -X POST localhost:5860/api/chat -H 'Content-Type: application/json' -d '{"agent":{"model":"qwen2.5:7b"},"messages":[{"role":"user","content":"hi"}]}'`
   and confirm the raw SSE frames are only `token`/`done` (add a tool for
   `tool_call`/`tool_result`, or a bad model for `error`).
3. Switch to a reasoning-only model with a tool enabled and confirm the
   friendly "can't call tools in chat" guidance message appears as an
   `error` event, not a silent failure.
4. Send a couple of messages, reload the page, and confirm the conversation
   appears in the history sidebar (`GET /api/chats`) with the right
   `message_count`; open it and confirm `GET /api/chats/<id>` returns the
   full message list.
5. Give the chat agent the `files` tool, write a file, start a second chat
   session, and confirm (per the shared-workspace gotcha) it can read the
   first chat's file back.
