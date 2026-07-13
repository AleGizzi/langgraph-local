# Image Generation
> Part of Local Agents Studio. Read docs/index.md for the doc map.

## What it is

Local text-to-image generation via **Fooocus-API**
([mrhan1993/Fooocus-API](https://github.com/mrhan1993/Fooocus-API)), a
FastAPI wrapper around Fooocus/SDXL. It's a separate local process on its own
port (default 8888) that this app installs, starts/stops, and drives over
plain HTTP — no heavy ML dependencies (torch etc.) are imported into the
Flask process itself. Agents can call it as the `generate_image` tool; the
Models page has an install/run/generate UI.

## Key files

| Path | Role |
|------|------|
| `imagegen.py` | Install (git clone + venv + pip), start/stop (subprocess), `generate()` (POST + poll), gallery listing. All Fooocus-API HTTP contract details are documented in this file's module docstring. |
| `loras.py` | Search Civitai for SDXL-family LoRAs and download them into Fooocus's `loras` folder. Both the Civitai search API and the Fooocus-API `loras` request-field contract are documented in this file's module docstring. |
| `app.py` | `/api/imagegen/*` and `/api/loras*` routes. |
| `tools.py` (`generate_image`) | The agent-facing tool — thin wrapper calling `imagegen.generate(prompt, negative)`. |
| `frontend/src/components/ImageGen.jsx` | Install/start/stop/generate UI + gallery + collapsible "🎨 Style LoRAs" search/download/select panel, embedded in the Models page. |

`catalog.image_models()` / `frontend/.../ImageModels.jsx` (curated VRAM
assessment of SD 1.5/SDXL/FLUX etc.) are a **separate, informational-only**
system documented in `docs/features/models-catalog/` — they don't install or
run anything; this feature is the only thing that actually installs/drives a
runtime (Fooocus).

## API

- `GET /api/imagegen/status` → `imagegen.backend_status()` +
  `install: imagegen.install_status()`:
  ```json
  {"installed": bool, "running": bool, "url": "http://localhost:8888",
   "port": 8888, "dir": "...", "installing": bool, "error": "string|null",
   "install": {"status": "...", "progress": 0-100, "error": null, "done": bool} | {}}
  ```
  `install` is `{}` if no install was ever started in this process's
  lifetime (in-memory state — see Gotchas).
- `POST /api/imagegen/install` → `imagegen.install_backend()`:
  `{ok, error}`. Requires `git` on `PATH`; refuses if already installing.
- `POST /api/imagegen/start` → `imagegen.start_server()`: `{ok, error}`.
  No-op (`ok:true`) if already running; errors if not installed.
- `POST /api/imagegen/stop` → `imagegen.stop_server()`: `{ok: true}` always
  (best-effort — see Gotchas).
- `POST /api/imagegen/generate`
  `{prompt (required), negative?, steps?, aspect? (default "1152*896"),
  performance? (default "Extreme Speed"), loras? ([{file_name, weight}])}` →
  `imagegen.generate()`: `{ok, images: ["filename.png", ...], error}`. Each
  `loras` entry becomes a Fooocus-API `{"enabled": true, "model_name":
  file_name, "weight": weight}` entry (weight clamped to `[0, 2]`); malformed
  entries are silently skipped rather than raising.
- `GET /api/imagegen/gallery` → `{images: [filenames, newest first]}`.
- `GET /api/imagegen/images/<filename>` → the raw image file
  (path-traversal safe: filename is `os.path.basename`'d and resolved
  against `IMAGES_DIR`).

### LoRAs (`loras.py`)

- `GET /api/loras` → `{local: loras.list_local(), downloads:
  loras.download_status()}`. `local`: `[{file_name, size_mb}, ...]` currently
  sitting in `LORAS_DIR`. `downloads`: in-memory status dict keyed by
  `file_name` (installer.py-style: `status, progress, error, done,
  started_at`).
- `GET /api/loras/search?q=<query>&base=SDXL` → `loras.search(q, base)`:
  `{ok, results: [{id, name, version_name, base_model, file_name, size_kb,
  download_url, downloads, description (≤200 chars, HTML stripped),
  compatible}], error}`, sorted compatible-first then by `downloads` desc.
  Backed live by `GET https://civitai.com/api/v1/models?query=...&types=LORA&limit=30`
  (no auth needed for search) — one result row per `modelVersion` (a single
  Civitai model can list both an SDXL and an SD 1.5 version, each with a
  different `baseModel`/`compatible` value). `compatible` is `true` iff the
  version's `baseModel` contains `"SDXL"` or `"Pony"` (Pony is an
  SDXL-architecture finetune) — everything else (`SD 1.5`, `Flux.1 D`, ...)
  is marked incompatible but still returned, not hidden, per the "surface
  compatibility clearly" requirement.
- `POST /api/loras/download {download_url, file_name}` → `loras.download()`:
  `{ok, error}`. Starts a background download into `LORAS_DIR`; poll via
  `GET /api/loras`. `file_name` is sanitized (`os.path.basename`, must end
  `.safetensors`/`.pt`/`.ckpt`) before being used as both the download key
  and the on-disk filename.

### The `generate_image` agent tool

`generate_image(prompt: str, negative: str = "") -> str` — checks
`backend_status()["running"]` first (returns a plain-English "install/start
Fooocus" message if not), otherwise calls `imagegen.generate(prompt,
negative=negative)` with **default** aspect ratio and performance mode (no
`aspect`/`steps`/`performance` arguments exposed to agents), and returns
`"Generated image(s): /api/imagegen/images/<name>, ..."` as plain text.

## How it works

- **Install** (`install_backend` → `_install_worker`): `git clone --depth 1`
  into `FOOOCUS_DIR` (default
  `~/.local/share/local-agents-studio/fooocus-api`, override with
  `FOOOCUS_DIR`), `python -m venv venv`, `pip install -r requirements.txt`,
  then `pip install torch torchvision torchaudio --index-url
  https://download.pytorch.org/whl/cu121` — **deliberately unpinned**: an
  earlier pin (`torch==2.1.0`) broke when that exact wheel build was dropped
  from the cu121 index; falls back to CPU-only torch if the CUDA install
  fails. All steps run in a background daemon thread; progress/errors are
  tracked in an in-memory `_installs["fooocus"]` dict polled via
  `install_status()`.
- **Start** (`start_server`): launches
  `venv/bin/python main.py --host <h> --port <p> --always-low-vram` as a
  detached subprocess (`start_new_session=True`), logging to
  `FOOOCUS_DIR/server.log`, and records the pid in `FOOOCUS_DIR/.server.pid`.
  `--always-low-vram` forces Fooocus's aggressive offloading mode, needed on
  small GPUs (this app was verified against a 4 GB Quadro P600).
- **Health check**: `GET /ping` on the Fooocus-API server (not `/health`).
- **Generate** (`generate`): POSTs to `/v1/generation/text-to-image` with
  `async_process: true` **always** (a slow/low-VRAM GPU can take minutes per
  image — far past a normal HTTP timeout), receives a `job_id`, then polls
  `GET /v1/generation/query-job?job_id=...` every 2s until
  `job_status`/`job_stage` is `finished`/`success` (or `job_result` is
  present), up to `GEN_TIMEOUT` (default 2400s, env `IMAGEGEN_TIMEOUT`). A
  defensive branch handles the (unexpected) case where the server replies
  synchronously despite the async flag. Result images (`base64` or a `url`
  the Fooocus-API server itself serves) are downloaded/decoded and saved
  into `IMAGES_DIR` by **this module**, so generated images survive
  independently of the Fooocus-API process or install.
- **Performance presets** (`PERFORMANCE_MODES`: `Extreme Speed`,
  `Lightning`, `Hyper-SD`, `Speed`, `Quality`) map to Fooocus's built-in
  diffusion step-count presets — the dominant cost knob. Default is
  `Extreme Speed` (~8 LCM steps, env override `IMAGEGEN_PERFORMANCE`),
  chosen because full-step modes are impractically slow on weak GPUs
  (measured ~86s/step on the reference 4 GB card → ~40 min for the 30-step
  `Speed` mode). An explicit `steps` argument overrides the preset via
  `advanced_params.overwrite_step`.
- **LoRAs** (`loras.py`): `search()` hits Civitai's public REST API directly
  (no API key needed to search) and classifies each `modelVersion` as
  SDXL-compatible or not client-side, because Civitai's own `baseModels`
  filter only matches exact enum strings and would hide compatible-but-
  differently-labelled results (or require one request per variant) instead
  of surfacing the mismatch. `download()` streams the file into `LORAS_DIR`
  (installer.py-style background thread + polled status dict keyed by
  `file_name`); if the creator gated the file behind a login (Civitai
  returns `401`), it stops immediately with an error naming `CIVITAI_API_KEY`
  and the manual-download fallback path, rather than retrying or hanging.
  `LORAS_DIR` resolves to `FOOOCUS_LORAS_DIR` if set, else
  `<FOOOCUS_DIR>/repositories/Fooocus/models/loras` — the directory Fooocus
  itself scans for `model_name` values, and where its two bundled example
  LoRAs (`sd_xl_offset_example-lora_1.0.safetensors`,
  `sdxl_lcm_lora.safetensors`) already live after a normal install.

### LoRA metadata, source links and removal

- **Search results** carry `description`, `source_url` (the Civitai model page —
  open it to inspect samples/licence), `trigger_words` (`trainedWords`; putting
  these in the prompt is often what actually activates the style), `creator`,
  and the SDXL-compatibility flag.
- **Downloads persist that metadata** in a `<file>.json` sidecar next to the
  `.safetensors`, so the Installed list can still explain a LoRA long after the
  search results are gone.
- **`list_local()`** merges: the sidecar → `KNOWN_LORAS` (hand-written
  descriptions for the LoRAs Fooocus ships: the offset-noise LoRA and the
  LCM/Lightning/Hyper-SD accelerators the performance presets load automatically
  — these are marked `builtin` and cannot be deleted from the UI) → basic file
  facts.
- **`POST /api/loras/identify {file_name}`** backfills metadata for a file with
  no sidecar (downloaded before sidecars existed, or dropped in by hand): it
  searches Civitai for the filename and accepts **only an exact file-name
  match**, so a file is never mislabelled with someone else's description. It
  honestly returns an error when there's no match.
- **`DELETE /api/loras/<file_name>`** removes the file and its sidecar. Names
  are sanitized to a basename and confined to `LORAS_DIR` (a `../` traversal
  attempt 404s and touches nothing).

### Modifying an existing image (img2img)

`GET /api/imagegen/modes` lists what can be done; `POST /api/imagegen/modify`
does it. Body: `{image, mode, prompt, negative, performance, loras, weight,
outpaint, aspect}` where **`image`** is a data URL, raw base64, or the filename
of an image already in the gallery. Response is the same `{ok, images, error}`
shape as `/generate`.

Modes map to Fooocus-API's **v2** JSON endpoints (v2 is used here because it
takes the source image as base64, unlike v1's multipart):

| mode | endpoint | what it does |
|------|----------|--------------|
| `vary_subtle` / `vary_strong` | `/v2/generation/image-upscale-vary` | re-diffuse the image, guided by your prompt (classic img2img) |
| `upscale_1_5x` / `upscale_2x` / `upscale_fast` | same | enlarge; `upscale_fast` skips re-diffusion and is the quick one |
| `style` / `structure` / `depth` / `face` | `/v2/generation/image-prompt` | ControlNet: `ImagePrompt` (borrow look/content), `PyraCanny` (keep composition), `CPDS` (keep shapes/depth), `FaceSwap`. `weight`/`stop` control influence |
| `outpaint` | `/v2/generation/image-inpaint-outpaint` | extend the image outward (`outpaint: ["Left","Right","Top","Bottom"]`) — no mask needed |

`imagegen._run_job()` is shared by `generate()` and `modify()` (post → poll →
save → write the metadata sidecar), so modified images get the same prompt
tracking, LoRA support and speed presets. UI: the "🖼️ Modify an existing image"
panel in `ImageGen.jsx` — drop/browse a file **or** click any image already in
the gallery, choose a mode, and go.

**Not implemented:** inpainting with a hand-painted mask (the endpoint supports
`input_mask`, but it needs a mask-painting canvas in the UI). Outpaint covers
the maskless half of that endpoint.

## Gotchas

- **Vary/restyle re-diffuse at higher resolution and are SLOW** on a small GPU
  (~6 min for 8 steps on the 4GB P600 — slower than a plain generation).
  `upscale_fast` is the only quick mode. Requests are long-lived: don't hold a
  short HTTP timeout on `/api/imagegen/modify`.
- **The old `docs/image-generation.md` described a different, incomplete
  implementation** — it said "`imagegen.py` is currently in development" and
  gave manual install/usage instructions that don't match the real, working
  module: it showed `pip install -e .` (the real steps are `pip install -r
  requirements.txt` then a separate unpinned torch install from the cu121
  index), a `/health` health-check endpoint (the real one is `GET /ping`),
  and `negative_prompt`/`aspect_ratio` as the agent tool's argument names
  (the real `generate_image` tool only takes `prompt`/`negative`, with no
  aspect-ratio control exposed to agents at all). This README replaces that
  content with what the code actually does.
- **Torch install is deliberately unpinned** — if you reintroduce a version
  pin for reproducibility, expect it to silently break again whenever that
  exact wheel build is removed from the PyTorch cu121 index (this already
  happened once with `torch==2.1.0`).
- **Install/start progress is in-memory only** (`_installs` dict, not
  persisted) — a server restart mid-install loses progress tracking
  entirely, though the partially-cloned repo/venv on disk survives, so
  `installed` still reports correctly (possibly as a broken/incomplete
  install) after restart.
- `stop_server()` is best-effort: it reads `.server.pid` and sends
  `SIGTERM` to that process group. If Fooocus-API was started outside this
  app (e.g. manually for debugging), there's no pid file and `stop_server()`
  is a silent no-op that still returns `{ok: true}`.
- The `generate_image` tool's returned image paths are **plain text** in the
  tool result — nothing renders them inline in the run `Timeline` (a known
  gap noted in `CLAUDE.md`: "Fooocus artifacts aren't wired to teams' final
  output cards").
- `generate()` always sets `async_process: true`; the synchronous-reply
  handling branch is a defensive fallback for an API behavior change, not
  something to rely on as the primary path.
- **Only SDXL-family LoRAs (`baseModel` containing "SDXL" or "Pony") work on
  this app's JuggernautXL/SDXL Fooocus base.** SD 1.5 LoRAs (and Flux, etc.)
  load into `loras.model_name` without any error from Fooocus-API — they
  just silently have zero visible effect on the generated image, since the
  tensor shapes don't match the SDXL U-Net. `loras.search()`'s `compatible`
  flag exists specifically to surface this before a download is wasted; the
  UI shows a red "incompatible (SD1.5)"-style badge rather than hiding those
  results outright.
- **Civitai downloads increasingly require a login.** Verified live (July
  2026): most LoRA files 401 anonymously with `{"error":"Unauthorized",
  "message":"The creator of this asset requires you to be logged in to
  download it"}`; a minority (e.g. ones without a licensing gate) still
  redirect straight to a signed `b2.civitai.com` URL with no auth. Set the
  `CIVITAI_API_KEY` env var (a key from the user's Civitai account settings)
  to send `Authorization: Bearer <key>` on every download and unlock the
  gated ones; without it, `download()` fails fast with a clear error instead
  of hanging or silently writing a 0-byte/HTML file.
- **Downloaded LoRA files land in `LORAS_DIR`**
  (`FOOOCUS_LORAS_DIR` env override, else `<FOOOCUS_DIR>/repositories/
  Fooocus/models/loras`) — this only exists once Fooocus-API has been
  installed (the `repositories/Fooocus` vendor checkout is created by
  Fooocus itself on first launch, not by `install_backend()`), so
  `download()`/`list_local()` create the directory on demand if it's
  missing rather than assuming it's there.
- **LoRA download progress is in-memory only** (`loras._downloads`, mirrors
  the `imagegen`/`installer` pattern) — a server restart mid-download loses
  progress tracking; the partially-written file is left as `<name>.part` and
  is not picked up by `list_local()` (which only lists the recognized LoRA
  extensions), so a restart-interrupted download needs to be retried from
  the UI.

## How to verify

1. `GET /api/imagegen/status` on a fresh machine — expect `installed: false`.
2. `POST /api/imagegen/install`, poll `GET /api/imagegen/status` until
   `install.done: true, install.error: null`.
3. `POST /api/imagegen/start`, poll until `running: true`; sanity-check
   directly with `curl http://localhost:8888/ping`.
4. `POST /api/imagegen/generate {"prompt":"a red cube on a white background",
   "performance":"Extreme Speed"}` and wait for `{ok:true, images:[...]}`;
   confirm the files exist under `data/images/` (or `$IMAGES_DIR`).
5. `GET /api/imagegen/gallery` and confirm the new filenames appear, newest
   first; open one via `GET /api/imagegen/images/<name>`.
6. Enable `generate_image` on a team agent, run a task asking for an image,
   and confirm a `tool_call`/`tool_result` pair appears in the run timeline
   with a `/api/imagegen/images/...` path in the result text.
7. `GET /api/loras/search?q=pokemon+sprite&base=SDXL` and confirm real
   Civitai results come back with a mix of `compatible: true/false` values
   (SD 1.5 results should be marked `false`, SDXL/Pony `true`).
8. `POST /api/loras/download {"download_url": "<a result's download_url>",
   "file_name": "<its file_name>"}`, poll `GET /api/loras` until that
   `file_name`'s entry in `downloads` has `done: true` (and `error: null`),
   then confirm it now also appears in `local`. If it 401s instead, that
   file needs a Civitai login — try a different result or set
   `CIVITAI_API_KEY`.
9. In the UI: open the "🎨 Style LoRAs" panel under a running Fooocus
   server, search, download a compatible result, watch the progress bar
   reach 100%, check it in the "Installed LoRAs" list, set a weight, and
   confirm the next `POST /api/imagegen/generate` call includes a `loras`
   array in its request body with that `file_name`/`weight`.
