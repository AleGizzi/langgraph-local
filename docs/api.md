# Local Agents Studio — REST API Reference

**Base URL:** `/api` (same-origin, no authentication, single-user)

All responses are JSON unless noted otherwise. The app uses SQLite for persistence, so all writes are immediately durable.

---

## System & Health

### GET /api/health

Health check with provider availability.

**Response:**
```json
{
  "ok": true,
  "providers": {
    "ollama": {
      "installed": bool,
      "running": bool,
      "version": "string|null"
    },
    "lmstudio": {
      "installed": bool,
      "running": bool,
      "version": "string|null"
    }
  }
}
```

### GET /api/system

Complete system report: hardware, local installations, setup guides, and model assessment.

**Response:**
```json
{
  "hardware": {
    "cpu": "string",
    "cores": int,
    "ram_total_gb": float,
    "ram_available_gb": float,
    "gpu": {
      "name": "string",
      "vram_total_gb": float|null,
      "vram_free_gb": float|null,
      "vendor": "nvidia|unknown"
    } | null,
    "disk_free_gb": float,
    "os": "string"
  },
  "installations": {
    "ollama": {
      "name": "Ollama",
      "installed": bool,
      "running": bool,
      "url": "string",
      "port": int,
      "binary": "string|null",
      "version": "string|null",
      "models_dir": "string|null",
      "models_size_gb": float|null,
      "service": "string|null"
    },
    "lmstudio": {
      "name": "LM Studio",
      "installed": bool,
      "running": bool,
      "url": "string",
      "port": int,
      "binary": "string|null",
      "version": "string|null",
      "models_dir": "string|null",
      "models_size_gb": float|null,
      "home": "string|null",
      "app": "string|null",
      "service": "string|null"
    }
  },
  "guides": {
    "ollama": {
      "title": "string",
      "site": "string",
      "steps": [{"text": "string", "cmd": "string|null"}]
    },
    "lmstudio": {...}
  },
  "assessment": {
    "installed": [
      {
        "name": "string",
        "provider": "ollama",
        "size_gb": float,
        "params_b": float|null,
        "quant": "string|null",
        "verdict": "great|ok|tight|no",
        "verdict_label": "string",
        "est_tok_s": float|null
      }
    ],
    "parallel": {
      "capacity": int,
      "reason": "string"
    },
    "notes": ["string"]
  },
  "docker": bool
}
```

### POST /api/setup/install

Install a provider (Ollama or LM Studio).

**Request body:**
```json
{
  "provider": "ollama|lmstudio"
}
```

**Response:**
```json
{
  "success": bool,
  "message": "string|null"
}
```

---

## Models & Catalog

### GET /api/models

List all models available from installed providers (Ollama and/or LM Studio).

**Response:**
```json
{
  "ollama": ["model:tag", "model:tag"],
  "lmstudio": ["model:tag"]
}
```

### GET /api/catalog

Full model catalog from ollama.com with suitability assessments and dream-team recommendations.

**Query params:**
- (none)

**Response:**
```json
{
  "fetched_at": float|null,
  "source": "ollama.com|builtin",
  "refreshing": bool,
  "error": "string|null",
  "models": [
    {
      "name": "string",
      "base": "string",
      "description": "string",
      "capabilities": ["string"],
      "pulls": float,
      "pulls_label": "string",
      "size_gb": float|null,
      "params_b": float|null,
      "exact": bool,
      "verdict": "great|ok|tight|no|unknown",
      "verdict_label": "string",
      "est_tok_s": float|null,
      "installed": bool,
      "categories": ["general|coding|thinking|vision|agents|fast"],
      "ranks": {"category": int}
    }
  ],
  "summary": {
    "total": int,
    "runnable": int,
    "sweet_spot": "string|null"
  },
  "dream_team": [
    {
      "category": "string",
      "icon": "string",
      "label": "string",
      "model": "string",
      "size_gb": float,
      "verdict": "great|ok|tight|no",
      "est_tok_s": float|null,
      "installed": bool,
      "image": bool|null,
      "runner": "string|null",
      "reason": "string"
    }
  ],
  "categories": {
    "general": {"icon": "string", "label": "string"},
    ...
  },
  "image": {
    "models": [
      {
        "name": "string",
        "disk_gb": float,
        "min_vram_gb": int,
        "runner": "string",
        "tag": "string",
        "description": "string",
        "verdict": "great|ok|tight|no",
        "verdict_label": "string"
      }
    ],
    "setup": {...},
    "best": {...} | null,
    "runnable_count": int
  }
}
```

### POST /api/catalog/refresh

Kick off a background refresh of the model catalog from ollama.com (no blocking).

