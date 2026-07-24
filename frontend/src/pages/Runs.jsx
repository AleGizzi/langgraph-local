import React, { useEffect, useMemo, useState } from "react";
import { api, fmtDur, fmtTime } from "../lib/api.js";
import { clickable } from "../lib/clickable.js";
import { Loading, EmptyState } from "../components/Loading.jsx";

// Status gets BOTH an icon and a color, so it's distinguishable without color.
const STATUS = {
  done: ["✓", "done"], running: ["⏳", "running"],
  error: ["✗", "error"], cancelled: ["⊘", "error"],
};

export default function Runs() {
  const [runs, setRuns] = useState(null);
  const [summary, setSummary] = useState(null);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");

  useEffect(() => {
    api("/runs").then(setRuns).catch(() => setRuns([]));
    api("/runs/recent?limit=50").then((d) => setSummary(d.summary)).catch(() => {});
  }, []);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (runs || []).filter((r) =>
      (status === "all" || r.status === status) &&
      (!needle ||
        (r.team_name || "").toLowerCase().includes(needle) ||
        (r.task || "").toLowerCase().includes(needle)));
  }, [runs, q, status]);

  if (!runs) return <Loading what="runs" />;

  const pct = summary?.success_rate != null ? Math.round(summary.success_rate * 100) : null;
  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Runs</h1>
          <p className="page-sub">History of every team execution</p>
        </div>
      </div>

      {summary && runs.length > 0 && (
        <div className="telemetry">
          <div className="stat"><div className="k">Recent runs</div>
            <div className="v">{summary.count}</div></div>
          <div className="stat"><div className="k">Success rate</div>
            <div className={"v " + (pct == null ? "" : pct >= 70 ? "good" : "warn")}>
              {pct == null ? "—" : `${pct}%`}</div></div>
          <div className="stat"><div className="k">Median time</div>
            <div className="v">{summary.median_duration_s != null
              ? fmtDur(0, summary.median_duration_s) : "—"}</div></div>
          <div className="stat"><div className="k">Active now</div>
            <div className={"v " + (summary.active ? "warn" : "")}>{summary.active}</div></div>
        </div>
      )}

      {!runs.length ? (
        <EmptyState icon="🗂️">
          No runs yet. Pick a team in the Studio and give it a task.
        </EmptyState>
      ) : (
        <>
          <div className="runs-bar">
            <input type="text" placeholder="Search by team or task…" value={q}
              onChange={(e) => setQ(e.target.value)} aria-label="Search runs" />
            <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
              <option value="all">All statuses</option>
              <option value="done">Done</option>
              <option value="running">Running</option>
              <option value="error">Error</option>
              <option value="cancelled">Cancelled</option>
            </select>
            <span className="help">{shown.length} of {runs.length}</span>
          </div>
          {!shown.length ? (
            <EmptyState icon="🔍">No runs match that search.</EmptyState>
          ) : (
            <div className="card table-card">
              <table className="runs">
                <thead>
                  <tr><th>ID</th><th>Team</th><th>Task</th><th>Status</th><th>Duration</th><th>Started</th></tr>
                </thead>
                <tbody>
                  {shown.map((r) => {
                    const [ico, cls] = STATUS[r.status] || ["•", "error"];
                    return (
                      <tr key={r.id} {...clickable(() => (location.hash = `#/run/${r.id}`),
                        { label: `Run ${r.id} — ${r.team_name}` })}>
                        <td>#{r.id}</td>
                        <td>{r.team_name}</td>
                        <td className="task-cell" title={r.task}>{r.task}</td>
                        <td><span className={"status " + cls}>{ico} {r.status}</span></td>
                        <td>{fmtDur(r.created_at, r.finished_at)}</td>
                        <td>{fmtTime(r.created_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  );
}
