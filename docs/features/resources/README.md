# AI News & Resources

A curated link store — AI news, local-LLM trainings, open-source tools — that
the user grows by hand or refreshes with a web-researching agent.

## Key files

| Path | Role |
|------|------|
| `resources.py` | `refresh(category)` runs a research agent (web_search/read_webpage), parses its JSON, de-dupes by URL; `get/set_prompt`, `get/set_model` |
| `storage.py` | `resources` table (UNIQUE url) + `list/add/delete_resource` |
| `app.py` | `/api/resources*` routes |
| `frontend/src/pages/Resources.jsx` | Category tabs, cards, refresh + manual add, prompt & model editor |

## API
- `GET /api/resources?category=` → `{resources, categories}`.
- `POST /api/resources {url, title?, category}` — add by hand (source=manual).
- `DELETE /api/resources/<id>`.
- `GET /api/resources/prompt?category=` → `{prompt, default, model}` where
  `model` is `{provider, model}` or `{}` when set to auto.
- `PUT /api/resources/prompt {category, prompt, provider?, model?}` — saves
  both. An empty/absent `model` clears the override back to auto-pick.
- `POST /api/resources/refresh {category, n, provider?, model?}` → runs the
  agent, stores new links, returns `{ok, found, added, model, provider}`.
  Blocks (~1-2 min on a 7B).

## How it works
- Three categories: `news`, `training`, `tools` (`resources.CATEGORIES`).
- The agent is a tool-capable model with web_search + read_webpage; the prompt
  asks for a JSON array of `{title, url, summary}`, parsed defensively
  (`_extract_items`). URLs must start with http; the table's UNIQUE(url)
  constraint de-dupes across refreshes.
- **Both the search prompt and the model are per-category and user-editable**
  (✏️ Search prompt & model). Precedence for the model: an explicit one in the
  refresh body > the category's saved choice (`storage` meta key
  `resource_model:<category>`, JSON `{provider, model}`) > auto-pick (first
  `qwen2.5:*`, else any Ollama model). Model lives next to the prompt because
  it is the same kind of knob: a model that is too small, or has no tool
  calling, skips the search and **invents plausible-looking links** instead —
  so the fix for a fabricating category is usually a bigger model, not a
  better prompt.
- Refresh is on-demand here; to keep it fresh automatically, create a
  **Schedule** whose prompt is a research task with a knowledge folder, or wire
  a scheduled job to `resources.refresh` (future).

## Gotchas
- A local 7B sometimes returns fewer/looser links than asked; `found` vs
  `added` shows how many were new. Bad JSON yields zero rather than an error.
- Needs internet (web_search); offline refreshes just add nothing.
- **A fabricated link is indistinguishable from a real one here** — nothing
  fetches the URL to confirm it resolves. The model picker is the mitigation,
  not a guarantee.
- The saved model is used verbatim; if you later delete that model from Ollama,
  refresh fails with a 404 naming it rather than silently falling back. Set the
  picker to Auto to recover.

## How to verify
- `POST /api/resources/refresh {category:"training"}` → confirms real links get
  stored (verified: 3 genuine local-LLM guides added, deduped by URL).
- Model plumbing without spending a real run: save a nonexistent model for a
  category, then refresh — the error must name *that* model, proving no silent
  fallback (verified: `model 'definitely-not-a-real-model:1b' not found`); a
  `model` in the refresh body must override it (verified: error named
  `override-model:7b` instead).
