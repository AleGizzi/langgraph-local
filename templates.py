"""Project templates — ready-to-run blueprints for the things local models on
this hardware are actually good at.

Each template is a curated project from the studio review. "Instantiating" one
turns it into a real object you can use or trigger later:

  * kind "schedule" → creates a DISABLED scheduled task (you review + enable it),
  * kind "team"     → creates a real team (e.g. a tool-builder pipeline),
  * kind "chat"     → returns a chat preset (model + system prompt + tools) the
                      Chat page opens pre-configured,
  * kind "team_ref" → opens an existing seeded team by name.

Nothing here fires automatically or spends a run on creation — instantiate only
writes the blueprint. No AI is involved in this module; it is plain data.
"""
import storage

# Model preference ladders, resolved against what's actually installed at
# instantiate time (so a template never points at a model you don't have).
_GENERAL = ["qwen2.5:7b", "qwen2.5:14b", "llama3.1:8b", "llama3.2:3b", "mistral:7b"]
_CODER = ["qwen2.5-coder:7b", "qwen2.5-coder:14b", "deepseek-coder:6.7b", "codestral:22b"]
_TINY = ["qwen2.5:3b", "llama3.2:3b", "qwen2.5:1.5b", "phi3.5"]


def _pick(prefer: list, models: dict) -> str:
    """First preferred model that's installed, else any Ollama model, else ''."""
    installed = list(models.get("ollama") or [])
    bases = {m.split(":")[0]: m for m in installed}
    for want in prefer:
        if want in installed:
            return want
        base = want.split(":")[0]
        if base in bases:            # same family, whatever tag is installed
            return bases[base]
    return installed[0] if installed else ""


# ---- the catalogue --------------------------------------------------------
# Ordered by the review's "start here" ranking. Each has display metadata plus
# a builder that returns the concrete payload for its kind.

