import React, { useEffect, useRef, useState } from "react";
import { api, toast } from "../lib/api.js";
import { useApp } from "../App.jsx";
import AgentFields from "../components/AgentFields.jsx";
import { Md } from "../lib/markdown.jsx";

export default function Chat({ personaId = null }) {
  const { models } = useApp();
  const [personas, setPersonas] = useState([]);
  const [agent, setAgent] = useState({
    name: "Chat", role: "", provider: "ollama", model: "",
    system_prompt: "", params: {}, tools: [], skills: [],
  });
  const [messages, setMessages] = useState([]); // {role, content, tools:[]}
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [showConfig, setShowConfig] = useState(true);
  const [chats, setChats] = useState([]);
  const [chatId, setChatId] = useState(null);
  const abortRef = useRef(null);
  const endRef = useRef(null);
  const chatIdRef = useRef(null);
  chatIdRef.current = chatId;

  const loadChats = () => api("/chats").then(setChats).catch(() => {});
  useEffect(() => {
    api("/personas").then((ps) => {
      setPersonas(ps);
      // Deep link #/chat/<personaId> (from the Personas page): start a fresh
      // conversation as that persona.
      if (personaId) {
        const p = ps.find((x) => x.id === personaId);
        if (p) { applyPersona(p); setChatId(null); setMessages([]); }
        else toast("Persona not found", true);
      }
    }).catch(() => {});
    loadChats();
  }, [personaId]);

  const persist = async (agentCfg, msgs) => {
    const clean = msgs.filter((m) => !m.live)
      .map(({ role, content }) => ({ role, content }));
    if (!clean.length) return;
    try {
      if (chatIdRef.current) {
        await api(`/chats/${chatIdRef.current}`, { method: "PUT",
          body: { agent: agentCfg, messages: clean,
                  title: chats.find((c) => c.id === chatIdRef.current)?.title || "" } });
      } else {
        const saved = await api("/chats", { method: "POST",
          body: { agent: agentCfg, messages: clean } });
        setChatId(saved.id);
      }
      loadChats();
    } catch { /* persistence is best-effort */ }
  };

  const newChat = () => { setChatId(null); setMessages([]); };

  const openChat = async (c) => {
    try {
      const full = await api(`/chats/${c.id}`);
      setChatId(full.id);
      setMessages(full.messages.map((m) => ({ ...m, tools: [] })));
      if (full.agent?.model) setAgent(full.agent);
    } catch (e) { toast(e.message, true); }
  };

  const deleteChat = async (c, e) => {
    e.stopPropagation();
    if (!confirm(`Delete chat "${c.title}"?`)) return;
    await api(`/chats/${c.id}`, { method: "DELETE" });
    if (chatId === c.id) newChat();
    loadChats();
  };
  useEffect(() => {
    // Default model once discovered.
    if (agent.model) return;
    const pick = (l) => l.find((m) => /^(qwen|llama|mistral|gemma)/i.test(m) && !/r1|coder|think/i.test(m)) || l[0] || "";
    const model = pick(models.ollama || []) || pick(models.lmstudio || []);
    if (model) setAgent((a) => ({ ...a, model, provider: (models.ollama || []).length ? "ollama" : "lmstudio" }));
  }, [models]);
  useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [messages]);

  const applyPersona = (p) => {
    setAgent({
      name: p.name, role: p.role,
      provider: p.model ? p.provider : agent.provider,
      model: p.model || agent.model,
      system_prompt: p.system_prompt,
      params: { ...(p.params || {}) },
      tools: [...(p.tools || [])], skills: [...(p.skills || [])],
    });
    toast(`Chatting as: ${p.icon} ${p.name}`);
  };

  const saveAsPersona = async () => {
    try {
      await api("/personas", { method: "POST", body: {
        ...agent, icon: "💬", description: "Saved from the chat page",
      }});
      toast(`Saved "${agent.name}" as a persona`);
      api("/personas").then(setPersonas).catch(() => {});
    } catch (e) { toast(e.message, true); }
  };

  const stop = () => abortRef.current?.abort();

  const send = async () => {
    const text = input.trim();
    if (!text || streaming) return;
    if (!agent.model) { toast("Pick a model first", true); return; }
    const history = [...messages, { role: "user", content: text }];
    setMessages([...history, { role: "assistant", content: "", tools: [], live: true }]);
    setInput("");
    setStreaming(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: ctrl.signal,
        body: JSON.stringify({
          agent,
          messages: history.map(({ role, content }) => ({ role, content })),
        }),
      });
      if (!resp.ok) throw new Error((await resp.text()).replace(/<[^>]+>/g, " ").trim().slice(0, 200));
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
          if (ev.type === "token") {
            patch((m) => ({ ...m, content: m.content + ev.content }));
          } else if (ev.type === "tool_call" || ev.type === "tool_result") {
            patch((m) => ({ ...m, tools: [...m.tools, { type: ev.type, text: ev.content }] }));
          } else if (ev.type === "done") {
            patch((m) => ({ ...m, content: ev.content || m.content, live: false }));
          } else if (ev.type === "error") {
            patch((m) => ({ ...m, content: (m.content ? m.content + "\n\n" : "") + "⚠ " + ev.content, live: false }));
          }
        }
      }
    } catch (e) {
      if (e.name !== "AbortError") toast(e.message, true);
      setMessages((ms) => {
        const next = [...ms];
        const last = next[next.length - 1];
        if (last?.live) next[next.length - 1] = { ...last, live: false,
          content: last.content || (e.name === "AbortError" ? "(stopped)" : "") };
        return next;
      });
    }
    setStreaming(false);
    // Persist the finished turn (functional read of the final state).
    setMessages((ms) => { persist(agent, ms); return ms; });
  };

  return (
    <div className="chat-layout">
      <div className="chat-history">
        <button className="btn primary" style={{ width: "100%", justifyContent: "center" }}
          onClick={newChat}>＋ New chat</button>
        <div className="chat-history-list">
          {chats.map((c) => (
            <div key={c.id}
              className={"chat-history-item" + (c.id === chatId ? " active" : "")}
              onClick={() => openChat(c)} title={c.title}>
              <span className="chi-title">{c.title}</span>
              <span className="chi-meta">{c.agent?.model || ""} · {c.message_count} msg</span>
              <button className="icon-btn chi-del" title="Delete"
                onClick={(e) => deleteChat(c, e)}>🗑</button>
            </div>
          ))}
          {!chats.length && <div className="help" style={{ padding: 8 }}>No saved chats yet.</div>}
        </div>
      </div>
      <div className="chat-main">
        <div className="page-head" style={{ marginBottom: 10 }}>
          <div>
            <h1 className="page-title">Chat</h1>
            <p className="page-sub">
              Talk directly to a model with full persona settings — prompt,
              hyperparameters, tools and skills
            </p>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {messages.length > 0 && (
              <button className="btn" onClick={() => setMessages([])}>🧹 Clear</button>
            )}
            <button className="btn" onClick={() => setShowConfig(!showConfig)}>
              {showConfig ? "Hide settings" : "⚙️ Settings"}
            </button>
          </div>
        </div>

        <div className="chat-scroll">
          {messages.length === 0 && (
            <div className="empty">
              <div className="big">💬</div>
              Chatting with <strong>{agent.model || "…"}</strong>
              {agent.name !== "Chat" ? <> as <strong>{agent.name}</strong></> : null}.
              <br />Load a persona on the right, or just start typing.
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={"chat-msg " + m.role}>
              <div className="chat-bubble">
                {(m.tools || []).map((t, j) => (
                  <div key={j} className={"tool-line" + (t.type === "tool_result" ? " result" : "")}>
                    {t.type === "tool_call" ? "🛠 " : "↳ "}{t.text}
                  </div>
                ))}
                {m.role === "assistant"
                  ? (m.live && !m.content
                    ? <span className="stream-raw"><span className="caret" /></span>
                    : <>
                        <Md text={m.content} />
                        {m.live && <span className="caret" />}
                      </>)
                  : m.content}
              </div>
            </div>
          ))}
          <div ref={endRef} />
        </div>

        <div className="chat-inputbar">
          <textarea
            rows={2} value={input}
            placeholder={`Message ${agent.model || "the model"}…  (Enter to send, Shift+Enter for newline)`}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
            }}
          />
          {streaming
            ? <button className="btn danger" onClick={stop}>■ Stop</button>
            : <button className="btn primary" onClick={send} disabled={!input.trim()}>Send ➤</button>}
        </div>
      </div>

      {showConfig && (
        <div className="chat-config">
          <div className="flow-panel-head">
            <span>⚙️ Model & persona settings</span>
            <button className="btn sm" onClick={saveAsPersona} title="Save these settings as a persona">💾</button>
          </div>
          <div className="flow-panel-body">
            <div className="field">
              <label>Quick-load a persona</label>
              <div className="persona-strip">
                {personas.map((p) => (
                  <span key={p.id} className="persona-chip" title={p.description}
                    onClick={() => applyPersona(p)}>{p.icon} {p.name}</span>
                ))}
              </div>
            </div>
            <AgentFields value={agent} onChange={setAgent} namePlaceholder="Persona name" />
            <div className="help" style={{ marginTop: 10 }}>
              Changes apply from your next message. Conversation history is kept
              in the browser until you clear it.
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
