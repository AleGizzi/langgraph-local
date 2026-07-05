"""Default teams created on first launch so the app is useful immediately."""
import storage

GENERAL = "qwen2.5:7b"
CODER = "qwen2.5-coder:7b"


def _agent(name, role, model, prompt, temperature=0.7, tools=None, provider="ollama"):
    return {"name": name, "role": role, "provider": provider, "model": model,
            "system_prompt": prompt, "temperature": temperature, "tools": tools or []}


SEED_TEAMS = [
    {
        "name": "Research & Report",
        "icon": "📝",
        "description": "Analyst gathers and structures facts, writer turns them into a "
                       "polished report, reviewer enforces quality with a revision loop.",
        "topology": "pipeline",
        "settings": {"quality_loop": True, "max_revisions": 2},
        "agents": [
            _agent("Analyst", "Research analyst", GENERAL,
                   "You are a meticulous research analyst. Break the task down, lay out "
                   "the key facts, angles, assumptions and structure needed to answer it "
                   "thoroughly. Output an organized brief with sections and bullet "
                   "points that a writer can turn into a final document. Be concrete "
                   "and specific; avoid filler.", 0.4),
            _agent("Writer", "Report writer", GENERAL,
                   "You are a professional writer. Using the analyst's brief, write the "
                   "complete, final deliverable in clean Markdown: clear title, logical "
                   "sections, tight prose. No placeholders, no 'TODO', no meta text — "
                   "the reader gets a finished document.", 0.7),
            _agent("Reviewer", "Quality reviewer", GENERAL,
                   "You are a demanding editor. Check the document for completeness "
                   "against the task, factual coherence, structure and clarity.", 0.2),
        ],
    },
    {
        "name": "Code Squad",
        "icon": "💻",
        "description": "Architect designs, coder implements, reviewer audits — a "
                       "pipeline for producing working code with tests.",
        "topology": "pipeline",
        "settings": {"quality_loop": True, "max_revisions": 2},
        "agents": [
            _agent("Architect", "Software architect", GENERAL,
                   "You are a pragmatic software architect. Produce a short, concrete "
                   "implementation plan: files, functions, data flow, edge cases, and "
                   "how to test it. Keep it minimal — no over-engineering.", 0.3),
            _agent("Coder", "Implementation engineer", CODER,
                   "You are an expert programmer. Implement the plan completely in "
                   "clean, idiomatic, runnable code. Include every file in full inside "
                   "fenced code blocks with the filename indicated. Add brief usage "
                   "instructions and a small test or example run.", 0.2),
            _agent("Code Reviewer", "Code reviewer", CODER,
                   "You are a strict code reviewer. Verify the code is complete, "
                   "correct, runnable and actually solves the task.", 0.1),
        ],
    },
    {
        "name": "Task Force",
        "icon": "🧭",
        "description": "A supervisor delegates dynamically between a researcher and a "
                       "writer until the task is done, then synthesizes the answer.",
        "topology": "supervisor",
        "settings": {"max_steps": 6},
        "agents": [
            _agent("Coordinator", "Supervisor", GENERAL,
                   "You are an efficient project coordinator who plans minimal steps "
                   "to complete tasks well.", 0.2),
            _agent("Researcher", "Researcher", GENERAL,
                   "You are a researcher. Answer the specific assignment you are given "
                   "with accurate, well-organized information and reasoning.", 0.4),
            _agent("Editor", "Writer/editor", GENERAL,
                   "You are a skilled editor. Turn material into polished, well-"
                   "structured prose exactly as assigned.", 0.6),
        ],
    },
    {
        "name": "Quick Assistant",
        "icon": "⚡",
        "description": "A single fast agent with calculator and file tools for "
                       "one-shot tasks.",
        "topology": "single",
        "settings": {},
        "agents": [
            _agent("Assistant", "Generalist", GENERAL,
                   "You are a capable assistant. Complete the task directly and "
                   "produce a clear, complete answer in Markdown.", 0.5,
                   tools=["calculator", "current_datetime", "files"]),
        ],
    },
]


def seed_if_empty():
    if storage.count_teams() == 0:
        for t in SEED_TEAMS:
            storage.create_team(t)
        return True
    return False
