import React, { useEffect, useRef, useState } from "react";
import { api } from "../lib/api.js";

function ago(ts) {
  const d = Math.floor(Date.now() / 1000 - ts);
  if (d < 60) return "now";
  if (d < 3600) return `${Math.floor(d / 60)}m`;
  if (d < 86400) return `${Math.floor(d / 3600)}h`;
  return `${Math.floor(d / 86400)}d`;
}

/* Notification bell in the sidebar: polls the store, shows an unread badge, and
 * opens a small panel of recent notifications (from scheduled agents, the
 * notify tool, etc.). Desktop popups are separate (notify-send); this is the
 * reliable in-app record. */
export default function NotificationBell() {
  const [data, setData] = useState({ notifications: [], unread: 0 });
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  const load = () => api("/notifications").then(setData).catch(() => {});
  useEffect(() => {
    load();
    const t = setInterval(load, 12000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && data.unread) api("/notifications/read", { method: "POST", body: {} })
      .then(() => setData((d) => ({ ...d, unread: 0 }))).catch(() => {});
  };
  const clear = () => api("/notifications", { method: "DELETE" })
    .then(() => setData({ notifications: [], unread: 0 })).catch(() => {});

  return (
    <div className="notif-wrap" ref={ref}>
      <button className="notif-bell" onClick={toggle} title="Notifications" data-label="Notifications">
        🔔
        {data.unread > 0 && <span className="notif-badge">{data.unread > 9 ? "9+" : data.unread}</span>}
      </button>
      {open && (
        <div className="notif-panel">
          <div className="notif-head">
            <b>Notifications</b>
            {data.notifications.length > 0 &&
              <button className="btn sm ghost" onClick={clear}>Clear all</button>}
          </div>
          <div className="notif-list">
            {!data.notifications.length && <div className="help" style={{ padding: 14 }}>No notifications.</div>}
            {data.notifications.map((n) => (
              <div key={n.id} className={"notif-item" + (n.level === "critical" ? " crit" : "")}
                onClick={() => { if (n.link) { location.hash = n.link; setOpen(false); } }}
                style={{ cursor: n.link ? "pointer" : "default" }}>
                <div className="notif-item-title">{n.title}</div>
                {n.body && <div className="notif-item-body">{n.body.slice(0, 160)}</div>}
                <div className="notif-item-meta">{n.source || ""} · {ago(n.created_at)} ago</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
