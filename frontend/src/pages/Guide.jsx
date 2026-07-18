import React, { useEffect, useState } from "react";

/* In-app user documentation. Original, hand-written overview of every feature so
 * users understand what the app can do. Left rail = sections; right = content.
 * Keep this in sync when features change (same spirit as help.py's guide). */

const SECTIONS = [
  {
    id: "overview", icon: "✨", title: "Overview",
    body: [
      ["p", "Agent Studio is a fully-local app for building and running teams of AI agents on your own models (Ollama / LM Studio). Nothing you do leaves your machine — no cloud, no accounts, no telemetry."],
      ["p", "You can build agent teams that work together on a task, chat with a single model, automate recurring tasks on a schedule, generate images and short videos, keep a knowledge vault, and even have agents build working apps or improve this app's own code."],
      ["tip", "New here? Start on the Agents page (the Dashboard shows what you have and how it's being used), then open Chat to talk to a model, or the Studio tab to run a team."],
    ],
  },
  {
    id: "agents", icon: "🎭", title: "Agents: teams & personas",
    body: [
      ["h", "Teams"],
      ["p", "A team is a set of agents that collaborate on a task using a topology: pipeline (each agent hands off to the next), supervisor (a coordinator delegates), graph (a custom flow you draw), or single. Open a team, give it a task, and watch it work in real time; the result and any files it produced are saved as a run."],
      ["p", "Create a team by hand, or click \"🪄 Describe a team\" and a local model drafts the whole team from a sentence. A team can loop for quality: the last agent reviews the work and sends it back with fixes until it's good."],
      ["h", "Personas"],
      ["p", "Personas are reusable agent definitions — a model, a system prompt, hyperparameters, tools and skills, wrapped in a Pokédex-style card (its creature sprite reflects the model family and size). Load a persona into Chat, or drop it into a team."],
      ["h", "Dashboard"],
      ["p", "The default tab shows totals, which personas you've actually used most (from chats and team runs), your recent runs and chats, and your most-run teams — a quick pulse on your activity."],
    ],
  },
  {
    id: "chat", icon: "💬", title: "Chat",
    body: [
      ["p", "Talk to one model directly with the same settings as a persona — prompt, hyperparameters, tools, skills. Your chat history is kept in the left rail."],
      ["h", "Context gauge"],
      ["p", "A bar above the input shows how full the model's context window is (tokens used vs the window size, message count, tok/s). When it turns red the model is starting to forget the oldest messages — a good moment to start a new chat."],
      ["h", "Tools in chat"],
      ["p", "Give a chat agent tools and it can use them. Models that can't call tools natively (like some reasoning models) still get them: their tool requests are automatically delegated to a tool-capable model behind the scenes."],
      ["h", "Spawning agents"],
      ["p", "With the \"agents\" tool enabled, a chat agent can consult another persona, or have two personas discuss a topic. Each spawned agent appears as its own bubble showing the real model and time it took — proof it's a genuine separate call, not the main model role-playing. Blocked automatically when free memory is low."],
      ["h", "Hallucination check"],
      ["p", "Optional (in chat settings): after each reply, a small model estimates how much of it is confident-but-unverifiable, shown as a per-reply pill and a conversation average. It's an estimate to guide skepticism — not a measurement."],
    ],
  },
  {
    id: "build", icon: "🏗️", title: "Building apps & hardware",
    body: [
      ["p", "Several seed teams turn an idea into something that is PROVEN to work, not just plausible — the verifying agent runs a real check and won't claim success without it."],
      ["ul", [
        "Flask App Factory — a single-file web app; the Verifier runs a smoke test until it passes. Run the result with python app.py.",
        "App Factory Pro — a bigger, multi-file app with SQLite persistence and real business rules; loops (up to 6 rounds) until a domain smoke test passes.",
        "Pair Builder — two agents in a loop (Driver writes and runs code, Navigator reviews) that build a new app or improve this one.",
        "Raspberry Pi Lab — gpiozero GPIO code, run here against a mock pin factory (no Pi needed).",
        "Arduino Forge — an AVR sketch, compiled with the real arduino-cli toolchain.",
        "3D Model Forge — a parametric model exported to STL and checked watertight/printable.",
        "App Improver — reads and edits this app's own source with minimal diffs (review with git diff, restart to apply).",
      ]],
      ["tip", "Honest expectation: a local 7B–14B model can reliably build small-to-moderate apps and MVPs. Genuinely complex, pro-level apps usually need several rounds or a bigger model — the teams loop and self-verify to get as far as they can, and report honestly rather than fake success."],
    ],
  },
  {
    id: "schedules", icon: "⏰", title: "Schedules",
    body: [
      ["p", "Run an agent (or a whole team) unattended on an interval — daily web checks, tracked metrics, recurring research. Create one on the Schedules page; describe your task and click \"🪄 Draft with AI\" to fill in the fields automatically."],
      ["ul", [
        "Track a number — pulls the first number from each result and charts its evolution (e.g. a currency rate day over day).",
        "Save to a knowledge folder — logs each finding as a dated note so it accumulates.",
        "Notify me — a desktop popup + the in-app bell when it finishes.",
        "Run history & logs — every run stores a full execution log; open the 📋 log on any run to debug what happened. Team runs link to the full timeline on the Runs page.",
      ]],
      ["p", "Four ready-made templates come seeded but OFF (opt-in): a daily AI-news digest, a currency tracker, a PC health check, and a weekly knowledge gardener — plus tool-discovery, activity-summary and model-watch ideas. Enable the ones you want."],
      ["tip", "Schedules run only while the app is open. Install it as a desktop app (Settings → Hardware) or the systemd service to keep it running 24/7."],
    ],
  },
  {
    id: "knowledge", icon: "📚", title: "Knowledge vault",
    body: [
      ["p", "A shared Markdown vault where team deliverables and agent findings are archived. It's a real Obsidian/Logseq vault on disk (data/knowledge) — open it in those apps directly, no import."],
      ["p", "Notes live in sub-vaults (topic folders). Each folder has a 🗑 to delete a whole topic at once (the \"forget it\" move), and each note has its own. The 🕸️ Graph view shows notes as dots colored by sub-vault with [[wikilinks]] as connections; faded dots are \"ghost\" notes (linked but not yet written). Click a dot to open it."],
    ],
  },
  {
    id: "tools", icon: "🧰", title: "Skills & Tools",
    body: [
      ["h", "Skills"],
      ["p", "A skill is a reusable block of instructions appended to an agent's system prompt (e.g. a code-review checklist, a report format). Attach skills to agents in the team editor or on a persona. Create them by hand or with an AI wizard."],
      ["h", "Tools"],
      ["p", "Tools are functions agents can call while working: builtin ones (calculator, web search, read webpage, run code, file access, knowledge, system info, notify, image generation, spawn agents, edit this app's files) plus custom Python tools you write."],
      ["p", "Custom tools are editable .py files. Builtin tools can't be edited in place, but each has a \"view / fork\" button — see its source, or fork it into an editable custom tool that wraps it."],
    ],
  },
  {
    id: "media", icon: "🎨", title: "Images & video",
    body: [
      ["h", "Image generation"],
      ["p", "On the Models page → Image generation, generate images locally with Fooocus (SDXL). Modify an existing image with vary, upscale, restyle (ControlNet), inpaint (paint a mask over the part to change) or outpaint (extend the canvas). An AI prompt assistant helps write prompts, and jobs queue so you can batch them."],
      ["p", "Prefer Fooocus's own interface? Launch it standalone from the Models page (same models, its own window). It and the app's image server share the GPU, so only one runs at a time."],
      ["h", "Video Maker"],
      ["p", "Describe a video idea; an LLM plans the shots, Fooocus renders one still per shot, and ffmpeg assembles them into an mp4 with pan/zoom and crossfades. This is slideshow-style video — true frame-by-frame video generation needs far more GPU than a typical local machine has."],
    ],
  },
  {
    id: "news", icon: "📰", title: "AI News & Resources",
    body: [
      ["p", "A curated link store in three tabs — AI news, local-LLM trainings, and tools. Add links by hand, or click \"Refresh with agent\" to have a web-researching agent find fresh ones. Pair it with a schedule to keep it current automatically."],
    ],
  },
  {
    id: "models", icon: "🧠", title: "Models, Setup & Settings",
    body: [
      ["p", "Models page: your installed models (click any for what it's best used for), plus the full Ollama catalog assessed against your hardware, with one-click install."],
      ["p", "Setup page: install and connect Ollama / LM Studio. Settings page: your hardware, parallel-agent capacity, installed-model assessments, and a recommended \"dream team\" for your PC. Settings → Hardware also has \"Install as app\" to add Agent Studio to your desktop launcher."],
    ],
  },
  {
    id: "calcifer", icon: "🔥", title: "Calcifer & notifications",
    body: [
      ["p", "Calcifer is the little fire-spirit assistant in the corner of every page. Ask it anything about the app — where things are, how to use them, or how to set up a scheduled task."],
      ["p", "The 🔔 bell in the sidebar collects notifications from scheduled agents and the notify tool (desktop popups fire too). Critical ones are marked; click one to jump to what it's about."],
    ],
  },
];

