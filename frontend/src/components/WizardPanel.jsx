import React, { useEffect, useState } from "react";
import { api, toast } from "../lib/api.js";
import { useApp } from "../App.jsx";
import { ModelSelect } from "./AgentFields.jsx";

export function pickModel(models, preferCoder) {
  const lists = [["ollama", models.ollama || []], ["lmstudio", models.lmstudio || []]];
  for (const [prov, list] of lists) {
    if (preferCoder) {
      const coder = list.find((m) => /coder/i.test(m) && !/r1|think/i.test(m));
      if (coder) return { provider: prov, model: coder };
    }
    const general = list.find((m) => /^(qwen|llama|mistral|gemma)/i.test(m) && !/r1|coder|think/i.test(m));
    if (general) return { provider: prov, model: general };
    if (list.length) return { provider: prov, model: list[0] };
  }
  return { provider: "ollama", model: "" };
}

const COPY = {
  skill: {
    label: "What should agents with this skill do?",
    placeholder: "e.g. always answer in Spanish, keeping technical terms in English",
  },
  tool: {
    label: "What should this tool be able to do?",
    placeholder: "e.g. convert temperatures between celsius and fahrenheit",
  },
  team: {
    label: "Describe the team — who is in it and how should they work together?",
    placeholder: "e.g. a global PMO orchestrator, a team of devops and a team of qa",
  },
};

export default function WizardPanel({ kind, buildPayload, onDraft }) {
  const { models } = useApp();
  const [sel, setSel] = useState(() => pickModel(models, kind === "tool"));
  const [request, setRequest] = useState("");
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);
  const [generated, setGenerated] = useState(false);

  useEffect(() => {
    if (!sel.model) setSel(pickModel(models, kind === "tool"));
  }, [models]);

  const generate = async () => {
    if (!request.trim()) { toast("Describe what you need first", true); return; }
    if (!sel.model) { toast("No local model available", true); return; }
    setBusy(true);
    try {
      const body = {
        kind, request: request.trim(),
        provider: sel.provider, model: sel.model,
        ...(generated ? { feedback: feedback.trim() || "improve it", ...buildPayload() } : {}),
      };
      const r = await api("/wizard", { method: "POST", body });
      onDraft(r.draft);
      setGenerated(true);
      setFeedback("");
      toast(generated ? "Draft refined — review below" : "Draft ready — review and edit below");
    } catch (e) { toast(e.message, true); }
    setBusy(false);
  };

  const copy = COPY[kind] || COPY.skill;
  return (
    <div className="wizard-box">
      <div className="wizard-head">🪄 AI wizard
        <span className="help">a local model drafts it; you review, refine and save</span>
      </div>
      <div className="field">
        <label>{copy.label}</label>
        <textarea rows={2} value={request} disabled={generated}
          placeholder={copy.placeholder}
          onChange={(e) => setRequest(e.target.value)} />
      </div>
      {generated && (
        <div className="field">
          <label>Refine — what should change?</label>
          <textarea rows={2} value={feedback}
            placeholder="e.g. make it stricter / add a security specialist"
            onChange={(e) => setFeedback(e.target.value)} />
        </div>
      )}
      <div className="wizard-actions">
        <div style={{ minWidth: 220 }}>
          <ModelSelect provider={sel.provider} model={sel.model}
            onChange={(provider, model) => setSel({ provider, model })} />
        </div>
        <button className="btn primary" disabled={busy} onClick={generate}>
          {busy ? "Generating…" : generated ? "🪄 Refine draft" : "🪄 Generate draft"}
        </button>
        {busy && <span className="help">running locally on {sel.model} — this can take a minute or two</span>}
      </div>
    </div>
  );
}