**Response:**
```json
{
  "started": bool
}
```

### GET /api/params

Get available model parameter specifications (temperature, top_p, etc.).

**Response:**
```json
[
  {
    "key": "string",
    "label": "string",
    "min": float,
    "max": float,
    "step": float,
    "default": float,
    "hint": "string"
  }
]
```

---

## Install/Setup

### POST /api/install

Start a model installation (download + pull into Ollama or LM Studio).

**Request body:**
```json
{
  "provider": "ollama|lmstudio",
  "model": "model:tag"
}
```

**Response:**
```json
{
  "provider": "string",
  "model": "string",
  "started": bool,
  "status": "downloading|pulling|done|error",
  "progress": {
    "total": int,
    "completed": int,
    "percent": float
  } | null,
  "error": "string|null"
}
```

### GET /api/install/status

Get status of all active and recent model installations.

**Response:**
```json
{
  "ollama": [
    {
      "model": "string",
      "status": "downloading|pulling|done|error",
      "progress": {"total": int, "completed": int, "percent": float} | null,
      "error": "string|null"
    }
  ],
  "lmstudio": [...]
}
```

### POST /api/install/cancel

Cancel an ongoing model installation.

**Request body:**
```json
{
  "provider": "ollama|lmstudio",
  "model": "model:tag"
}
```

**Response:**
```json
{
  "cancelled": bool
}
```

---

## Tools

Tools are reusable actions agents can invoke. Builtin tools: `calculator`, `current_datetime`, `http_get`, `files`, `knowledge`. Custom tools live in `custom_tools/*.py` files.

### GET /api/tools

Full tool catalog: builtin, custom, and file metadata.

**Response:**
```json
{
  "builtin": [
    {
      "name": "calculator|current_datetime|http_get|files|knowledge",
      "description": "string"
    }
  ],
  "custom": [
    {
      "name": "string",
      "file": "filename.py",
      "description": "string (up to 200 chars)"
    }
  ],
  "files": [
    {
      "file": "filename.py",
      "tools": ["tool_name"],
      "error": "string|null"
    }
  ],
  "template": "string (Python code template for new custom tools)"
}
```

### GET /api/tools/files/<filename>

Read a custom tool file (filename validated: `[A-Za-z0-9_\-]+\.py`).

**Response:**
```json
{
  "file": "string",
  "code": "string"
}
```

Returns 404 if file not found.

### PUT /api/tools/files/<filename>

Create or update a custom tool file. Immediately reloaded and validated.

**Request body:**
```json
{
  "code": "string (Python code with @tool functions)"
}
```

**Response:**
```json
{
  "file": "string",
  "loaded": ["tool_name"],
  "error": "string|null"
}
```

If `error` is set, `loaded` may be empty (file has syntax/import issues). If `error` is null, the tools in `loaded` are available immediately.

### DELETE /api/tools/files/<filename>

Delete a custom tool file.

**Response:**
```json
{
  "ok": true
}
```

---

## Wizard

AI-assisted code generation for custom skills and tools. Uses a local LLM to draft implementations based on user requests.

### POST /api/wizard

Generate a draft skill, tool, or entire team from a natural-language description.

**Request body:**
```json
{
  "kind": "skill|tool|team",
  "request": "string (user description, e.g. 'a PMO orchestrator with devops and qa teams')",
  "provider": "ollama|lmstudio (default: ollama)",
  "model": "string (required, e.g. 'qwen2.5:7b')",
  "current": "object|null (existing skill/team draft, for refinement)",
  "current_code": "string|null (existing tool code, for refinement)",
  "feedback": "string|null (user feedback on a draft)"
}
```

**Response:** `{"kind": ..., "draft": ...}` where `draft` is:
- `skill` → `{name, icon, description, instructions}`
- `tool` → `{code, tools, error, filename_suggestion}` (code is load-validated
  with one auto-fix round)
- `team` → a full team object `{name, icon, description, topology, settings,
  agents[], graph?}` — normalized server-side (models/tools/skills validated
  against what exists, unique agent names, topology repaired, graph gets
  auto-positions or degrades to pipeline if broken). Load it into the team
  editor for review; saving goes through the normal `POST /api/teams`
  validation.

**Errors:**
- 400 if `kind` not in `["skill", "tool", "team"]` or no `request` / `model`
- 502 if LLM generation fails

---

## Skills

Reusable instruction sets (system prompts) agents can apply. Each skill has a name, icon, description, and instructions.

### GET /api/skills

List all skills (builtin and user-created).

