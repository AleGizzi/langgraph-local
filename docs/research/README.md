# Research & work log — 2026-10-25

| Doc | Contents |
|---|---|
| [model-store.md](model-store.md) | A single LLM store at `~/.ollama/models`: what changed in the code, LM Studio symlinks, the Ollama 0.22.1 → 0.40.11 upgrade (user-local, with rollback), and reclaimable disk |
| [small-models.md](small-models.md) | The "Jev" decision-model family (kev/tev1/d3…), Gemma 4 siblings, newest efficient agent models, minimal-resource picks, **measured** results on this machine |
| [hermes.md](hermes.md) | Hermes Agent: installing it properly (fully local) and using it from the Studio (`hermes_agent` tool) |
| [ui-improvements.md](ui-improvements.md) | Ranked UI / model-workflow proposals (✅ = done) |
| `scripts/bench_small_models.py` | Benchmark used for the measurements; results in `scripts/results/` |

**Code changed:** `sysinfo.py` (store + user-unit detection, install guide), `providers.py`
(decision models listed separately), `router.py` (one-pass decision-model classifier with
chat fallback), `catalog.py` (🎯 decision category), `modes.py`, `engine.py` (hermes_agent is
treated as destructive), `custom_tools/hermes_agent.py`, `deploy/link-ollama-to-lmstudio.py`,
`Models.jsx`, `Setup.jsx`, `FreeMemory.jsx`.

**Outside the repo:** the user unit `~/.config/systemd/user/ollama.service` now runs
`~/.local/share/ollama-0.40.11` (backup `.bak-0.22.1`); `~/.local/bin/ollama` symlinks to it;
LM Studio links were re-pointed. **Downloaded:** kev:4b, tev1:0.8b, d3:2b, granite4.2:3b, qwen3.5:4b,
bonsai-2:9b, lfm2.5:8b, gemma4:e2b/e4b/26b, nemotron-3-nano:4b (strands-decider is MLX-only and won't run here).
