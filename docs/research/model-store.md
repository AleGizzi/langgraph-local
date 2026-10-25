# One model store: `~/.ollama/models`

*2026-10-25.* Every LLM on this machine lives in **one place**:
`/home/ale/.ollama/models` (~193 GB before this session's downloads), served by
the **user** systemd unit `~/.config/systemd/user/ollama.service`
(`OLLAMA_MODELS=%h/.ollama/models`, `127.0.0.1:11434`). Every consumer reads it:

| Consumer | How it reaches the store |
|---|---|
| Local Agents Studio | Ollama API `:11434` (`providers.list_models` → `/api/tags`) |
| Hermes Agent | Ollama `/v1` on `:11434` |
| pop-doctor, whisper-flow-local, lovable-local | Ollama API `:11434` |
| LM Studio | **symlinks** `~/.lmstudio/models/ollama/<name>-<tag>/*.gguf` → blobs in the store (0 extra disk) |

The old root store `/usr/share/ollama/.ollama/models` was merged into it on
2026-10-24 (hermes-local `scripts/01-merge-ollama-stores.sh`); only empty
manifest dirs (176 KB) remain, and the root `ollama.service` is disabled.

## What was wrong and what changed in this repo

1. **`sysinfo.py`** searched `/usr/share/ollama` *before* `~/.ollama` and picked
   the biggest dir; it only checked the *system* `ollama` unit, so the Setup page
   reported "no service" for the user unit. Now: `$OLLAMA_MODELS` →
   `~/.ollama/models` → legacy `/usr/share` (only if it still holds blobs), and the
   user unit is detected first.
2. **Install guide** (Setup page, `sysinfo.INSTALL_GUIDES`) now shows how to swap
   the installer's root service for the user service, so new installs get one store.
3. **FreeMemory / Setup hints** said `sudo systemctl edit ollama` — that edits the
   disabled root unit and does nothing. Now `systemctl --user edit ollama`.
4. **LM Studio links were all broken** (10 links pointed into the emptied
   `/usr/share` blobs dir). Re-pointed, and
   `deploy/link-ollama-to-lmstudio.py` now links **every** Ollama model (36 at the
   time) and removes stale links. Re-run it after `ollama pull` / `ollama rm`.

## Ollama upgrade 0.22.1 → 0.40.11 (user-local, no sudo)

The newest models (Kev/Tev1/d3 decision family, gemma4, qwen3.5, …) return
`412: requires a newer version of Ollama` on 0.22.1. 0.40.11 was installed to
`~/.local/share/ollama-0.40.11/` (checksum-verified from the GitHub release) and
the user unit's `ExecStart` points there; `/usr/local/bin/ollama` (0.22.1, root)
is untouched as a fallback. Roll back = point `ExecStart` back at
`/usr/local/bin/ollama` and `systemctl --user daemon-reload && systemctl --user restart ollama`.

The CLI on `PATH` is still the old binary, which can talk to the new server but
warns `client version is 0.40.11`. To make the CLI match, run
`ln -s ~/.local/share/ollama-0.40.11/bin/ollama ~/.local/bin/ollama` (`~/.local/bin`
comes before `/usr/local/bin` on PATH), or replace the system binary with sudo.

## Docker

`docker-compose.yml` keeps a named volume (it targets Windows/macOS). On Linux,
to share the host store instead of downloading again, replace
`ollama_models:/root/.ollama` with `${HOME}/.ollama:/root/.ollama` — but don't run
it next to the native server on the same port.

## Reclaiming disk (suggestions — not done, deleting models is your call)

Duplicates / superseded models in the store, largest first:

| Model | Size | Why it's a candidate |
|---|---|---|
| `codellama:34b` | 19 GB | superseded by qwen3-coder:30b (MoE, far faster here) |
| `llama3.1:8b-instruct-fp16` | 16 GB | fp16 of a model also present as q8_0 and q4 |
| `gemma4:31b` | 19 GB | dense 31B ≈ 1 tok/s on this CPU; `gemma4:26b` (MoE, 3.8B active) is the usable sibling |
| `llama2-uncensored:7b`, `tinyllama` | 4.4 GB | 2023-era, far weaker than 2026 small models |

`ollama rm <model>` then re-run `deploy/link-ollama-to-lmstudio.py`.
