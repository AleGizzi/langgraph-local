# Models & Catalog
> Part of Local Agents Studio. Read docs/index.md for the doc map.

## What it is

Model discovery and "can my PC run this?" tooling: live model discovery from
the running providers, a scraped Ollama-library catalog with per-model
suitability verdicts and use-case categories, hardware assessment, a "dream
team" recommender, model installation with progress, and first-run provider
install (Ollama/LM Studio). No AI is involved anywhere in this feature — it's
all HTTP scraping/parsing and arithmetic heuristics.

## Key files

| Path | Role |
|------|------|
| `catalog.py` | Scrapes `ollama.com/library`, caches to `data/model_catalog.json`, categorizes/ranks models, builds the dream team, assesses curated image-gen models, always-merges a curated **uncensored** list (`UNCENSORED_MODELS`). |
| `sysinfo.py` | Hardware detection (CPU/RAM/GPU), provider install detection, per-model suitability verdicts, parallel-capacity estimate. |
| `installer.py` | Model pulls (Ollama native `/api/pull`, LM Studio `lms` CLI) and first-run provider install (Ollama user-level from GitHub releases, LM Studio AppImage download). |
| `providers.py` | `list_models()` / `provider_status()` — the live "what's actually loaded" discovery this feature displays. |
| `app.py` | `/api/models`, `/api/health`, `/api/system`, `/api/setup/install`, `/api/catalog*`, `/api/install*`, `/api/params`. |
| `frontend/src/pages/Models.jsx` | Discovered models + catalog table + embeds `ImageGen` (install/run Fooocus — see `docs/features/image-generation/`). |
| `frontend/src/pages/Settings.jsx` | Hardware, parallel capacity, installed-model verdicts, dream team, full catalog, `ImageModels` (curated image-gen VRAM table). |
| `frontend/src/pages/Setup.jsx` | Provider install wizards + install guides. |
| `frontend/src/components/CatalogTable.jsx` | Searchable/filterable catalog table, install buttons + progress, dream-team cards. |
| `frontend/src/components/ImageModels.jsx` | Read-only table of `catalog.image_models()` results (curated SD/FLUX list vs. this GPU — informational only, doesn't install anything). |

## API

- `GET /api/models` → `providers.list_models()`:
  `{ollama: ["model:tag", ...], lmstudio: [...], errors: {ollama?: "...", lmstudio?: "..."}}`.
  The `errors` key (per-provider failure string when unreachable) is real
  but was missing from the old `docs/api.md` schema — fixed here.
- `GET /api/health` → `{ok, providers: {ollama: {up, url, models},
  lmstudio: {...}}}`.
- `GET /api/system` → `sysinfo.full_report()` plus a `docker` bool:
  `{hardware, installations, guides, assessment, docker}` (see `sysinfo.py`
  for the exact per-field shape — stable, matches `docs/api.md`'s existing
  `/api/system` schema).
- `POST /api/setup/install {provider: "ollama"|"lmstudio"}` →
  `installer.install_provider()`: `{ok, error}`. Refused inside Docker
  (`{ok:false, error:"Running in Docker…"}"}` — Ollama is the bundled
  service there).
- `GET /api/catalog` → cached+enriched catalog (verified against `catalog.py`
  + `app.py`'s `catalog_get`; shape matches `docs/api.md`'s existing
  `/api/catalog` schema — `models[]` with verdict/est_tok_s/installed/
  categories/ranks, `dream_team[]`, `categories`, `summary`, `image`).
- `POST /api/catalog/refresh` → `{started: bool}` (non-blocking background
  refresh; `false` if a refresh is already running).
- `GET /api/params` → `providers.PARAM_SPECS` as
  `[{key, label, min, max, step, default, hint}]`.
- `POST /api/install {provider, model}` → `installer.start()`: `{ok:true}`
  or `{ok:false, error:"already installing"}`.
- `GET /api/install/status` → `installer.status_all()`, keyed
  `"<provider>::<model>"` for model pulls and `"setup::<provider>"` for
  first-run provider installs — one shared dict for both.
- `POST /api/install/cancel {provider, model}` → `{cancelled: bool}`.

## How it works

- **`catalog.py`** scrapes `ollama.com/library` with plain HTTP + regex
  (`fetch_library_index`, one request lists every model with capability
  tags/sizes/pulls), then fetches exact per-tag sizes
  (`fetch_exact_tags`) for the top `EXACT_SIZE_TOP_N` (45) models by pulls.
  Results cache to `data/model_catalog.json`; `get_catalog()` auto-refreshes
  (non-blocking) when the cache is older than `MAX_AGE_DAYS` (7) — checked
  both at app startup (`app.py` calls `catalog.get_catalog(auto_refresh=True)`)
  and on every `GET /api/catalog`. `BUILTIN_SNAPSHOT` (13 hardcoded models)
  is the offline fallback when there's no cache and no network.
- **Categorization** (`classify`): heuristic regex over capability tags +
  name/description text → `coding`/`thinking`/`vision`/`agents`/`fast`/
  `uncensored`/`general` (not derived from the model weights themselves). The
  `uncensored` tag comes from `_UNCENSORED_RE` (matches `dolphin`,
  `*-uncensored`, `wizard-vicuna`, `nous-hermes`, `abliterated`, …).
- **Uncensored models are always available.** `UNCENSORED_MODELS` is a curated
  list of real `ollama.com/library` slugs (dolphin3, dolphin-llama3/mistral/
  mixtral, llama2-uncensored, wizard-vicuna-uncensored, wizardlm-uncensored,
  nous-hermes2). They rank below the exact-size scrape cutoff (fewer pulls) and
  must survive an offline/builtin catalog, so `get_catalog` calls
  `_merge_uncensored` to append any the scrape didn't already surface —
  **a scraped entry always wins on a name collision** (keeps live pulls/size/
  caps). The model card route reads the *merged* catalog (not raw
  `load_cache()`) so these still supply size/description.
- **Ranking + dream team** (`annotate`): per-category family popularity
  ranking, counting only families with ≥1 runnable (`great`/`ok`) variant;
  the dream-team pick for each category is the **largest `great`-verdict
  variant of the top-ranked family**, falling back to the largest `ok`
  variant if no variant is `great`.
- **Image models are a separate, VRAM-bound ecosystem**: `catalog.image_models()`
  assesses a small curated hardcoded list (`IMAGE_MODELS`: SD 1.5, SD-Turbo,
  SDXL, SDXL-Turbo, SD 3.5 Medium, FLUX schnell/dev) against this machine's
  GPU — these models don't run in Ollama at all (ComfyUI/Fooocus/A1111
  instead). `app.py`'s `catalog_get()` route handler (not `catalog.annotate()`
  itself) appends the best runnable one to `dream_team` under a `🎨 "image"`
  category — remember this split if you ever move that assembly logic.
