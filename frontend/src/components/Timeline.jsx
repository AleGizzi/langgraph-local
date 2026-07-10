import React, { useEffect, useRef, useState } from "react";
import { api, toast } from "../lib/api.js";
import { Md } from "../lib/markdown.jsx";

/* Timeline items:
   {kind:'banner', text}
   {kind:'step', key, agent, meta, text, content, status, tools:[{call,result}]}
   {kind:'decision', agent, text}
   {kind:'error', text}
   {kind:'final', content}
*/

export function useRunStream(runId, onDone) {
  const [items, setItems] = useState([]);
  const [live, setLive] = useState(false);

  useEffect(() => {
    if (!runId) return undefined;
    setItems([]);
    setLive(true);
    const es = new EventSource(`/api/runs/${runId}/events`);
    const openSteps = {}; // agent -> item key

    const handle = (e) => {
      setItems((prev) => {
        const next = [...prev];
        const findStep = (agent) => {
          const key = openSteps[agent];
          return next.findIndex((it) => it.kind === "step" && it.key === key);
        };
        if (e.type === "run_start") {
          const conc = e.meta?.concurrency;
          next.push({
            kind: "banner",
            text: `🚀 Run #${runId} — ${e.meta?.team || ""} (${e.meta?.topology || ""}` +
              (conc > 1 ? `, parallel ×${conc})` : ")"),
          });
        } else if (e.type === "agent_start") {
          const key = `${e.agent}-${e.seq}`;
          openSteps[e.agent] = key;
          next.push({ kind: "step", key, agent: e.agent, meta: e.meta, text: "", content: null, status: "running", tools: [] });
        } else if (e.type === "token") {
          const i = findStep(e.agent);
          if (i >= 0) next[i] = { ...next[i], text: next[i].text + e.content };
        } else if (e.type === "tool_call" || e.type === "tool_result") {
          const i = findStep(e.agent);
          if (i >= 0) next[i] = { ...next[i], tools: [...next[i].tools, { type: e.type, text: e.content }] };
        } else if (e.type === "agent_end") {
          const i = findStep(e.agent);
          if (i >= 0) {
            const verdict = e.meta?.verdict;
            next[i] = { ...next[i], content: e.content, status: verdict === "revise" ? "revise" : "done" };
            delete openSteps[e.agent];
          }
        } else if (e.type === "decision") {
          next.push({ kind: "decision", agent: e.agent, text: e.content });
        } else if (e.type === "artifact") {
          next.push({ kind: "artifact", agent: e.agent, text: e.content });
        } else if (e.type === "error") {
          next.push({ kind: "error", text: e.content });
        } else if (e.type === "run_end") {
          for (let i = 0; i < next.length; i++) {
            if (next[i].kind === "step" && next[i].status === "running") {
              next[i] = { ...next[i], status: "done", content: next[i].content ?? next[i].text };
            }
          }
          const st = e.meta?.status;
          if (st === "done" && e.content) next.push({ kind: "final", content: e.content });
          else if (st === "cancelled") next.push({ kind: "decision", text: "■ Run stopped by user" });
        }
        return next;
      });
      if (e.type === "run_end") {
        es.close();
        setLive(false);
        onDone && onDone(e.meta?.status);
      }
    };

    es.onmessage = (msg) => {
      try { handle(JSON.parse(msg.data)); } catch { /* ignore malformed */ }
    };
    return () => es.close();
  }, [runId]);

  return { items, live };
}

export function itemsFromPersistedEvents(run) {
  const items = [];
  const metaByAgent = {};
  for (const e of run.events) {
    if (e.type === "agent_start") metaByAgent[`${e.agent}-${e.seq}`] = e.meta;
  }
  let lastStep = null;
  for (const e of run.events) {
    if (e.type === "agent_end") {
      const startKey = Object.keys(metaByAgent).reverse()
        .find((k) => k.startsWith(e.agent + "-") && +k.split("-").pop() < e.seq);
      lastStep = {
        kind: "step", key: `${e.agent}-${e.seq}`, agent: e.agent,
        meta: startKey ? metaByAgent[startKey] : null, text: "",
        content: e.content, tools: [],
        status: e.meta?.verdict === "revise" ? "revise" : "done",
      };
      items.push(lastStep);
    } else if (e.type === "tool_call" || e.type === "tool_result") {
      if (lastStep) lastStep.tools.push({ type: e.type, text: e.content });
    } else if (e.type === "decision") {
      items.push({ kind: "decision", agent: e.agent, text: e.content });
    } else if (e.type === "artifact") {
      items.push({ kind: "artifact", agent: e.agent, text: e.content });
    } else if (e.type === "error") {
      items.push({ kind: "error", text: e.content });
    }
  }
  if (run.status === "done" && run.final) items.push({ kind: "final", content: run.final });
  return items;
}