function Block([type, content], i) {
  if (type === "h") return <h3 key={i}>{content}</h3>;
  if (type === "p") return <p key={i}>{content}</p>;
  if (type === "tip") return <div key={i} className="guide-tip">💡 {content}</div>;
  if (type === "ul") return <ul key={i}>{content.map((li, j) => <li key={j}>{li}</li>)}</ul>;
  return null;
}

export default function Guide() {
  const [active, setActive] = useState(SECTIONS[0].id);

  useEffect(() => {
    const els = SECTIONS.map((s) => document.getElementById("guide-" + s.id)).filter(Boolean);
    const obs = new IntersectionObserver((entries) => {
      const vis = entries.filter((e) => e.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (vis) setActive(vis.target.id.replace("guide-", ""));
    }, { rootMargin: "-80px 0px -70% 0px" });
    els.forEach((el) => obs.observe(el));
    return () => obs.disconnect();
  }, []);

  return (
    <div className="guide-layout">
      <nav className="guide-nav">
        <div className="guide-nav-title">Guide</div>
        {SECTIONS.map((s) => (
          <a key={s.id} href={"#/guide"} className={active === s.id ? "active" : ""}
            onClick={(e) => {
              e.preventDefault();
              document.getElementById("guide-" + s.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
            }}>
            <span className="ico">{s.icon}</span>{s.title}
          </a>
        ))}
      </nav>
      <div className="guide-content">
        <div className="page-head" style={{ marginBottom: 8 }}>
          <div>
            <h1 className="page-title">User Guide</h1>
            <p className="page-sub">Everything Agent Studio can do — a plain-language tour.</p>
          </div>
        </div>
        {SECTIONS.map((s) => (
          <section key={s.id} id={"guide-" + s.id} className="guide-section">
            <h2><span style={{ marginRight: 8 }}>{s.icon}</span>{s.title}</h2>
            {s.body.map(Block)}
          </section>
        ))}
        <div className="guide-foot">
          Still stuck? Ask <b>🔥 Calcifer</b> (bottom-right) — it knows the app inside out.
        </div>
      </div>
    </div>
  );
}