- **`sysinfo.assess()`**: Q4_K_M sizing heuristic — a model needs roughly its
  file size in RAM plus `KV_OVERHEAD_GB` (2 GB) for context, against a budget
  of total RAM minus `OS_RESERVE_GB` (3 GB); verdict thresholds are
  `great ≤55%`, `ok ≤80%`, `tight ≤100%` of that budget, else `no`. Parallel
  capacity = `min(RAM-budget slots, cpu_cores // 4, 4)`, further capped at
  **2** if the GPU's VRAM is smaller than a typical installed model (partial
  offload thrash, found empirically per `CLAUDE.md`).
- **`installer.py`**: Ollama pulls stream native `/api/pull` progress
  directly; LM Studio pulls shell out to `lms get <model> --yes` and parse
  percentage tokens from its stdout (best-effort — `CLAUDE.md`: "LM Studio
  automation is best-effort"). First-run **provider** install: Ollama is
  installed **user-level, no sudo** by resolving the latest GitHub release
  asset (`_resolve_ollama_asset`, tries `.tgz`/`.tar.zst`/`.tar.gz` in
  order), extracting to `~/.local/share/local-agents-studio/ollama`,
  symlinking the binary into `~/.local/bin`, and launching `ollama serve` as
  a detached background process, polling `/api/version` for up to 30s. LM
  Studio install only downloads the AppImage (probed against a hardcoded
  list of guessed version strings, `LMSTUDIO_VERSIONS`) — the user still has
  to launch it once and start its server manually. All installs run in
  daemon threads tracked in a shared in-memory `_installs` dict; the UI
  polls `GET /api/install/status`.

### Free memory (Settings)

`GET /api/system/memory` → live snapshot: total/available/cached/swap, models
currently loaded in Ollama (`/api/ps`), whether the Fooocus image server is
running and its RSS, the top RSS processes, `freeable_gb` (what the app itself
can release) and `largest_model_fits_gb`.

`POST /api/system/free-memory {unload_models?, stop_image_server?}` → unloads
Ollama models (`keep_alive: 0`) and/or stops the image server, then returns
`{actions, before, after, freed_gb}`. `FreeMemory.jsx` (Settings page) renders
the snapshot, one-click actions, and a collapsible Linux/Pop!_OS guide
(keep-alive tuning, `OLLAMA_MAX_LOADED_MODELS`, drop_caches, zram, TTY).

### Model cards — "what is this model best used for?"

`GET /api/models/card?name=<model>&provider=<ollama|lmstudio>` → a Pokédex-style
card (`ModelCard.jsx`, opened from the Models page pills, the Settings installed
table, and the catalog table):

- **8 aptitudes scored 1-10** (brainstorming, problem solving, task execution,
  tool & skill use, coding, writing, speed, long context)
- **best_for**: concrete roles in this app (Coder agent, Supervisor, Writer,
  Brainstormer, Help assistant…), ranked by the score they actually earn and
  gated behind a per-role minimum — so not every model gets called an
  orchestrator
- **avoid** + **notes**: e.g. "no native tool use → don't give it tools in Chat
  (team runs auto-delegate)", "reasoning model: give it ≥2000 max tokens"
- **suggested_params**: a sane starting temperature / max tokens / context
- **Manual download link** (`ModelCard.jsx`, derived client-side from
  `name`/`provider` — no backend field): Ollama models link to
  `ollama.com/library/<slug>` and show the exact `ollama pull <name>` command;
  LM Studio models link to a Hugging Face search. For when the one-click
  installer can't reach a provider, or you want to grab GGUFs by hand.
- **"💬 Try it in Chat"** opens the Chat page pre-selected on *this* model. The
  hash router keys on the path segment only (a `?query` would break it), so the
  card stashes `{model, provider}` in `sessionStorage["chatModel"]`; Chat's
  agent-state initializer consumes it once (then removes it) and, because
  `agent.model` is now set, skips its qwen-first auto-pick. A later plain visit
  to `#/chat` finds nothing stashed and falls back to the default.

Scoring lives in `modelinfo.py` and is **deterministic — no LLM rates models**.
Inputs: catalog capability tags (`tools`, `thinking`, `vision`), model family
(`FAMILY_TRAITS`), parameter count, this machine's speed estimate and RAM
verdict, plus `engine._tool_support_cache` (runtime truth about builds that
actually reject tool binding, which beats the catalog's family-wide tag).

## Gotchas

- **Model scores are relative, not benchmarks.** They answer "which of MY
  models should I point at this job?" Bonuses are capped at `size_score + 2`
  because a 1.5B "reasoning" model was otherwise ranking as a 10/10 supervisor,
  and non-coder families are capped at 7.5 coding so a big generalist doesn't
  outrank a coder model at coding. Keep those caps if you tune the weights.
- **`imagegen.stop_server()` used to lie.** It killed only the PID in a stale
  pid-file and still returned `ok: true`, leaving Fooocus holding ~10 GB + the
  GPU (which starves Ollama to a crawl). It now scans `/proc` for the real
  process, escalates SIGTERM→SIGKILL, and **verifies** it is gone before
  reporting success. Don't reintroduce pid-file-only killing.
- **Catalog scraping is HTML+regex, no official API.** If `ollama.com`
  changes its markup, `refresh()` catches the exception, sets
  `_state["error"]`, and the app quietly keeps serving the last good cache
  (or the tiny builtin snapshot on a fresh install) — check `data.error` /
  `data.source` before assuming the catalog is simply small.
- The image-generation dream-team entry is assembled in the **route
  handler**, not in `catalog.annotate()` — if `annotate()` is ever moved to
  a background job or cached independently of the per-request image
  assessment, the image entry needs to be re-attached wherever that move
  happens.
- **LM Studio install is inherently fragile**: `LMSTUDIO_VERSIONS` is a
  hardcoded, manually-maintained guess list probed via `HEAD` requests (no
  real "latest" API exists) — once every listed version is superseded on
  `installers.lmstudio.ai`, install silently fails to find a URL until the
  list is updated in code.
- `installer.cancel()` is cooperative and only checked between streamed
  chunks/lines — a pull blocked on one large network read won't cancel
  instantly.
- `POST /api/setup/install` inside Docker always returns
  `{ok:false, error:...}` without attempting anything — don't expect it to
  work there; the bundled Ollama service is the intended path.
- `GET /api/models`'s `errors` field is easy to miss when consuming this API
  — a provider being down looks identical to "provider up, zero models" in
  the `ollama`/`lmstudio` arrays alone; check `errors` to distinguish them.

## How to verify

1. `GET /api/system` and cross-check `hardware`/`installations` against
   reality on this machine (`nvidia-smi`, `ollama --version`, etc.).
2. `GET /api/catalog`, confirm a model you have installed shows
   `installed: true` and a `verdict` consistent with `sysinfo._verdict`'s
   RAM-budget math for its `size_gb`.
3. `POST /api/catalog/refresh`, poll `GET /api/catalog` and confirm
   `refreshing` flips to `false` and `fetched_at` advances (or `error` is
   set if offline).
4. `POST /api/install {"provider":"ollama","model":"qwen2.5:0.5b"}` (small,
   fast), poll `GET /api/install/status` until `done:true, status:"installed"`,
   then confirm `GET /api/models` and `GET /api/catalog` both reflect it as
   installed.
5. On a machine without Ollama, exercise `POST /api/setup/install
   {"provider":"ollama"}` and confirm it downloads, extracts, and starts a
   reachable server on `OLLAMA_URL` (or returns the Docker-refusal message
   when run inside a container).