function StepCard({ item }) {
  const [collapsed, setCollapsed] = useState(false);
  const m = item.meta || {};
  return (
    <div className="card step-card">
      <div className="step-head" onClick={() => setCollapsed(!collapsed)}>
        {item.status === "running" && <div className="spinner" />}
        <span className="name">{item.agent}</span>
        <span className="model">
          {[m.provider, m.model, m.role].filter(Boolean).join(" · ")}
        </span>
        <span className="spacer" />
        <span className={"status " + item.status}>{item.status}</span>
      </div>
      {!collapsed && (
        <div className="step-body">
          {item.tools.map((t, i) => (
            <div key={i} className={"tool-line" + (t.type === "tool_result" ? " result" : "")}>
              {t.type === "tool_call" ? "🛠 " : "↳ "}{t.text}
            </div>
          ))}
          {item.content !== null
            ? <Md text={item.content} />
            : <div className="stream-raw">{item.text}<span className="caret" /></div>}
        </div>
      )}
    </div>
  );
}

function FinalCard({ content, runId }) {
  return (
    <div className="card step-card final-card">
      <div className="step-head">
        <span className="name">✅ Final deliverable</span>
        <span className="spacer" />
        <button className="btn sm" onClick={() =>
          navigator.clipboard.writeText(content).then(() => toast("Copied to clipboard"))}>
          Copy
        </button>
        <a className="btn sm" href={`/api/runs/${runId}/artifacts/final_output.md`}
          download={`run-${runId}.md`}>Download .md</a>
      </div>
      <div className="step-body"><Md text={content} /></div>
    </div>
  );
}

function Artifacts({ runId }) {
  const [files, setFiles] = useState([]);
  useEffect(() => {
    api(`/runs/${runId}/artifacts`)
      .then((fs) => setFiles(fs.filter((f) => f.path !== "final_output.md")))
      .catch(() => {});
  }, [runId]);
  if (!files.length) return null;
  return (
    <div className="card">
      <div className="step-head">
        <span className="name">📎 Workspace artifacts</span>
        <span className="spacer" />
        <a className="btn sm" href={`/api/runs/${runId}/artifacts.zip`}
          download={`run-${runId}.zip`}>⬇ Download all (.zip)</a>
      </div>
      <div className="artifact-list">
        {files.map((f) => (
          <a key={f.path} href={`/api/runs/${runId}/artifacts/${f.path}`} target="_blank" rel="noopener noreferrer">
            📄 {f.path} <span style={{ color: "var(--text-3)" }}>{f.size} B</span>
          </a>
        ))}
      </div>
    </div>
  );
}

export default function Timeline({ items, runId, autoScroll = false }) {
  const endRef = useRef(null);
  useEffect(() => {
    if (!autoScroll) return;
    const main = document.querySelector(".main");
    if (main && main.scrollHeight - main.scrollTop - main.clientHeight < 320) {
      endRef.current?.scrollIntoView({ block: "end" });
    }
  }, [items, autoScroll]);

  const finished = items.some((it) => it.kind === "final");
  return (
    <div className="timeline">
      {items.map((it, i) => {
        if (it.kind === "banner" || it.kind === "decision") {
          return (
            <div key={i} className="decision-line">
              {it.kind === "banner" ? it.text : `🧭 ${it.agent ? it.agent + ": " : ""}${it.text}`}
            </div>
          );
        }
        if (it.kind === "artifact") {
          return (
            <div key={i} className="decision-line" style={{ borderStyle: "solid" }}>
              📦 {it.agent ? it.agent + " wrote " : ""}
              <code style={{ fontFamily: "var(--mono)" }}>{it.text}</code>
            </div>
          );
        }
        if (it.kind === "step") return <StepCard key={it.key} item={it} />;
        if (it.kind === "error") {
          return (
            <div key={i} className="card step-card error-card">
              <div className="step-head">
                <span className="name">Error</span><span className="spacer" />
                <span className="status error">error</span>
              </div>
              <div className="step-body"><div className="stream-raw">{it.text}</div></div>
            </div>
          );
        }
        if (it.kind === "final") return <FinalCard key={i} content={it.content} runId={runId} />;
        return null;
      })}
      {finished && <Artifacts runId={runId} />}
      <div ref={endRef} />
    </div>
  );
}