**Response:**
```json
[
  {
    "id": int,
    "name": "string",
    "icon": "string (emoji, up to 8 chars)",
    "description": "string",
    "instructions": "string",
    "builtin": bool
  }
]
```

### POST /api/skills

Create a new skill.

**Request body:**
```json
{
  "name": "string (required, e.g. 'Strict Analyzer')",
  "icon": "string (emoji, default: '✨')",
  "description": "string",
  "instructions": "string (required, e.g. 'Be critical and thorough...')"
}
```

**Response:** same as GET /api/skills item (with assigned `id`)

### PUT /api/skills/<int:sid>

Update a skill by id.

**Request body:** same as POST

**Response:** updated skill object

Returns 404 if skill not found.

### DELETE /api/skills/<int:sid>

Delete a skill by id.

**Response:**
```json
{
  "ok": true
}
```

---

## Personas

Pre-configured agent personalities with a model, provider, tools, and skills. Think of a persona as a lightweight agent template.

### GET /api/personas

List all personas (builtin and user-created).

**Response:**
```json
[
  {
    "id": int,
    "name": "string",
    "icon": "string (emoji)",
    "role": "string (e.g. 'Researcher')",
    "description": "string",
    "system_prompt": "string",
    "provider": "ollama|lmstudio",
    "model": "string (e.g. 'qwen2.5:7b')",
    "params": {
      "temperature": float (0–2),
      "top_p": float,
      ...
    },
    "tools": ["calculator", "http_get"],
    "skills": ["Strict Analyzer"],
    "builtin": bool
  }
]
```

### POST /api/personas

Create a new persona.

**Request body:**
```json
{
  "name": "string (required)",
  "icon": "string (emoji, default: '🧑')",
  "role": "string",
  "description": "string",
  "system_prompt": "string",
  "provider": "ollama|lmstudio (default: ollama)",
  "model": "string (required)",
  "params": {
    "temperature": float (clamped 0–2),
    "top_p": float,
    ...
  },
  "tools": ["tool_name"],
  "skills": ["skill_name"]
}
```

**Response:** persona object with assigned `id`

Tools and skills are validated against available names; invalid ones are silently dropped.

### PUT /api/personas/<int:pid>

Update a persona by id.

**Request body:** same as POST

**Response:** updated persona object

Returns 404 if persona not found.

### DELETE /api/personas/<int:pid>

Delete a persona by id.

**Response:**
```json
{
  "ok": true
}
```

---

## Teams

Teams are multi-agent ensembles running on a graph topology. Four topologies supported: `single`, `pipeline`, `supervisor`, `graph`.

### GET /api/teams

List all teams.

**Response:**
```json
[
  {
    "id": int,
    "name": "string",
    "icon": "string (emoji)",
    "description": "string",
    "topology": "single|pipeline|supervisor|graph",
    "agents": [
      {
        "name": "string",
        "model": "string",
        "provider": "ollama|lmstudio",
        "temperature": float (0–2),
        "params": {...},
        "tools": ["tool_name"],
        "skills": ["skill_name"]
      }
    ],
    "settings": {
      "quality_loop": bool (default: false),
      "parallel": bool (default: false),
      "max_revisions": int (0–5, default: 2),
      "max_steps": int (1–20, default: 8)
    },
    "graph": {
      "nodes": [{"id": "string", "agent": "string (agent name)"}],
      "edges": [{"source": "string", "target": "string"}],
      "positions": {"node_id": {"x": float, "y": float}}
    } | null (only for topology: "graph"),
    "created_at": float (unix timestamp),
    "updated_at": float
  }
]
```

### POST /api/teams

Create a new team.

**Request body:**
```json
{
  "name": "string (required, e.g. 'Research Squad')",
  "icon": "string (emoji, default: '🤖')",
  "description": "string",
  "topology": "single|pipeline|supervisor|graph (default: pipeline)",
  "agents": [
    {
      "name": "string (required, unique per team)",
      "model": "string (required)",
      "provider": "ollama|lmstudio (default: ollama)",
      "temperature": float (clamped 0–2, default: 0.7),
      "params": {...},
      "tools": ["tool_name"],
      "skills": ["skill_name"]
    }
  ],
  "settings": {
    "quality_loop": bool,
    "parallel": bool,
    "max_revisions": int (clamped 0–5),
    "max_steps": int (clamped 1–20)
  },
  "graph": {
    "nodes": [{"id": "string", "agent": "agent_name"}],
    "edges": [{"source": "string", "target": "string"}],
    "positions": {"node_id": {"x": float, "y": float}}
  } (required only if topology: "graph")
}
```

