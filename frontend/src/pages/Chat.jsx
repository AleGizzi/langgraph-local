import React, { useEffect, useRef, useState } from "react";
import { api, toast } from "../lib/api.js";
import { useApp } from "../App.jsx";
import AgentFields from "../components/AgentFields.jsx";
import { Md } from "../lib/markdown.jsx";

const fmtK = (n) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`);

/* Context-window gauge: how full the model's working memory is. Numbers come
 * from the server's `usage` SSE event (real token counts when the provider
 * reports them, a chars/4 estimate otherwise — we show whichever is larger,
 * because Ollama under-reports cached prompt tokens). */
function ContextGauge({ usage, msgCount, onNewChat, hallucAvg }) {
  if (!usage) return null;
  const reported = (usage.input_tokens || 0) + (usage.output_tokens || 0);
  const used = Math.max(reported, usage.est_tokens || 0);
  const ctx = usage.num_ctx || 8192;
  const pct = Math.min(100, Math.round((used / ctx) * 100));
  const level = pct >= 85 ? "hot" : pct >= 60 ? "warm" : "ok";
  const canGrow = usage.model_max && usage.model_max > ctx;
  return (
    <div className={"ctx-gauge " + level}
      title={`Context window: ~${fmtK(used)} of ${fmtK(ctx)} tokens in use (${pct}%).\n`
        + `Everything above 100% gets forgotten, oldest first.`
        + (canGrow ? `\nThis model supports up to ${fmtK(usage.model_max)} — raise `
          + `"Context window" (num_ctx) in settings to give it more memory (uses more RAM).` : "")}>
      <div className="ctx-bar"><div className="ctx-fill" style={{ width: `${pct}%` }} /></div>
      <span className="ctx-text">
        🧠 {fmtK(used)} / {fmtK(ctx)} tokens ({pct}%) · {msgCount} messages
        {usage.tok_s ? ` · ${usage.tok_s} tok/s` : ""}
        {hallucAvg != null ? ` · 🔮 ~${hallucAvg}% est. hallucination risk` : ""}
      </span>
      {level === "hot" && (
        <span className="ctx-warn">
          context nearly full — the model starts forgetting the oldest messages.
          <button className="btn sm" style={{ marginLeft: 6, padding: "1px 8px" }}
            onClick={onNewChat}>＋ Start a new chat</button>
        </span>
      )}
    </div>
  );
}

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
  const [usage, setUsage] = useState(null);
  const [checkHalluc, setCheckHalluc] = useState(
    () => localStorage.getItem("chatHallucCheck") === "1");
  useEffect(() => {
    localStorage.setItem("chatHallucCheck", checkHalluc ? "1" : "0");
  }, [checkHalluc]);
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
      .map(({ role, content, name, model, seconds }) =>
        (name ? { role, content, name, model, seconds } : { role, content }));
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

  const newChat = () => { setChatId(null); setMessages([]); setUsage(null); };

  const openChat = async (c) => {
    try {
      const full = await api(`/chats/${c.id}`);
      setChatId(full.id);
      setMessages(full.messages.map((m) => ({ ...m, tools: [] })));
      if (full.agent?.model) setAgent(full.agent);
      // Until the next reply brings real numbers, estimate the reopened
      // conversation's context fill so the gauge isn't blank.
      const est = Math.round(full.messages.reduce(
        (n, m) => n + (m.content || "").length, 0) / 4);
      setUsage({ est_tokens: est, input_tokens: 0, output_tokens: 0, tok_s: null,
        num_ctx: +(full.agent?.params?.num_ctx) || 8192, model_max: null });
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
          } else if (ev.type === "agent_msg") {
            // A spawned agent spoke — its own bubble, placed before the live
            // assistant message so the dialog reads in order. model + seconds
            // are the proof it was a real, separate inference call.
            setMessages((ms) => {
              const next = [...ms];
              const live = next.pop();
              next.push({ role: "agent", name: ev.agent, content: ev.content,
                          model: ev.model, seconds: ev.seconds });
              next.push(live);
              return next;
            });
          } else if (ev.type === "usage") {
            setUsage(ev);
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
    // Optional hallucination-risk estimate for the reply that just finished.
    if (checkHalluc) {
      setMessages((ms) => {
        const i = ms.length - 1; // messages only append, so this index is stable
        const last = ms[i];
        if (last?.role === "assistant" && last.content && !last.risk) {
          const evidence = (last.tools || [])
            .map((t) => `${t.type}: ${t.text}`).join("\n");
          api("/chat/verify", { method: "POST", body: {
            question: text, reply: last.content, evidence,
          } }).then((r) => {
            if (!r.ok) return;
            setMessages((cur) => {
              if (cur[i]?.role !== "assistant") return cur;
              const next = [...cur];
              next[i] = { ...next[i], risk: r };
              return next;
            });
          }).catch(() => {});
        }
        return ms;
      });
    }
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
              <button className="btn" onClick={() => { setMessages([]); setUsage(null); }}>🧹 Clear</button>
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
              {m.role === "agent" && (
                <div className="agent-msg-name">
                  {m.name || "spawned agent"}
                  {m.model && (
                    <span className="agent-msg-proof"
                      title="This reply came from a separate local model call — proof it is a real spawned agent, not the main model role-playing.">
                      · {m.model}{m.seconds != null ? ` · ${m.seconds}s` : ""}
                    </span>
                  )}
                </div>
              )}
              <div className="chat-bubble">
                {(m.tools || []).map((t, j) => (
                  <div key={j} className={"tool-line" + (t.type === "tool_result" ? " result" : "")}>
                    {t.type === "tool_call" ? "🛠 " : "↳ "}{t.text}
                  </div>
                ))}
                {m.role === "assistant" || m.role === "agent"
                  ? (m.live && !m.content
                    ? <span className="stream-raw"><span className="caret" /></span>
                    : <>
                        <Md text={m.content} />
                        {m.live && <span className="caret" />}
                      </>)
                  : m.content}
                {m.risk?.ok && (
                  <div className={"halluc-pill " + (m.risk.risk < 34 ? "ok"
                      : m.risk.risk < 67 ? "warm" : "hot")}
                    title={"ESTIMATE by " + m.risk.judge + " — not a measurement. "
                      + "It flags confident, specific, unverifiable claims.\n\n"
                      + (m.risk.reasons || []).map((r) => "• " + r).join("\n")}>
                    🔮 hallucination risk ~{m.risk.risk}% <em>(est.)</em>
                  </div>
                )}
              </div>
            </div>
          ))}
          <div ref={endRef} />
        </div>

        <ContextGauge usage={usage} msgCount={messages.length} onNewChat={newChat}
          hallucAvg={(() => {
            const rs = messages.filter((m) => m.risk?.ok).map((m) => m.risk.risk);
            return rs.length ? Math.round(rs.reduce((a, b) => a + b, 0) / rs.length) : null;
          })()} />

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
            <div className="field" style={{ marginTop: 10 }}>
              <label style={{ display: "inline-flex", gap: 8, alignItems: "center", cursor: "pointer" }}>
                <input type="checkbox" checked={checkHalluc}
                  onChange={(e) => setCheckHalluc(e.target.checked)} />
                🔮 Hallucination check
              </label>
              <div className="help">
                After each reply, a small local model estimates how much of it is
                confident-but-unverifiable (~10-20s extra per message). It is an
                <strong> estimate</strong>, not a measurement — use it as a
                skepticism guide, especially for numbers, names and citations.
              </div>
            </div>
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
