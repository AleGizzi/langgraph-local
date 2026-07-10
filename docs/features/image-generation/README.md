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
| `app.py` | `/api/imagegen/*` routes. |
| `tools.py` (`generate_image`) | The agent-facing tool — thin wrapper calling `imagegen.generate(prompt, negative)`. |
| `frontend/src/components/ImageGen.jsx` | Install/start/stop/generate UI + gallery, embedded in the Models page. |

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
  performance? (default "Extreme Speed")}` → `imagegen.generate()`:
  `{ok, images: ["filename.png", ...], error}`.
- `GET /api/imagegen/gallery` → `{images: [filenames, newest first]}`.
- `GET /api/imagegen/images/<filename>` → the raw image file
  (path-traversal safe: filename is `os.path.basename`'d and resolved
  against `IMAGES_DIR`).

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

## Gotchas

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
