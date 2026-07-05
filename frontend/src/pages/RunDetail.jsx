import React, { useEffect, useState } from "react";
import { api, fmtDur, fmtTime } from "../lib/api.js";
import Timeline, { itemsFromPersistedEvents, useRunStream } from "../components/Timeline.jsx";

export default function RunDetail({ runId }) {
  const [run, setRun] = useState(null);
  const [liveDone, setLiveDone] = useState(false);

  useEffect(() => {
    api(`/runs/${runId}`).then(setRun).catch(() => (location.hash = "#/runs"));
  }, [runId, liveDone]);

  const isLive = run && run.status === "running";
  const { items: liveItems } = useRunStream(isLive ? runId : null, () => setLiveDone(true));

  if (!run) return null;
  const items = isLive ? liveItems : itemsFromPersistedEvents(run);
  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Run #{run.id} — {run.team_name}</h1>
          <p className="page-sub">
            {fmtTime(run.created_at)} · {fmtDur(run.created_at, run.finished_at)} · {run.status}
            {run.error ? ` — ${run.error}` : ""}
          </p>
        </div>
        <button className="btn" onClick={() => (location.hash = "#/runs")}>← All runs</button>
      </div>
      <div className="card task-box">
        <div className="field">
          <label>Task</label>
          <div className="md">{run.task}</div>
        </div>
      </div>
      <Timeline items={items} runId={runId} autoScroll={isLive} />
    </>
  );
}
