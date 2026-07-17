import React, { useEffect, useRef, useState } from "react";
import { api, toast } from "../lib/api.js";
import { Md } from "../lib/markdown.jsx";
import PixelSprite from "./PixelSprite.jsx";

/* Floating help assistant, available on every page. It reuses the normal
 * /api/chat SSE endpoint with a server-provided agent config (help.py) whose
 * system prompt embeds a guide to this app. Conversation lives in
 * sessionStorage so it survives navigation but not a new session. */

const PAGE_HINTS = {
  agents: "the Agents page (dashboard, teams, personas)",
  teams: "the Agents page — Teams tab",
  team: "a team's page",
  flow: "the visual pipeline canvas",
  pixel: "the pixel studio",
  chat: "the Chat page",
  runs: "the Runs history",
  run: "a run's detail page",
  knowledge: "the Knowledge vault",
  personas: "the Agents page — Personas tab",
  toolbox: "the Skills & Tools page",
  models: "the Models page",
  setup: "the Setup page",
  settings: "the Settings page",
};

const SUGGESTIONS = [
  "What can this app do?",
  "How do I create a team?",
  "How do agents deliver files?",
  "How do I free up memory?",
];

export default function HelpAssistant() {
  const [open, setOpen] = useState(false);
  const [cfg, setCfg] = useState(null);
  const [messages, setMessages] = useState(() => {
    try { return JSON.parse(sessionStorage.getItem("helpChat") || "[]"); }
    catch { return []; }
  });
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const abortRef = useRef(null);
  const endRef = useRef(null);

  useEffect(() => { api("/help/agent").then(setCfg).catch(() => {}); }, []);
  useEffect(() => {
    sessionStorage.setItem("helpChat", JSON.stringify(messages.filter((m) => !m.live)));
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  const ask = async (text) => {
    const q = (text ?? input).trim();
    if (!q || busy) return;
    if (!cfg?.available) { toast("No local model available for help", true); return; }
    const page = (location.hash || "#/teams").split("/")[1] || "teams";
    const history = [...messages, { role: "user", content: q }];
    setMessages([...history, { role: "assistant", content: "", live: true }]);
    setInput("");
    setBusy(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: ctrl.signal,
        body: JSON.stringify({
          agent: cfg.agent,
          // Page context rides on the latest question only, so it stays out of
          // the visible transcript and doesn't accumulate.
          messages: history.map(({ role, content }, i) => (
            i === history.length - 1
              ? { role, content: `[The user is currently on ${PAGE_HINTS[page] || "a page"}.]\n\n${content}` }
              : { role, content }
          )),
        }),
      });
      if (!resp.ok) throw new Error((await resp.text()).replace(/<[^>]+>/g, " ").trim().slice(0, 160));
      const reader = resp.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      const patch = (fn) => setMessages((ms) => {
        const next = [...ms];
        next[next.length - 1] = fn(next[next.length - 1]);
        return next;
      });
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop();
        for (const part of parts) {
          const line = part.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;
          let ev;
          try { ev = JSON.parse(line.slice(6)); } catch { continue; }
          if (ev.type === "token") patch((m) => ({ ...m, content: m.content + ev.content }));
          else if (ev.type === "done") patch((m) => ({ ...m, content: ev.content || m.content, live: false }));
          else if (ev.type === "error") patch((m) => ({ ...m, content: "⚠ " + ev.content, live: false }));
        }
      }
    } catch (e) {
      if (e.name !== "AbortError") toast(e.message, true);
      setMessages((ms) => {
        const next = [...ms];
        const last = next[next.length - 1];
        if (last?.live) next[next.length - 1] = { ...last, live: false, content: last.content || "(stopped)" };
        return next;
      });
    }
    setBusy(false);
  };

  return (
    <>
      <button className={"help-fab" + (open ? " open" : "")} title="Help assistant"
        onClick={() => setOpen(!open)}>
        <PixelSprite name={open ? "close" : "squid"} size={open ? 20 : 24} color="#fff" />
      </button>

      {open && (
        <div className="help-panel">
          <div className="help-head">
            <span style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
              <PixelSprite name="squid" size={16} color="var(--accent)" />
              <b>Help assistant</b>
            </span>
            <span className="help-model">{cfg?.agent?.model || "…"}</span>
            <span className="spacer" style={{ flex: 1 }} />
            {messages.length > 0 && (
              <button className="btn sm ghost" onClick={() => setMessages([])}>Clear</button>
            )}
          </div>

          <div className="help-body">
            {!messages.length && (
              <div className="help-intro">
                Ask me anything about this app — where things are and how to use them.
                <div className="help-suggestions">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} className="help-sugg" onClick={() => ask(s)}>{s}</button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={"help-msg " + m.role}>
                {m.role === "assistant"
                  ? (m.live && !m.content
                    ? <span className="caret" />
                    : <Md text={m.content} />)
                  : m.content}
              </div>
            ))}
            <div ref={endRef} />
          </div>

          <div className="help-input">
            <input value={input} placeholder="Ask about this app…"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") ask(); }} />
            {busy
              ? <button className="btn sm danger" onClick={() => abortRef.current?.abort()}>■</button>
              : <button className="btn sm primary" onClick={() => ask()} disabled={!input.trim()}>➤</button>}
          </div>
        </div>
      )}
    </>
  );
}