TEMPLATES = [
    {
        "id": "tool-forge", "icon": "🔧", "title": "Personal tool forge",
        "group": "Build", "kind": "team", "star": True,
        "what": "A Builder+Verifier pipeline that writes a small, reusable Python "
                "tool from your description — and proves it runs before it's done.",
        "builds_on": "pipeline topology · quality loop · run_python",
        "tier": "coder 7B", "effort": "M",
        "realism": "The Verifier can't fake exit-0. Best for self-contained tools "
                   "under ~150 lines. 10–20 min per run.",
        "goto": "the new team — give it a task like “a tool that resizes every "
                "image in a folder to 800px”, then Run.",
    },
    {
        "id": "pc-health", "icon": "🩺", "title": "PC health watchdog",
        "group": "Automation", "kind": "schedule", "star": True,
        "what": "Hourly system check that flags low disk / RAM / GPU pressure and "
                "notifies you — catches Fooocus/Ollama zombies eating the 4 GB card.",
        "builds_on": "schedules · system_info · notify",
        "tier": "general 7B", "effort": "S",
        "realism": "High reliability — factual tool output, the model just judges a "
                   "threshold. Seeded disabled; enable it on the Schedules page.",
        "goto": "Schedules — review it and flip it on.",
    },
    {
        "id": "voice-notes", "icon": "🎙️", "title": "Voice-memo → notes",
        "group": "Knowledge", "kind": "chat", "star": True,
        "what": "Paste (or dictate) a transcript; get decisions + action items "
                "extracted and filed to a meetings/ folder in your vault.",
        "builds_on": "Chat · knowledge_write",
        "tier": "general 7B", "effort": "S",
        "realism": "Strong — grounded extraction from text in front of the model, "
                   "which sidesteps the recall weakness entirely.",
        "goto": "Chat, pre-loaded — paste a transcript and send.",
    },
    {
        "id": "daily-digest", "icon": "📰", "title": "Daily local-LLM digest",
        "group": "Automation", "kind": "schedule",
        "what": "Every morning: web-search AI/local-LLM news, summarize, save a "
                "dated vault note, and ping you with the headlines.",
        "builds_on": "schedules · web_search · knowledge · notify",
        "tier": "general 7B", "effort": "S",
        "realism": "Solid for a digest; a 7B often summarizes from snippets — good "
                   "enough to skim, not citation-grade.",
        "goto": "Schedules — enable when you want it.",
    },
    {
        "id": "knowledge-gardener", "icon": "🌱", "title": "Knowledge gardener",
        "group": "Knowledge", "kind": "schedule",
        "what": "Weekly pass over recent notes proposing [[wikilinks]] between "
                "them, growing a real graph over time.",
        "builds_on": "schedules · knowledge tools · graph view",
        "tier": "general 14B if you can wait", "effort": "S",
        "realism": "Connections are plausible, not deep; vault search is a linear "
                   "scan — fine at hundreds of notes.",
        "goto": "Schedules — enable it and let a few weeks accumulate.",
    },
    {
        "id": "price-watcher", "icon": "🏷️", "title": "Marketplace price watcher",
        "group": "Automation", "kind": "schedule",
        "what": "Daily check of a JS-rendered listing via the real headless "
                "browser, logging price changes to a vault note.",
        "builds_on": "browser (MCP) · schedules · knowledge",
        "tier": "general 7B", "effort": "M",
        "realism": "The one job where JS rendering matters. Chromium is heavy — "
                   "don't poll every few minutes. Needs the browser tool enabled.",
        "goto": "Schedules — set your listing URL in the prompt, then enable.",
    },
    {
        "id": "warranty-tracker", "icon": "🧾", "title": "Warranty & inventory tracker",
        "group": "Knowledge", "kind": "chat",
        "what": "Dictate receipts; the assistant extracts item / date / price / "
                "warranty into a searchable vault folder.",
        "builds_on": "Chat · knowledge tools",
        "tier": "general 7B", "effort": "S",
        "realism": "Good extraction; keyword-overlap retrieval is fine at household "
                   "scale.",
        "goto": "Chat, pre-loaded — start adding purchases.",
    },
    {
        "id": "decision-brief", "icon": "⚖️", "title": "Decision brief",
        "group": "Knowledge", "kind": "chat",
        "what": "Lay out a real decision; the assistant argues both sides and "
                "surfaces considerations you hadn't listed — then you decide.",
        "builds_on": "Chat",
        "tier": "general 7B", "effort": "S",
        "realism": "Clarifying, not authoritative — it has no tools by default, so "
                   "treat it as a thinking aid, not a source of facts.",
        "goto": "Chat, pre-loaded — describe your decision.",
    },
]


def list_templates() -> list:
    """Display metadata only (no payloads)."""
    keep = ("id", "icon", "title", "group", "kind", "star", "what",
            "builds_on", "tier", "effort", "realism", "goto")
    return [{k: t.get(k) for k in keep} for t in TEMPLATES]


# ---- builders (payload per kind) ------------------------------------------

