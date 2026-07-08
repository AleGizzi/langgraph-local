# Image Generation (Fooocus)

Local Agents Studio can generate images locally via **Fooocus**, a REST API wrapper around Stable Diffusion XL (SDXL). Unlike text models (Ollama/LM Studio), image generation is a separate service running on a different port (default 8888) that the app calls over HTTP.

## Overview

Fooocus runs as a standalone local server (installed as the [`mrhan1993/Fooocus-API`](https://github.com/mrhan1993/Fooocus-API) REST distribution). The app discovers and manages this service via a simple HTTP interface:

- **Install** — git clone + virtual environment + dependencies + first model download (multi-GB, takes 10–30 minutes depending on your connection and GPU).
- **Start/Stop** — Launch or shut down the Fooocus server (background process).
- **Generate** — POST a prompt + settings to the server; images appear in the gallery and are saved to disk.
- **Use in agents** — Add the `generate_image` tool to any agent; it becomes callable as part of a run.

Fooocus targets SDXL and includes sane defaults (good quality, reasonable speed). For alternate runtimes (Automatic1111, ComfyUI) or lighter models (SD 1.5), see the [Alternatives](#alternatives) section.

## Installing

### From the UI

1. Go to the **Models** page.
2. Scroll to **Image generation (Fooocus)**.
3. Click **Install Fooocus** (if not already installed).
   - This runs in the background: clones the Fooocus-API repo, creates a venv, installs dependencies, and downloads the default SDXL model on first run.
   - Multi-GB download; watch the progress indicator.
4. Once installed, click **Start image server**.
   - The server starts on `http://localhost:8888` (or `$FOOOCUS_URL` if overridden).

### Manual Install

```bash
# Install Fooocus-API
git clone https://github.com/mrhan1993/Fooocus-API ~/.local/share/local-agents-studio/fooocus-api
cd ~/.local/share/local-agents-studio/fooocus-api
python -m venv venv
source venv/bin/activate
pip install -e .

# Start the server (it will download models on first run)
python -m fooocus_api
```

The server listens on port 8888 by default. If that's in use, set `FOOOCUS_URL=http://localhost:9999` before starting the app.

## Hardware Reality

**Fooocus targets SDXL, which wants ~8 GB VRAM for best performance.** On smaller GPUs, it works but images take longer.

### VRAM Guide

The app's **Settings** page includes a **Local image generation** table that assesses each model against your GPU:

| Verdict | Meaning | What to expect |
|---------|---------|----------------|
| **great** | VRAM ≥ 1.4× model minimum | Recommended. Smooth generation (minutes per image). |
| **ok** | VRAM ≥ model minimum | Workable. Reasonable speed. |
| **tight** | VRAM 60–99% of minimum | Runs, but uses offloading/quantization. Noticeably slow (5–15 minutes per image). |
| **no** | Insufficient VRAM or RAM | Not practical. |

**This machine (Quadro P600, 4 GB VRAM):** SDXL runs in "tight" mode. Expect 5–15 minutes per image. For faster results, use **SD 1.5** (2 GB VRAM) instead, or upgrade the GPU.

### Alternatives for Smaller GPUs

- **SD 1.5** (~2 GB VRAM) — Classic, lighter, huge ecosystem of fine-tunes and LoRAs.
  - Install via Automatic1111 or ComfyUI (see [alternatives](#alternatives) below).
- **SDXL-Turbo** (~6 GB VRAM) — Generates in 1–4 steps instead of 25–50. Needs a mid-range GPU but noticeably faster.

## Using It

### From the Gallery

1. Open **Models** → the **Image generation (Fooocus)** section.
2. Enter a prompt (e.g., "a serene mountain landscape at sunset").
3. (Optional) Add a negative prompt (e.g., "blurry, low quality").
4. Choose aspect ratio and a **Speed / quality** mode (see below).
5. Click **Generate**.
6. Images appear in the gallery below. Click to view full-size.

Generated images are saved to `data/images/` and listed with timestamps.

### Speed / quality modes (the key to usability on weak GPUs)

Fooocus performance presets set how many diffusion steps run — the dominant cost.
On a slow/low-VRAM GPU this is the difference between usable and unusable:

| Mode | Steps | On the 4 GB P600 (measured ~86s/step) |
|------|-------|----------------------------------------|
| **Extreme Speed** (default) | ~8 (LCM) | **~6 min/image** ✓ verified |
| **Lightning** | ~4 | ~3–4 min (needs a small extra LoRA download) |
| **Speed** | 30 | ~40 min |
| **Quality** | 60 | ~80 min |

Default is **Extreme Speed** — on a strong GPU switch to Speed/Quality for more
detail. Overridable app-wide with `IMAGEGEN_PERFORMANCE`; the generation poll
timeout is `IMAGEGEN_TIMEOUT` (default 2400s).

### From Agents

Enable the `generate_image` tool on an agent:

1. Go to **Teams** → edit an agent.
2. Under **Tools**, check **generate_image**.
3. Instruct the agent in its system prompt, e.g., "Generate a diagram if the user asks for one."

When a run executes, the agent can call the tool with:
```json
{
  "prompt": "a detailed architecture diagram",
  "negative_prompt": "text, labels",
  "aspect_ratio": "16:9"
}
```

The tool returns the saved image path; the agent can reference it in its response or describe what was generated.

**Note:** `imagegen.py` is currently in development. Once complete, the `generate_image` tool will be available in the UI and callable from agents.

## Where Files Live

| Item | Location | Override |
|------|----------|----------|
| Generated images | `data/images/` | — |
| Fooocus-API install | `~/.local/share/local-agents-studio/fooocus-api` | `FOOOCUS_DIR` |
| Server URL | `http://localhost:8888` | `FOOOCUS_URL` |
| Models cache | `~/.local/share/local-agents-studio/fooocus-api/models` | Inside `FOOOCUS_DIR` |

**Environment variables:**
```bash
export FOOOCUS_DIR="$HOME/my-fooocus"      # Custom install location
export FOOOCUS_URL="http://localhost:9999" # Non-default port
./run.sh
```

## Troubleshooting

### Fooocus Server Won't Start

**Symptom:** "Start image server" button fails or server doesn't respond.

**Fixes:**
1. Check the port is free: `lsof -i :8888` or `netstat -tlnp | grep 8888`.
2. If another process is using 8888, stop it or set `FOOOCUS_URL` to a different port.
3. Manually verify the server:
   ```bash
   curl http://localhost:8888/health
   ```
   If it returns `{"status": "ok"}`, the server is up.

### Generation Times Out (Long Waits)

**Symptom:** Image generation stalls or times out after 5+ minutes.

**Cause:** Your GPU is weak (expected on 4 GB VRAM). Fooocus runs in offloading mode.

**Fixes:**
1. **Be patient.** 5–15 minutes per image is normal on tight VRAM. Increase your timeout in the UI.
2. **Use a smaller model:**
   - Try **SD 1.5** instead of SDXL (half the VRAM, faster, lighter).
   - Requires a different runner (Automatic1111, ComfyUI, or a separate Fooocus setup).
3. **Reduce quality/steps:**
   - In the generate form, lower "steps" or resolution to speed up (Fooocus UI, not this app's UI yet).
4. **Upgrade GPU.** If image generation is critical, a mid-range GPU (8 GB+ VRAM) is worth it.

### Out of Disk Space

**Symptom:** Install fails midway; "No space left on device."

**Fix:**
1. Free up disk space:
   ```bash
   df -h                          # Check available space
   du -sh ~/.local/share/local-agents-studio
   ```
2. Models are large (6–10 GB per model). Ensure `~/.local/share/` has at least 30 GB free.
3. Retry the install from the UI.

### Install Failed, Won't Retry

**Symptom:** "Install Fooocus" button shows an error; clicking again doesn't help.

**Fix:**
1. Check the app logs:
   ```bash
   tail -50 data/server.log
   ```
2. Try manual install (see [Installing](#installing) above).
3. If that works, the app should detect the existing install on next startup.

## Alternatives

If Fooocus doesn't fit your needs, you can use another image-generation runtime. The app currently targets Fooocus, but the pattern is extensible.

### Automatic1111 (Classic SD UI)

- **Best for:** SD 1.5, SDXL, and extensions.
- **Install:** [AUTOMATIC1111/stable-diffusion-webui](https://github.com/AUTOMATIC1111/stable-diffusion-webui).
- **Run:** `./webui.sh`.
- **Endpoint:** Usually `http://localhost:7860`.
- **Note:** Requires manual HTTP calls; not yet integrated into Local Agents Studio.

### ComfyUI (Node-Based)

- **Best for:** Advanced workflows, FLUX.1, and custom pipelines.
- **Install:** [comfyanonymous/ComfyUI](https://github.com/comfyanonymous/ComfyUI).
- **Endpoint:** Usually `http://localhost:8188`.
- **Note:** Requires custom workflow definitions; not yet integrated.

---

For more details on running the app, see [operations.md](operations.md). For extending the app to support other image backends, see [extending.md](extending.md).
