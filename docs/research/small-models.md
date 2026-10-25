# Small & efficient local models (Oct 2026) — research for this machine

*2026-10-25. Machine: i7-8850H 6C/12T AVX2 · 31 GB RAM · Quadro P600 4 GB
(Pascal, helps prefill only) · Ollama 0.40.11. Sources: ollama.com library pages
(vendor claims, marked as such) + measurements on this machine (§ Measured).*

## How to read "efficient" on this hardware

- **Generation speed is RAM-bandwidth bound** (~2 tok/s for a dense 8B q8, ~4 tok/s
  for a 30B MoE with 3B active — hermes-local measurements). So the number that
  matters is **active parameters**, not total. MoE models with 1–4B active give
  8B–30B quality at 3B speed — as long as the total size fits in RAM.
- **Prefill dominates agent workloads** (tool schemas + system prompt are
  thousands of tokens). Keep GPU offload on; the P600 makes prefill ~5× faster.
- **One model resident at a time** — a team that uses 3 different models pays
  3 loads per run. Fewer, more capable small models beat many specialists here.
- **Native context** — Ollama clamps `num_ctx` to the GGUF's native context; check
  `ollama show <m>` before relying on long context (Hermes needs ≥ 64k).

## 1. "Jev" models — the decision-model family (siblings of Kev)

There is no model called "jev". **JevBench / the Jev Decision Index** is the
benchmark the new Ollama *decision* models are scored on; the family appeared on
ollama.com in Oct 2026 (Ollama ≥ 0.35–0.40.9 required). They don't chat: you send
a `state` plus typed questions to `POST /v1/systemone` and get probabilities back
in one forward pass (`choice` over 2–255 options, `noul` = probability a statement
is true, `score` = level on an ordered scale).

| Model | Publisher | Sizes (local) | Notes |
|---|---|---|---|
| **kev** | Jared Palmer | 0.8b (812 MB), 4b (2.7 GB q4), 9b (5.6 GB q4), 27b (MLX only) | text only; reference model of the family |
| **tev1** | Together AI | 0.8b (~0.8–1.5 GB), 4b (4.4 GB) | "fast classification"; ~2k-token working context |
| **d3** | vLLM Semantic Router | 2b (3.1 GB), 4b, 9b, 27b | text + **images**; JDI text 38.9 (2b) … 66.3 (27b) |
| nimble / nimble-v3 | Bespoke Labs | 9b | typed classification / routing |
| clef-flash | Cloudflare | 9b | vision; `clef` 27b is cloud-only |
| pplx-decider | Perplexity | 27b | fine-tune of Qwen3.8-27B |
| laya | Convai | 421M | ModernBERT-large fine-tune (encoder, tiny) |
| strands-decider | Strands Agents | 2b | **MLX-only builds → can't run on this Linux box** (pull fails "requires MLX support") |

