# Documentation index

**How to use this:** find the feature you're touching in the table, read *that
folder's README* (self-sufficient: files, API, mechanics, gotchas, verification).
Only read the cross-cutting docs when your change spans features. Don't preload
everything — that's the point of this structure.

## Feature map — "I'm working on…"

| …this | Read | Owns (code) |
|-------|------|-------------|
| Teams, topologies, runs, streaming, file delivery, **tool delegation**, team wizard | [`features/teams-runs/`](features/teams-runs/README.md) | `engine.py`, `runmanager.py`, teams/runs routes, `Timeline.jsx`, `TeamEditor.jsx` |
| Visual pipeline canvas | [`features/flow-canvas/`](features/flow-canvas/README.md) | `FlowEditor.jsx`, `GraphEditor.jsx`, `_validate_graph` |
| GBA pixel view | [`features/pixel-studio/`](features/pixel-studio/README.md) | `PixelStudio.jsx` |
| Chat page + history | [`features/chat/`](features/chat/README.md) | `engine.chat_stream`, `/api/chat(s)`, `Chat.jsx` |
| Personas | [`features/personas/`](features/personas/README.md) | personas CRUD, `Personas.jsx`, `AgentFields.jsx` |
| Skills, tools, AI wizards | [`features/skills-tools/`](features/skills-tools/README.md) | `tools.py`, `wizard.py`, `Toolbox.jsx`, `WizardPanel.jsx` |
| Knowledge vault (Obsidian) | [`features/knowledge/`](features/knowledge/README.md) | `knowledge.py`, `Knowledge.jsx`, knowledge tools |
| Scheduled agent tasks (cron) | [`features/schedules/`](features/schedules/README.md) | `scheduler.py`, `schedules` tables, `Schedules.jsx` |
| Model catalog, installs, hardware assessment, provider setup | [`features/models-catalog/`](features/models-catalog/README.md) | `catalog.py`, `sysinfo.py`, `installer.py`, Models/Settings/Setup pages |
| Image generation (Fooocus) | [`features/image-generation/`](features/image-generation/README.md) | `imagegen.py`, `ImageGen.jsx` |

## Cross-cutting docs

| Doc | When |
|-----|------|
| [`architecture.md`](architecture.md) | You need the system-wide picture: run lifecycle, SSE fan-out, engine, concurrency, persistence. |
| [`extending.md`](extending.md) | Adding a tool / skill / hyperparameter / topology / provider / route / page. |
| [`operations.md`](operations.md) | Running, Docker, env vars, data layout, backup, troubleshooting. |
| [`handover.md`](handover.md) | Project state, roadmap, non-negotiables — read before big decisions. |

## Keeping documentation current (rules, not suggestions)

1. **Same-commit rule.** A change to a feature updates that feature's README in
   the *same commit*. API shape changed → its `## API` section changes with it.
2. **One home per fact.** Route shapes live in the owning feature README —
   nowhere else. Cross-cutting docs link to feature docs instead of restating.
3. **New feature → new folder** here + a row in the table above + a line in the
   root `README.md` feature list. Copy the README template from any existing
   feature folder (What it is / Key files / API / How it works / Gotchas /
   How to verify).
4. **Gotchas are append-mostly.** When a real bug taught you something, record
   it in the feature's `## Gotchas` — that's institutional memory. Don't delete
   entries unless the constraint truly no longer exists.
5. **CLAUDE.md stays lean** (≤ ~60 lines). It's the entry point that routes here;
   details belong in feature docs. If you're adding paragraphs to CLAUDE.md,
   you're putting them in the wrong place.
6. **Verify sections must stay executable.** If the verification steps in a
   README no longer work, fixing them is part of your change.