def _build_schedule(tid: str, m: dict) -> dict:
    g = _pick(_GENERAL, m)
    common = {"enabled": False, "notify": True, "team_id": None}

    def agent(prompt, tools, temp=0.3):
        return {"agent": {"name": "Scheduled agent", "provider": "ollama",
                          "model": g, "system_prompt": prompt,
                          "params": {"temperature": temp}, "tools": tools,
                          "skills": []}}

    if tid == "pc-health":
        return {**common, "name": "PC health watchdog", "interval_seconds": 3600,
                "prompt": "Check this machine's health with the system_info tool: "
                "disk space, free RAM, GPU/VRAM, and any process using an unusual "
                "amount of memory. If anything looks bad (low disk, RAM nearly full, "
                "a stuck Fooocus/Ollama process), notify me with a one-line summary "
                "of the problem. If everything is fine, do NOT notify.",
                **agent("You are a vigilant system monitor. Be terse and factual.",
                        ["system_info", "notify"])}
    if tid == "daily-digest":
        return {**common, "name": "Daily local-LLM digest", "interval_seconds": 86400,
                "knowledge_folder": "ai-news",
                "prompt": "Search the web for the most important AI and local-LLM "
                "news from the last day. Read the best 2-3 sources, then write a "
                "short digest: 4-6 bullet highlights, then a 'What this means' "
                "section with 2 concrete insights and 1 idea worth trying locally.",
                **agent("You are a diligent research assistant. Report concisely.",
                        ["web_search", "read_webpage", "knowledge", "notify"])}
    if tid == "knowledge-gardener":
        return {**common, "name": "Weekly knowledge gardener",
                "interval_seconds": 604800, "notify": False,
                "prompt": "Review the notes recently added to my knowledge vault "
                "using the knowledge tools. Identify 3-5 pairs of notes that are "
                "related but not yet linked, and for each, add a [[wikilink]] "
                "connecting them with a one-line note on why they relate.",
                **agent("You are a careful librarian tending a personal knowledge "
                        "graph. Only link notes that genuinely relate.",
                        ["knowledge"])}
    if tid == "price-watcher":
        return {**common, "name": "Marketplace price watcher", "interval_seconds": 86400,
                "track_number": True, "knowledge_folder": "price-watch",
                "prompt": "Open this listing with the browser tool and read the "
                "current price: <PASTE THE LISTING URL HERE>. Report the price as a "
                "single number with the date. Save it to the price-watch folder so "
                "it accumulates, and notify me if it dropped since last time.",
                **agent("You extract one number from a web page precisely. Do not "
                        "guess if the page didn't load.",
                        ["browser", "knowledge", "notify"])}
    return {}


def _build_chat(tid: str, m: dict) -> dict:
    g = _pick(_GENERAL, m)
    presets = {
        "voice-notes": {
            "name": "Notes extractor",
            "system_prompt": "You turn raw transcripts into structured notes. From "
            "the text the user pastes, extract: (1) Decisions made, (2) Action items "
            "with an owner if stated, (3) Open questions. Be faithful to the source — "
            "never invent. When asked, save the result to the 'meetings' folder with "
            "today's date using the knowledge tool.",
            "tools": ["knowledge", "current_datetime"],
            "starter": "Paste your transcript below and I'll pull out decisions, "
                       "action items and open questions.",
        },
        "warranty-tracker": {
            "name": "Inventory keeper",
            "system_prompt": "You maintain a household inventory. When the user "
            "describes a purchase or receipt, extract item, purchase date, price, and "
            "warranty length into a clean record, and save it to the 'inventory' "
            "folder using the knowledge tool. When asked 'what's under warranty', "
            "search that folder and answer from it.",
            "tools": ["knowledge", "current_datetime"],
            "starter": "Tell me about a purchase (what, when, price, warranty) and "
                       "I'll file it. Later, ask me what's still under warranty.",
        },
        "decision-brief": {
            "name": "Decision partner",
            "system_prompt": "You help think through decisions. Given the user's "
            "situation, lay out the strongest case FOR and AGAINST, surface "
            "considerations and risks they may not have listed, and end with the key "
            "questions that would settle it. Do not pretend to certainty you don't "
            "have; you have no tools, so flag anything that needs real data.",
            "tools": [],
            "starter": "Describe the decision you're weighing and what matters to "
                       "you, and I'll argue both sides.",
        },
    }
    p = presets.get(tid)
    if not p:
        return {}
    valid = _valid_tools()
    return {"preset": {
        "name": p["name"], "provider": "ollama", "model": g,
        "system_prompt": p["system_prompt"],
        "tools": [t for t in p["tools"] if t in valid],
        "skills": [], "params": {"temperature": 0.3},
        "starter": p["starter"],
    }}


