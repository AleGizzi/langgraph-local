# Documentation

The maintainer's library for Local Agents Studio. Start at the top and go deeper as
needed.

| Doc | Read it when… |
|-----|----------------|
| [`../CLAUDE.md`](../CLAUDE.md) | **Start here.** Mental model, repo map, vocabulary, conventions, sharp edges. |
| [`architecture.md`](architecture.md) | You need to understand *how it works* — the run lifecycle, event/SSE model, the engine, concurrency, persistence, catalog/installer. |
| [`extending.md`](extending.md) | You're *adding* something — a tool, skill, topology, provider, route, or page. Step-by-step recipes. |
| [`api.md`](api.md) | You need the REST/SSE reference — every endpoint, params, response shape. |
| [`frontend.md`](frontend.md) | You're working in the React SPA — pages, components, state, streaming, theming. |
| [`operations.md`](operations.md) | You're running/deploying it — native, Docker, env vars, data layout, backup, troubleshooting. |
| [`knowledge-base.md`](knowledge-base.md) | You're wiring the knowledge vault to Obsidian/Logseq or configuring where it lives. |
| [`image-generation.md`](image-generation.md) | You're setting up local image generation (Fooocus) or using the `generate_image` tool. |

## For AI agents maintaining this repo

`CLAUDE.md` is written for you too. The essentials: all routes are in `app.py`; the
run engine is `engine.py`; verify changes with a **real model run** (`qwen2.5:7b`), not
just imports; parse all model output defensively; never hardcode colors in the frontend
(dark mode uses CSS variables). Clean up test artifacts when you're done.
