# Handover: state of the project & where to take it

Written as a handover from the original builder to whoever maintains this next
(human or agent — if you're Claude/Opus, this is for you). Read `CLAUDE.md`
first, then `docs/index.md` to find the docs for whatever you're changing.

## What is solid and verified

Each of these was tested against **real local models** (not mocks) before its
commit — keep that discipline: all four topologies incl. parallel graphs; SSE
streaming + replay; skills/tools/personas + the AI wizards (skill/tool/team);
live model catalog + one-click installer; first-run provider install; Docker;
chat with persisted history; knowledge vault (Obsidian-compatible); image
generation via Fooocus; pixel studio; file delivery from agent output
(`File:` convention); tool delegation for models without native tool support.

## Known gaps / next steps (rough priority order)

1. **GitHub push is pending** — remote `git@github.com:alegizzi/langgraph-local`
   is configured and an SSH key exists at `~/.ssh/id_ed25519`; the owner still
   needs to add the pubkey to GitHub, then `git push -u origin main`.
2. **LM Studio integration is best-effort** — `lms get` is far less predictable
   than Ollama's API. If it matters, drive LM Studio's OpenAI-compat `/v1`
   more and the CLI less.
3. **Chat has no tool delegation** — team runs delegate tool work for non-tool
   models; chat only surfaces a guidance error. Port `_delegate_loop` usage
   into `engine.chat_stream` if chat tool use matters.
4. **Knowledge search is linear scan** — fine for hundreds of notes; if vaults
   grow large, add an index (sqlite FTS5 fits the codebase style).
5. **No unit-test suite** — verification is by driving the app. If contributors
   arrive, start with tests for `engine.extract_files`,
   `wizard._normalize_team`, `engine._find_delegate_request`, catalog parsing.
6. **Chat runs in the request thread** — fine single-user; run-manager-style
   background execution would allow multi-tab chat streaming.
7. **Generated images aren't inline in run timelines** — `generate_image`
   returns URLs; rendering them in the timeline is a small, high-delight win.

## Non-negotiables to preserve

- **Fully-local operation** — no cloud calls beyond model downloads and the
  ollama.com catalog scrape. No telemetry, no accounts.
- **Defensive parsing of ALL model output** — local models emit almost-right
  JSON/formats; repair, never trust, always fall back sanely.
- **The watchdog and concurrency caps** (`LLM_IDLE_TIMEOUT`, GPU-aware parallel
  capacity) — they exist because real hardware genuinely wedged. Removing them
  reintroduces multi-hour hangs.
- **Verification against real models before committing** — imports passing is
  not verification. Drive the feature end-to-end on `qwen2.5:7b` (or the
  relevant model) and assert on observed behavior.
- **Documentation same-commit rule** — see `docs/index.md` § keeping
  documentation current.
