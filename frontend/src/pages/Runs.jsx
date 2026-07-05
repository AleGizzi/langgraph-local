import React, { useEffect, useState } from "react";
import { api, fmtDur, fmtTime } from "../lib/api.js";

export default function Runs() {
  const [runs, setRuns] = useState(null);
  useEffect(() => { api("/runs").then(setRuns).catch(() => setRuns([])); }, []);
  if (!runs) return null;
  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Runs</h1>
          <p className="page-sub">History of every team execution</p>
        </div>
      </div>
      {!runs.length ? (
        <div className="empty">
          <div className="big">🗂️</div>
          No runs yet. Pick a team in the Studio and give it a task.
        </div>
      ) : (
        <div className="card table-card">
          <table className="runs">
            <thead>
              <tr><th>ID</th><th>Team</th><th>Task</th><th>Status</th><th>Duration</th><th>Started</th></tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} onClick={() => (location.hash = `#/run/${r.id}`)}>
                  <td>#{r.id}</td>
                  <td>{r.team_name}</td>
                  <td className="task-cell" title={r.task}>{r.task}</td>
                  <td><span className={"status " + (r.status === "done" ? "done" : r.status === "running" ? "running" : "error")}>{r.status}</span></td>
                  <td>{fmtDur(r.created_at, r.finished_at)}</td>
                  <td>{fmtTime(r.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