**Validation:**
- At least one agent required
- `supervisor` topology requires 2+ agents (1 supervisor + 1+ workers)
- For `graph` topology: nodes must be acyclic, reachable from "start", at least one edge to "end", no duplicate ids
- Tools and skills validated; invalid entries silently dropped

**Response:** team object with assigned `id`

### GET /api/teams/<int:team_id>

Fetch a single team by id.

**Response:** team object

Returns 404 if not found.

### PUT /api/teams/<int:team_id>

Update a team by id.

**Request body:** same as POST /api/teams

**Response:** updated team object

Returns 404 if not found.

### DELETE /api/teams/<int:team_id>

Delete a team by id.

**Response:**
```json
{
  "ok": true
}
```

---

## Runs

Runs are executions of a team on a task. They stream events as agents work.

### POST /api/teams/<int:team_id>/runs

Start a new run for a team.

**Request body:**
```json
{
  "task": "string (required, e.g. 'Analyze the latest earnings report')"
}
```

**Response:**
```json
{
  "run_id": int
}
```

Returns 404 if team not found.

### GET /api/runs

List all runs (optionally filtered by team).

**Query params:**
- `team_id` (optional int): filter to a specific team

**Response:**
```json
[
  {
    "id": int,
    "team_id": int,
    "team_name": "string",
    "task": "string",
    "status": "running|done|error",
    "final": "string|null (agent response / output)",
    "error": "string|null (error message if status: 'error')",
    "created_at": float (unix timestamp),
    "finished_at": float|null
  }
]
```

### GET /api/runs/<int:run_id>

Fetch a single run by id, including all persisted events.

**Response:**
```json
{
  "id": int,
  "team_id": int,
  "team_name": "string",
  "task": "string",
  "status": "running|done|error",
  "final": "string|null",
  "error": "string|null",
  "created_at": float,
  "finished_at": float|null,
  "events": [
    {
      "seq": int (event sequence number),
      "type": "run_start|agent_start|token|tool_call|tool_result|decision|agent_end|run_end|error",
      "agent": "string|null (agent name, null for run_start/run_end)",
      "content": "string|null (token text, tool args/result, or final output)",
      "meta": {
        "status": "string|null (for run_end: 'done' or 'error')",
        "reason": "string|null",
        ...
      } | null
    }
  ]
}
```

Returns 404 if not found.

### POST /api/runs/<int:run_id>/stop

Stop a running run.

**Response:**
```json
{
  "stopped": bool (true if run was running and stopped; false if already finished)
}
```

### GET /api/runs/<int:run_id>/events

**Server-Sent Events (SSE) stream.**

Subscribe to live events from a run. Replays persisted events first (for reconnection / finished runs), then streams live events as they happen. Keep-alive sent every 25s.

**Event types (in `event: type` followed by JSON `data: {...}`)**

- **`run_start`** – Run has begun
  ```json
  {"type": "run_start", "content": "string|null"}
  ```

- **`agent_start`** – Agent begins work
  ```json
  {"type": "agent_start", "agent": "string", "content": "string (task/prompt)"}
  ```

- **`token`** – LLM token streamed
  ```json
  {"type": "token", "agent": "string", "content": "string (single token)"}
  ```

- **`tool_call`** – Agent invokes a tool
  ```json
  {"type": "tool_call", "agent": "string", "content": "string (JSON-serialized call)"}
  ```

- **`tool_result`** – Tool result returned
  ```json
  {"type": "tool_result", "agent": "string", "content": "string (result text)"}
  ```

- **`decision`** – Routing decision (e.g., supervisor choosing next agent)
  ```json
  {"type": "decision", "content": "string (decision explanation)"}
  ```

- **`agent_end`** – Agent finishes
  ```json
  {"type": "agent_end", "agent": "string", "content": "string (agent output)"}
  ```

- **`run_end`** – Run completed
  ```json
  {"type": "run_end", "content": "string (final output)", "meta": {"status": "done|error", "replay": bool}}
  ```

- **`error`** – Error occurred
  ```json
  {"type": "error", "content": "string (error message)"}
  ```

Each event has:
- `seq` – monotonic sequence number
- `type` – event type
- `agent` – agent name (null for run-level events)
- `content` – event payload
- `meta` – additional metadata (JSON object or null)

All persisted events have `seq` ≥ 1; live events may have `seq` but are not de-duplicated if `seq` already seen (except tokens). Connection closes after `run_end`.

### GET /api/runs/<int:run_id>/artifacts

List output files generated by a run (workspace artifacts).

**Response:**
```json
[
  {
    "path": "string (relative to run workspace)",
    "size": int (bytes)
  }
]
```

Sorted by path.

### GET /api/runs/<int:run_id>/artifacts/<path:relpath>

