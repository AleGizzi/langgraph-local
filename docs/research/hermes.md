# Hermes Agent with Local Agents Studio

*Researched/written 2026-10-25. Source of truth for the Hermes install on this
machine is `~/Documents/projects/hermes-local` (AGENTS.md, docs/setup.md,
docs/models.md); this page is the Studio-side view.*

## What Hermes is, and how it relates to the Studio

[Hermes Agent](https://github.com/NousResearch/hermes-agent) (Nous Research) is a
single, general-purpose terminal agent: shell, files, web, memory, skills, a
messaging gateway. The Studio is a *team builder*: many small agents, topologies,
schedules, a knowledge vault. They complement each other:

| Use Hermes for | Use the Studio for |
|---|---|
| One long, open-ended job that needs a real terminal loop (fix my system, refactor this repo, research and write a report) | Repeatable pipelines (Spec → Builder → Verifier), schedules, chat, knowledge notes |
| Interactive sessions where the warm prompt cache matters | Unattended runs with blast-radius gating and run modes |

Both talk to the **same Ollama on `127.0.0.1:11434`** with the **same model store
(`~/.ollama/models`)**, so nothing is downloaded twice. The downside: only one
model is resident (`OLLAMA_MAX_LOADED_MODELS=1`, 31 GB RAM), so a Studio run
evicts Hermes' model and the next Hermes turn pays a cold prefill (~3–5 min).

## Installing Hermes properly (Linux, fully local)

1. **Ollama first, as a user service on the single store.** See
   [model-store.md](model-store.md). Check: `systemctl --user status ollama` and
   `curl -s http://127.0.0.1:11434/api/version`.
2. **Install Hermes (CLI only, no desktop app, no browser/computer-use extras):**
   ```bash
   curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash -s -- --skip-browser --skip-computer-use
   hermes --version          # this machine: v0.22.2
   ```
   It clones to `~/.hermes/hermes-agent`, puts a launcher in `~/.local/bin/hermes`
   and runs `hermes setup`. In setup, pick **custom (OpenAI-compatible)** — do
   **not** log in to Nous Portal or add cloud fallbacks (house rule: fully local).
3. **Point it at local Ollama** (`~/.hermes/config.yaml`):
   ```yaml
   model:
     provider: "custom"
     base_url: "http://127.0.0.1:11434/v1"   # 127.0.0.1, never localhost: IPv6 is broken here
     default: "qwen3-coder-64k:30b"
   agent:
     reasoning_effort: "none"                # the STRING "none"; bare none = YAML null
   ```
   and `HERMES_API_TIMEOUT=1800` in `~/.hermes/.env` (CPU prefill is slow).
4. **Give it a model with ≥ 64k context.** Hermes refuses tool use below 64k, and
   Ollama's `/v1` endpoint *ignores* per-request `num_ctx` (silently runs at 4096).
   Make a Modelfile variant that shares the weights (no extra disk):
   ```bash
   cat > /tmp/Modelfile <<'EOF'
   FROM qwen3-coder:30b
   PARAMETER num_ctx 65536
   EOF
   ollama create qwen3-coder-64k:30b -f /tmp/Modelfile
   ollama show qwen3-coder:30b | grep -i "context length"   # must be ≥ 65536 — Ollama clamps to native ctx
   ```
   hermes-local has this as `scripts/04-make-64k-variant.sh <model>`.
5. **Trim toolsets** (every tool schema is re-prefilled on cold turns):
   `platform_toolsets.cli: [clarify, code_execution, file, memory, session_search, skills, terminal, todo, web]`.
6. **Verify:** `hermes doctor`, then
   `hermes -z "Use the terminal tool to run: cat /etc/hostname. Reply with only the hostname."`
   must print the real hostname (proves tool calling end-to-end).

## Using Hermes from the Studio — `hermes_agent` tool

`custom_tools/hermes_agent.py` exposes Hermes as a tool any agent can be given
(Skills & Tools page → custom tools; attach to an agent like any other tool).

- Calls `hermes -z <task> --in <workdir>` (one-shot: prints only the final answer).
  Default workdir `data/workspaces/hermes/`; pass `workdir` to aim it elsewhere.
- **One-shot mode auto-approves Hermes' shell commands.** The tool is therefore in
  `engine._DESTRUCTIVE_TOOLS`: refused on scheduled runs (unless the schedule
  allows destructive actions) and on max-savings runs.
- Timeout `HERMES_TOOL_TIMEOUT` (default 1800 s). Expect 3–5 min per call on CPU.
- Pattern that works: a cheap Studio planner (qwen2.5:7b) writes a precise task
  statement → `hermes_agent` executes it → a Studio verifier checks the result.
  Don't give it to agents that should answer simple questions — the cost is a
  model swap plus a 15k-token cold prefill.

## Which model for Hermes (this machine: i7-8850H, 31 GB, P600 4 GB)

Measured by hermes-local (`docs/models.md`): **`qwen3-coder-64k:30b`** is the
default (MoE 3.3B active, 262k native ctx, 70 tok/s prefill, 4.3 tok/s gen).
Generation speed is RAM-bandwidth bound, so **MoE models with ~3B active
parameters are the sweet spot**. Newer candidates found in this research (see
[small-models.md](small-models.md)); none is benchmarked under Hermes yet:

| Candidate | Why | Size | Status |
|---|---|---|---|
| `nemotron-3.5-lightning:30b` | MoE 30B/3B active, 1M ctx, explicitly built for "always-on agents" incl. Hermes Agent | 19–25 GB | not downloaded (big; ask) |
| `gemma4:26b` | MoE 25B/3.8B active, 256k ctx, native tools + vision | 16–19 GB | **downloaded** — make a `-64k` variant to try |
| `laguna-xs-2.1` | MoE 33B/3B active, agentic coding (SWE-bench V 70.9%) | 20 GB | not downloaded |
| `lfm2.5:24b` | ~2B active, RL-trained in agent harnesses | 15 GB | not downloaded |
| `lfm2.5:8b` | ~1B active — very fast fallback, weaker | 5.2 GB | **downloaded** |

Always check `ollama show <m>` → context length ≥ 65536 before making a variant.

## Gotchas

- Loading a Studio model evicts Hermes' model → slow next turn. Keep one
  interactive `hermes` session for interactive work; use the tool for batch work.
- `localhost` resolves to IPv6 first here and fails — use `127.0.0.1`.
- Don't restart Ollama while a Hermes or Studio run is in flight (both die).
