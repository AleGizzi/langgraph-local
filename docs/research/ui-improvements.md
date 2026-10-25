# UI improvement suggestions

*2026-10-25 review of `frontend/src` (≈7.9k lines, 11 nav pages). Ordered by
value-for-effort. ✅ = done in this session; everything else is a proposal.*

## A. Working with models (biggest daily friction)

1. **Rich model picker** — `components/AgentFields.jsx: ModelSelect` is a bare
   `<select>` of 35+ names, used by agents, chat, wizard, flow canvas. Proposal:
   a searchable combobox that shows, per model, data the backend *already has*:
   - size + "fits in RAM now" (`sysinfo.memory_report().largest_model_fits_gb`)
   - 🔧 native tools (`engine._model_supports_tools` / catalog `capabilities`)
   - native context length (`/api/show` → `model_info.*.context_length`)
   - ● **loaded now** (`/api/ps`) — picking the resident model avoids a 30–90 s swap,
     the #1 hidden latency on this one-model-at-a-time machine
   - group by family, small→large (reuse `modes._family_size`)
   One `GET /api/models/rich` that joins these, cached ~10 s.
2. **"Model swap" warning on Run** — when a team uses N distinct models, show
   "this run will load 3 models (~2 min of swapping)". Add a one-click "use one
   model for all agents" option. The data is the team JSON plus `/api/ps`.
3. ✅ **Decision models are separated** — `list_models()` now returns them under
   `decision` (they can't chat); the Models page shows them in their own 🎯 group, and the
   catalog has a 🎯 Decision category. Previously they would have appeared in every
   chat picker and failed.
4. **Hermes panel** (Setup page tab) — status of `~/.hermes` (version, configured
   model, its native ctx ≥ 64k ✔/✘, gateway up), plus a "send to Hermes" button
   on Chat that hands the current message to the `hermes_agent` tool. See
   [hermes.md](hermes.md). Backend: `hermes --version`, parse `~/.hermes/config.yaml`.
5. **Single-store indicator** — Setup → Ollama already shows `models_dir`; add a
   warning badge when more than one store holds blobs or when LM Studio links are
   broken (the exact state found today), with a "re-link" button running
   `deploy/link-ollama-to-lmstudio.py`.
6. **Pull queue with disk budget** — the catalog's one-click install pulls one
   model at a time and shows no remaining-disk check. Show free space
   (`shutil.disk_usage`) before a pull and refuse when it would leave < 10 %.

## B. Navigation & information architecture

7. **11 flat nav items is a lot.** Group into *Build* (Agents, Skills & Tools,
   Knowledge), *Run* (Chat, Runs, Schedules), *Models* (Models, Setup), and a
   footer (AI News, Settings, Guide). Setup and Settings both answer "is my machine
   OK?" — merge Settings' hardware/recommendations into Setup.
8. **Command palette (Ctrl+K)** — jump to a team/run/note/model by name. The app
   has hash routing and every list already loads via `api()`; a palette is ~150
   lines with no new dependency.
9. **Persistent status bar** — loaded model, RAM free, active runs, Ollama
   up/down. Today this is scattered across banners (`App.jsx` health checks),
   FreeMemory and Runs tiles.

## C. Runs & feedback

10. **Show prefill vs. generation time per step** in `Timeline.jsx`. On this CPU,
    prefill dominates (Hermes: 4.5 min cold vs 6 s warm). Ollama returns
    `prompt_eval_duration` / `eval_duration`; surfacing them tells the user *why* a
    step was slow (long context vs. slow model) and makes the scratchpad budget
    (`settings.context_budget`) tunable with evidence.
11. **Router explanation chip** — when the auto-router picks a model, show
    `kind · model · p=0.93 (tev1)` so users see the classification and can override.
    `router.classify` now returns the decision probability in `reason`.
12. **Decision-log → recommendations** — the Agents dashboard's "Model
    performance" table already has outcomes per model; add a "suggest swap" hint when a
    smaller model has an equal pass rate (it is free speed).

## D. Polish & accessibility (continuing the July hardening)

13. `ImageGen.jsx` is 1,222 lines — split into picker / queue / gallery
    components; it's the slowest page to change safely.
14. Replace emoji-only buttons with icon + visible text label on narrow screens
    (several header buttons are emoji + text already; tabs and pills are not consistent).
15. Mobile: the flow canvas and pixel studio are desktop-only by nature, but the
    Chat and Runs pages could work on a phone over the WireGuard VPN with a
    responsive pass (sidebar → bottom bar under 700 px).
