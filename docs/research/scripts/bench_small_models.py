#!/usr/bin/env python3
"""Benchmark small local models on THIS machine (CPU + 4 GB P600).

Chat models:   prefill tok/s, generation tok/s, load time, one native tool-call
               test, one strict-JSON instruction test.
Decision models (/v1/systemone): routing accuracy on router.py's 7 task kinds
               + latency, compared with the chat-model JSON classifier.

Runs models ONE AT A TIME (each load evicts the previous one — only one fits).
Usage:  python3 bench_small_models.py chat qwen3.5:4b lfm2.5:8b ...
        python3 bench_small_models.py route tev1:0.8b kev:4b-q4_K_M gemma3:4b
Writes JSON next to this script in results/.
"""
import json
import os
import re
import sys
import time
import urllib.request

OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
HERE = os.path.dirname(os.path.abspath(__file__))


def post(path, body, timeout=900):
    req = urllib.request.Request(OLLAMA + path, json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


PROMPT = ("Explain in about 120 words why a mixture-of-experts language model can "
          "generate text faster than a dense model of the same total size. ") * 1
FILLER = ("Context paragraph about local inference on laptops with limited memory "
          "bandwidth and small GPUs. ") * 60  # ~1k tokens of prefill

TOOLS = [{"type": "function", "function": {
    "name": "get_weather", "description": "Current weather for a city",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}},
                   "required": ["city"]}}}]


def bench_chat(model):
    res = {"model": model}
    t = time.time()
    r = post("/api/generate", {"model": model, "prompt": FILLER + PROMPT, "stream": False,
                               "think": False, "options": {"num_predict": 160, "temperature": 0}})
    res["wall_s"] = round(time.time() - t, 1)
    res["load_s"] = round(r.get("load_duration", 0) / 1e9, 1)
    pe, pd = r.get("prompt_eval_count", 0), r.get("prompt_eval_duration", 1)
    ec, ed = r.get("eval_count", 0), r.get("eval_duration", 1)
    res["prefill_tps"] = round(pe / (pd / 1e9), 1) if pd else None
    res["gen_tps"] = round(ec / (ed / 1e9), 1) if ed else None
    # Native tool call
    try:
        r = post("/api/chat", {"model": model, "stream": False, "tools": TOOLS, "think": False,
                               "messages": [{"role": "user", "content": "What's the weather in Rosario?"}],
                               "options": {"temperature": 0}})
        calls = r.get("message", {}).get("tool_calls") or []
        res["tool_call"] = bool(calls) and calls[0]["function"]["name"] == "get_weather" and \
            "rosario" in json.dumps(calls[0]["function"].get("arguments", {})).lower()
    except Exception as e:  # noqa: BLE001 - model without tool support → 400
        res["tool_call"] = f"error: {str(e)[:80]}"
    # Strict JSON instruction following
    r = post("/api/generate", {"model": model, "stream": False, "think": False,
                               "prompt": 'Reply with ONLY this JSON, filled in: {"capital_of_france": "...", "two_plus_two": 0}',
                               "options": {"temperature": 0, "num_predict": 60}})
    txt = r.get("response", "")
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
        res["json_ok"] = str(d.get("capital_of_france", "")).lower() == "paris" and int(d.get("two_plus_two", 0)) == 4
    except Exception:  # noqa: BLE001
        res["json_ok"] = False
    return res


ROUTE_SET = [
    ("hi there!", "trivial"),
    ("convert 5 miles to km", "trivial"),
    ("what is the difference between a process and a thread?", "general"),
    ("write a short email asking my landlord to fix the heater", "general"),
    ("write a python function that removes duplicates from a list keeping order", "code"),
    ("fix this bash script: for f in *.txt do echo $f done", "code"),
    ("build a multi-file Flask app with auth, SQLAlchemy models, migrations and tests", "code_hard"),
    ("refactor this 3000-line legacy C++ module into separate classes with unit tests", "code_hard"),
    ("what are today's top headlines about local LLMs?", "research"),
    ("find the latest Ollama release notes and summarize them", "research"),
    ("a train leaves at 3pm at 80km/h, another at 4pm at 100km/h; when does the second catch up?", "reasoning"),
    ("plan a 3-step migration of a database with zero downtime and justify each step", "reasoning"),
    ("write a haiku about a sleepy GPU", "creative"),
    ("brainstorm 10 catchy names for a fitness app", "creative"),
]


def bench_route(model, decision):
    sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..")))
    import router  # the app's own prompts/criteria
    hits, lat, rows = 0, [], []
    for text, want in ROUTE_SET:
        t = time.time()
        if decision:
            got = (router._classify_decision(text, model) or ("<fail>", ""))[0]
        else:
            r = post("/api/generate", {"model": model, "stream": False, "think": False,
                                       "prompt": router._CLASSIFY_PROMPT.format(request=text),
                                       "options": {"temperature": 0, "num_predict": 80}})
            m = re.search(r'"kind"\s*:\s*"([a-z_]+)"', r.get("response", ""))
            got = m.group(1) if m else "<unparsed>"
        lat.append(time.time() - t)
        hits += got == want
        rows.append({"text": text, "want": want, "got": got})
    return {"model": model, "decision": decision, "accuracy": f"{hits}/{len(ROUTE_SET)}",
            # first call includes model load; report warm median separately
            "first_s": round(lat[0], 2), "median_warm_s": round(sorted(lat[1:])[len(lat[1:]) // 2], 2),
            "rows": rows}


if __name__ == "__main__":
    mode, models = sys.argv[1], sys.argv[2:]
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    out = []
    for m in models:
        try:
            if mode == "chat":
                r = bench_chat(m)
            else:
                base = m.split(":")[0]
                r = bench_route(m, base in ("tev1", "kev", "d3", "strands-decider", "nimble"))
        except Exception as e:  # noqa: BLE001
            r = {"model": m, "error": str(e)[:200]}
        print(json.dumps({k: v for k, v in r.items() if k != "rows"}), flush=True)
        out.append(r)
    path = os.path.join(HERE, "results", f"{mode}-{time.strftime('%Y%m%d-%H%M')}.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
    print("wrote", path)