def _build_team(tid: str, m: dict) -> dict:
    if tid != "tool-forge":
        return {}
    coder = _pick(_CODER, m) or _pick(_GENERAL, m)
    valid = _valid_tools()
    builder_tools = [t for t in ["files"] if t in valid]
    verifier_tools = [t for t in ["files", "run_python"] if t in valid]
    return {"team": {
        "name": "Personal Tool Forge",
        "icon": "🔧",
        "description": "Describe a small utility; the Builder writes a single "
                       "self-contained Python tool and the Verifier proves it runs "
                       "before the team calls it done.",
        "topology": "pipeline",
        "settings": {"quality_loop": True, "max_revisions": 5},
        "agents": [
            {"name": "Builder", "role": "Tool author", "provider": "ollama",
             "model": coder, "temperature": 0.2, "tools": builder_tools, "skills": [],
             "system_prompt": "You write ONE small, self-contained Python tool that "
             "does exactly what the user asked — no more. Standard library only "
             "unless a dependency is clearly needed. Include a short docstring, a "
             "`main()` with a tiny self-test using example inputs, and a "
             "`if __name__ == '__main__': main()` guard. Deliver it as a real file "
             "with a `File: <name>.py` block so it lands in the workspace."},
            {"name": "Verifier", "role": "Runner", "provider": "ollama",
             "model": coder, "temperature": 0.1, "tools": verifier_tools, "skills": [],
             "system_prompt": "You verify the Builder's tool. Run it with the "
             "run_python tool. If it errors or the self-test fails, say exactly what "
             "broke and send it back for a fix. Only approve when it runs cleanly "
             "(exit code 0) and the self-test output is correct. Never claim it works "
             "without a real run result in front of you."},
        ],
    }}


def _valid_tools() -> set:
    try:
        import tools as tools_mod
        return set(tools_mod.valid_tool_names())
    except Exception:  # noqa: BLE001
        return set()


def _find_team_by_keywords(*words) -> dict:
    for t in storage.list_teams():
        name = (t.get("name") or "").lower()
        if any(w in name for w in words):
            return t
    return None


def instantiate(tid: str) -> dict:
    """Create the real object for a template. Returns a dict with `ok`, `kind`,
    a `goto` hash route for the UI, and a human `message`."""
    tpl = next((t for t in TEMPLATES if t["id"] == tid), None)
    if not tpl:
        return {"ok": False, "error": "unknown template"}
    import providers
    models = providers.list_models()
    if not (models.get("ollama") or models.get("lmstudio")):
        return {"ok": False, "error": "No local models are installed yet — install "
                "one from the Models page first."}
    kind = tpl["kind"]

    if kind == "schedule":
        spec = _build_schedule(tid, models)
        if not spec:
            return {"ok": False, "error": "template has no schedule spec"}
        row = storage.create_schedule(spec)
        return {"ok": True, "kind": kind, "id": row["id"], "goto": "#/schedules",
                "message": f"Created the “{spec['name']}” schedule — disabled. "
                           "Review it and switch it on."}

    if kind == "team":
        spec = _build_team(tid, models)
        if not spec:
            return {"ok": False, "error": "template has no team spec"}
        row = storage.create_team(spec["team"])
        return {"ok": True, "kind": kind, "id": row["id"],
                "goto": f"#/team/{row['id']}",
                "message": f"Created the “{spec['team']['name']}” team. Open it, give "
                           "it a task, and Run."}

    if kind == "chat":
        spec = _build_chat(tid, models)
        if not spec:
            return {"ok": False, "error": "template has no chat preset"}
        return {"ok": True, "kind": kind, "preset": spec["preset"], "goto": "#/chat",
                "message": "Opening Chat, pre-configured."}

    if kind == "team_ref":
        team = _find_team_by_keywords(*tpl.get("match", []))
        if not team:
            return {"ok": False, "error": "that seeded team isn't present — it may "
                    "have been deleted; re-seed or build it from scratch."}
        return {"ok": True, "kind": kind, "id": team["id"],
                "goto": f"#/team/{team['id']}",
                "message": f"Opening the “{team['name']}” team."}

    return {"ok": False, "error": f"unknown kind: {kind}"}