Download a run artifact by path (with path traversal protection).

**Response:** plain text file (mimetype: `text/plain`)

---

## Chat

One-shot conversational AI endpoint (no team/run overhead). Streams responses as tokens and structured events.

### POST /api/chat

**Server-Sent Events (SSE) stream.**

Start a chat session and stream responses back. The same event types apply as runs: `run_start`, `agent_start`, `token`, `tool_call`, `tool_result`, `agent_end`, `run_end`, `error`.

**Request body:**
```json
{
  "agent": {
    "model": "string (required, e.g. 'qwen2.5:7b')",
    "provider": "ollama|lmstudio (default: ollama)",
    "temperature": float,
    "params": {...},
    "tools": ["tool_name"],
    "skills": ["skill_name"]
  },
  "messages": [
    {"role": "user|assistant", "content": "string"}
  ]
}
```

**Validation:**
- `agent.model` required
- `messages` required (at least one message)

**Response (SSE stream):**

Same event types as `/api/runs/<id>/events`. Ends with `run_end` or `error`.

---

## Chats (History)

Chat sessions are stored separately from runs. Users can save, retrieve, and manage chat histories.

### GET /api/chats

List all saved chats (most recent first, limited to 100).

**Response:**
```json
[
  {
    "id": int,
    "title": "string",
    "agent": {
      "model": "string",
      "provider": "string",
      "temperature": float,
      "params": {...},
      "tools": ["string"],
      "skills": ["string"]
    },
    "message_count": int,
    "created_at": float,
    "updated_at": float
  }
]
```

### POST /api/chats

Create a new chat session.

**Request body:**
```json
{
  "title": "string (auto-derived from first user message if empty)",
  "agent": {
    "model": "string",
    "provider": "string",
    "temperature": float,
    "params": {...},
    "tools": ["string"],
    "skills": ["string"]
  },
  "messages": [
    {"role": "user|assistant", "content": "string"}
  ]
}
```

**Response:**
```json
{
  "id": int,
  "title": "string",
  "agent": {...},
  "message_count": int,
  "created_at": float,
  "updated_at": float
}
```

### GET /api/chats/<int:cid>

Fetch a single chat with full message history.

**Response:**
```json
{
  "id": int,
  "title": "string",
  "agent": {...},
  "messages": [
    {"role": "user|assistant", "content": "string"}
  ],
  "created_at": float,
  "updated_at": float
}
```

Returns 404 if not found.

### PUT /api/chats/<int:cid>

Update a chat (title, agent, messages).

**Request body:** same as POST /api/chats

**Response:** updated chat object

Returns 404 if not found.

### DELETE /api/chats/<int:cid>

Delete a chat session.

**Response:**
```json
{
  "ok": true
}
```

---

## Knowledge

Shared knowledge base: a vault of Markdown notes with YAML frontmatter that agents can search, read, and contribute to. The folder is a valid Obsidian/Logseq vault.

### GET /api/knowledge

List notes or search the knowledge base.

**Query params:**
- `q` (optional string): search query; if provided, returns search results instead of note list

**Response (no search):**
```json
{
  "stats": {
    "dir": "string (knowledge base path)",
    "count": int (total notes),
    "bytes": int (total storage)
  },
  "notes": [
    {
      "path": "string (vault-relative path, e.g. 'research/topic.md')",
      "title": "string",
      "tags": ["string"],
      "size": int (bytes),
      "modified": float (unix timestamp)
    }
  ]
}
```

**Response (with search):**
```json
{
  "stats": {...},
  "results": [
    {
      "path": "string",
      "title": "string",
      "snippet": "string (context around match, ~200 chars)"
    }
  ]
}
```

### GET /api/knowledge/note

Fetch a single note by path.

**Query params:**
- `path` (required string): vault-relative path (e.g., `research/my-note.md`)

**Response:**
```json
{
  "path": "string",
  "content": "string (full Markdown, with or without frontmatter)"
}
```

Returns 404 if not found.

### POST /api/knowledge/note

Create a new note (with auto-generated filename).

**Request body:**
```json
{
  "title": "string (required, e.g. 'Meeting Notes')",
  "content": "string (required, Markdown)"
}
```

**Response:**
```json
{
  "path": "string (vault-relative path assigned to the note)"
}
```

Notes are saved to `data/knowledge/notes/YYYY-MM-DD-<slugified-title>.md` with frontmatter: `title`, `created`, `tags: [manual]`, `source: manual`.

---

## Static Files

### GET /

Serves the frontend (React/Vite SPA at `static/dist/index.html`).

### GET /static/...

Serves frontend assets (JS, CSS, etc.) from `static/dist/`.