**Why they matter for this app:** `router.classify` used to ask a chat model for
JSON (generate ~30 tokens, then repair-parse). A decision model answers the same
question in one pass with calibrated-ish probabilities and nothing to parse. Wired
in this session (see `docs/features/teams-runs/README.md` § Auto-router). Other
good fits, not yet built: `judge.py` hallucination-risk (`noul` "is the reply
supported by the evidence?"), Verifier PASS/FAIL gates, Resources link triage,
schedule "is this result worth notifying?".

## 2. Gemma siblings that run locally

The installed `gemma4:31b` is dense 31B: ≈1 tok/s here, not practical. Its siblings:

| Model | Params | Size | Ctx | Notes |
|---|---|---|---|---|
| **gemma4:e2b** | 2.3B effective (5.1B w/ embeddings) | 4.6–7.5 GB | 128k | text+image+**audio**, tools, thinking toggle |
| **gemma4:e4b** | 4.5B effective (8B) | 6.6–9.5 GB | 128k | same, stronger |
| gemma4:12b | 12B dense | 7.7 GB | 256k | dense → slow here; skipped |
| **gemma4:26b** | **MoE 25.2B / 3.8B active** | 16–19 GB | 256k | the usable "big Gemma" on CPU; Hermes candidate |
| gemma3n e2b/e4b | edge | — | — | predecessor of gemma4 e-models (installed gemma3 4b/12b can't call tools) |
| nemotron-3.5-bolt:e4b | NVIDIA post-train of Gemma 4 E4B + DFlash draft | 7.2–7.9 GB | 128k | multi-turn tool use claim; not downloaded |
| functiongemma | 270M | tiny | — | Gemma 3 270M tuned only for function calling (router/executor experiments) |
| embeddinggemma-2 | 270M–740M | — | — | multimodal embeddings (knowledge vault candidate) |

Unlike gemma3 (which needed the DELEGATE: protocol in `engine.py` because it has
no native tools), **gemma4 has native function calling**.

## 3. Newest efficient agent models (small → large)

Vendor claims unless measured below.

| Model | Size | Active | Why |
|---|---|---|---|
| granite4.2:3b | 2.2 GB | 3B dense | IBM, Apache-2.0, tools, thinking low/med/high, 128k |
| nemotron-3-nano:4b | 2.8 GB | 4B | NVIDIA agentic, 256k, listed for Hermes Agent |
| qwen3.5:4b (0.8b/2b also) | 3.3–4 GB | 4B | tools+thinking+**vision**, 256k ctx |
| bonsai-2:9b (2b/4b too) | **3.2 GB** for 9B | 9B ternary | ternary weights ≈ half a 4-bit file; tools, vision, 256k |
| lfm2.5:8b | 5.2 GB | ~1B (A1B) | Liquid AI, "fastest in class on CPU", built for chained tool calls |
| lfm2.5:24b | 15 GB | ~2B | RL-trained in agent harnesses |
| nemotron-3.5-lightning:30b | 19–25 GB | 3B | "execution layer of always-on agents", 1M ctx, Hermes-ready |
| laguna-xs-2.1 | 20 GB | 3B | agentic coding, SWE-bench V 70.9 % |
| qwen3.6:35b | 23–24 GB | ~3B (a3b) | newest Qwen agentic coding; too big next to the desktop |

## 4. Minimal-resources picks (≤ 4 GB RAM)

| Need | Pick | Fallback |
|---|---|---|
| Classify / route / yes-no | tev1:0.8b or kev:4b (decision) | d3:2b (with images) |
| Tool-calling worker | granite4.2:3b / qwen3.5:4b | smollm2:1.7b (installed) |
| Chat / summarise | qwen3.5:4b | phi4-mini:3.8b (installed) |
| Most quality per GB | bonsai-2:9b (3.2 GB) | — |

## Downloaded in this session

`kev:4b-q4_K_M`, `tev1:0.8b`, `d3:2b`, `granite4.2:3b`, `qwen3.5:4b`, `bonsai-2:9b`,
`lfm2.5:8b`, `gemma4:e2b`, `gemma4:e4b`, `gemma4:26b`, `nemotron-3-nano:4b`
(see § Measured for which actually work). Not downloaded on purpose: anything
≥ 19 GB (disk was 80 % full) and MLX-only builds.

## Measured on this machine

Script: `docs/research/scripts/bench_small_models.py` (raw JSON in `scripts/results/`).
Run 2026-10-25 on Ollama 0.40.11, one model at a time after 2 quiet minutes on the shared server.

**Routing (router.py's 7 task kinds, 14 labelled requests)**

| Model | Kind | Accuracy | Warm latency |
|---|---|---|---|
| **tev1:0.8b** | decision | **13/14** | **0.41 s** |
| d3:2b | decision | 13/14 | 0.81 s |
| kev:4b-q4_K_M | decision | 12/14 | 1.65 s |
| qwen2.5:7b | chat + JSON prompt | 12/14 | 3.82 s |
| gemma3:4b (old default classifier) | chat + JSON prompt | 10/14 | 3.66 s |

A first run (tev1 5/14 at 60 s per call) was invalid because another client was evicting models mid-run. Conclusion: tev1 is ~9× faster than the old classifier and more accurate, so it is first in `router.DECISION_PREFERENCE`.

**Chat / agent models** (~1k-token prefill + 160-token generation; native tool call; strict JSON)

| Model | Prefill tok/s | Gen tok/s | Load s | Tool call | JSON |
|---|---|---|---|---|---|
| **lfm2.5:8b** (A1B) | **209.6** | **16.6** | 7.8 | ✅ | ❌ |
| gemma4:e2b | 167.2 | 11.0 | 19.7 | ✅ | ✅ |
| granite4.2:3b | 126.0 | 8.1 | 8.0 | ✅ | ❌ |
| qwen3:4b (installed) | 119.8 | 7.7 | 4.8 | ✅ | ❌ |
| gemma4:e4b | 97.6 | 7.1 | 11.2 | ✅ | ✅ |
| qwen3.5:4b | 84.9 | 5.1 | 20.1 | ✅ | ✅ |
| qwen2.5:7b (workhorse) | 79.6 | 5.4 | 15.7 | ✅ | ✅ |
| nemotron-3-nano:4b | 77.7 | 5.8 | 7.3 | ✅ | ❌ |
| gemma4:26b (MoE 3.8B) | 65.1 | 6.4 | 33.6 | ✅ | ✅ |
| bonsai-2:9b (ternary) | 53.0 | 6.1 | 30.4 | ✅ | ✅ |

The JSON ❌ results come from a single strict test and are probably extra text or thinking output around the JSON. The app's defensive parsers usually recover this, but don't trust these models for raw JSON.

**Recommendations**
- **Fast tool worker / cheap steps:** `lfm2.5:8b`, about 3× qwen2.5:7b's generation speed with working tool calls.
- **Best small all-rounder (tools + clean JSON):** `gemma4:e2b`, or `gemma4:e4b` for more quality.
- **Big-model quality at small-model speed:** `gemma4:26b`, which generates faster than qwen2.5:7b. It's a Hermes candidate via a `-64k` variant (native ctx 256k).
- **Routing:** `tev1:0.8b`.
- Not yet tested: multi-step agent quality inside real Studio teams. These are single-call measurements.

