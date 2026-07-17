# CHECKPOINT — Pi/3D team verification (paused again 2026-07-16, LAST priority)

**Run 62 (7B verifier):** fabrication guard fired in production — Verifier
claimed "SMOKE TEST PASSED" over exit-1; the ⚠ NOT VERIFIED stamp landed.
Real bug: `sleep()` used without import + a smoke test with ~30s of real
sleeps.

**Run 63 (qwen2.5-coder:14b verifier):** salvage recovered every text-emitted
tool call (the 14B coder also prints calls as text). It iterated the full
budget but OSCILLATED between two `pir = MotionSensor(4)` edit variants —
undo/redo loop, never green. The wall is the Builder's smoke test trying to
mock/instantiate the MotionSensor; the loop guard can't see it because the
alternating arguments differ each call.

**Next levers when resuming (in order):**
1. Skill: forbid the smoke test from touching the SENSOR at all — "test the
   actuator functions (fade_on/fade_off) directly; never instantiate or mock
   MotionSensor in the test, the interactive loop is not the test's job".
2. Loop-guard v2: detect A/B oscillation (same file, alternating old_text
   pair) the way identical repeats are detected.
3. The Verifier stays on qwen2.5-coder:14b (DB team 18 only; seeds stay 7B).

---

# Original checkpoint (2026-07-14)

Paused mid-task on the user's request. This file is the resume point; delete it
once the task is finished.

## Where things stand

**Goal:** prove the Raspberry Pi Lab team (id 18) produces a green run
end-to-end, run the 3D Model Forge (id 20) for the first time, then commit.
(Arduino Forge already verified: run 54 compiled first try, independently
recompiled — 1278 bytes, 3% flash.)

**Run history of this session (runs are deleted, workspaces 59-61 may remain):**

| Run | Outcome | What it taught |
|-----|---------|----------------|
| 59 | Verifier finally called tools, but Builder ignored contract filenames (`File: /home/pi/...`, no smoke_test.py) | Builder prompt now pins EXACT filenames; Verifier now self-repairs missing files |
| 60 | Verifier re-ran the same failing test 11× through advisory warnings; run then killed by an *external* `import app` (see below) | Loop guard made **enforcing** (3rd identical call REFUSED); `AGENTS_SKIP_STARTUP=1` guards app.py side effects |
| 61 | Verifier **fabricated success** — reported "smoke test passed" while its last run_python was exit 1 (real bug: `led.value += 0.1` overshoots gpiozero's [0,1] and raises) | Engine now stamps `⚠ NOT VERIFIED` onto any agent report whose last execution-tool result failed (`TeamRunner._EXEC_PASS`); Pi skill got rule 4b (clamp PWM, prefer `led.pulse()`) |

## Already fixed & synced to the DB (do NOT redo)

- Team 18 agents (Builder filename contract, Verifier self-repair + never-run-main.py) — synced.
- Skill "Runnable Pi Program" incl. rule 4b (PWM clamp) — synced.
- engine.py: enforced loop guard, fabrication guard (`_EXEC_PASS` + NOT-VERIFIED postscript), `AGENTS_SKIP_STARTUP`.
- **None of this is committed yet** — commit alongside the other pending work
  (gauges, inpaint/outpaint, Fooocus UI, chat delegation).

## To resume

1. `rm -rf data/workspaces/59 data/workspaces/61` (stale test workspaces; 60 already removed).
2. Rerun: `curl -s -X POST localhost:5860/api/teams/18/runs -H 'Content-Type: application/json' -d '{"task":"a motion-activated night light that fades on"}'`
   — with the PWM-clamp rule the Builder has a real shot at green now.
3. **Never trust the Verifier's report** — verify independently:
   `cd data/workspaces/<run>; GPIOZERO_PIN_FACTORY=mock GPIOZERO_MOCK_PIN_CLASS=MockPWMPin python3 smoke_test.py`
   (a fabricated pass now carries an automatic "⚠ NOT VERIFIED" postscript, so
   check for that string in the Verifier's agent_end too).
4. First 3D Forge run: team 20, task e.g. `"a phone stand"`; verify with
   run_python model.py + check_stl model.stl in the workspace, look at the STL.
5. If Pi still can't go green after ~2 attempts, that's a 7B-repair ceiling —
   report honestly; consider pointing the Verifier at qwen2.5-coder:14b or
   qwen2.5:14b (slower, better debugger) as the next lever.
6. Delete test runs (`DELETE FROM events/runs WHERE ...` — there is no runs
   DELETE endpoint), remove workspaces, update `docs/features/skills-tools/README.md`
   §Flask-App-Factory-style notes if behavior changed, commit.

## Watch out for

- Wait for `/api/health` after `./restart.sh` before POSTing a run (a POST in
  the handover window once landed on the dying worker).
- `import app` without `AGENTS_SKIP_STARTUP=1` marks live runs as interrupted.
- Ollama holds the GPU after runs (~5 min keep_alive) — don't start Fooocus
  (API or UI) immediately after a team run, the runner crashes.
