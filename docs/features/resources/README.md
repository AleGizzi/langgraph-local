# AI News & Resources

A curated link store — AI news, local-LLM trainings, open-source tools — that
the user grows by hand or refreshes with a web-researching agent.

## Key files

| Path | Role |
|------|------|
| `resources.py` | `refresh(category)` runs a research agent (web_search/read_webpage), parses its JSON, de-dupes by URL |
| `storage.py` | `resources` table (UNIQUE url) + `list/add/delete_resource` |
| `app.py` | `/api/resources*` routes |
| `frontend/src/pages/Resources.jsx` | Category tabs, cards, refresh + manual add |

## API
- `GET /api/resources?category=` → `{resources, categories}`.
- `POST /api/resources {url, title?, category}` — add by hand (source=manual).
- `DELETE /api/resources/<id>`.
- `POST /api/resources/refresh {category, n}` → runs the agent, stores new
  links, returns `{ok, found, added, model}`. Blocks (~1-2 min on a 7B).

## How it works
- Three categories: `news`, `training`, `tools` (`resources.CATEGORIES`).
- The agent is a tool-capable model (qwen2.5 default) with web_search +
  read_webpage; the prompt asks for a JSON array of `{title, url, summary}`,
  parsed defensively (`_extract_items`). URLs must start with http; the table's
  UNIQUE(url) constraint de-dupes across refreshes.
- Refresh is on-demand here; to keep it fresh automatically, create a
  **Schedule** whose prompt is a research task with a knowledge folder, or wire
  a scheduled job to `resources.refresh` (future).

## Gotchas
- A local 7B sometimes returns fewer/looser links than asked; `found` vs
  `added` shows how many were new. Bad JSON yields zero rather than an error.
- Needs internet (web_search); offline refreshes just add nothing.

## How to verify
`POST /api/resources/refresh {category:"training"}` → confirms real links get
stored (verified: 3 genuine local-LLM guides added, deduped by URL).
