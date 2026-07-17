import React from "react";

/* Reusable tab bar. `tabs` is [{ key, label, badge? }]. When `persistKey` is
 * given, the active tab is remembered in localStorage. Controlled via
 * `active`/`onChange` if provided, otherwise self-managed. */
export function useTab(persistKey, initial) {
  const [tab, setTab] = React.useState(() =>
    (persistKey && localStorage.getItem(`tab:${persistKey}`)) || initial);
  React.useEffect(() => {
    if (persistKey) localStorage.setItem(`tab:${persistKey}`, tab);
  }, [persistKey, tab]);
  return [tab, setTab];
}

export default function Tabs({ tabs, active, onChange }) {
  return (
    <div className="tabbar" role="tablist">
      {tabs.map((t) => (
        <button key={t.key} role="tab" aria-selected={active === t.key}
          className={active === t.key ? "active" : ""}
          onClick={() => onChange(t.key)}>
          {t.label}
          {t.badge != null && <span className="chip" style={{ marginLeft: 6 }}>{t.badge}</span>}
        </button>
      ))}
    </div>
  );
}
