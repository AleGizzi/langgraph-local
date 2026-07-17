import React from "react";

/* Grid ⇆ list switch, shared by Studio / Personas / Skills & Tools.
 * `useViewMode(key)` persists the choice per page in localStorage. */
export function useViewMode(key, initial = "grid") {
  const [view, setView] = React.useState(() =>
    localStorage.getItem(`view:${key}`) || initial);
  React.useEffect(() => { localStorage.setItem(`view:${key}`, view); }, [key, view]);
  return [view, setView];
}

export default function ViewToggle({ view, onChange }) {
  return (
    <div className="view-toggle" role="group" aria-label="View mode">
      <button className={view === "grid" ? "active" : ""} title="Grid view"
        onClick={() => onChange("grid")} aria-pressed={view === "grid"}>▦</button>
      <button className={view === "list" ? "active" : ""} title="List view"
        onClick={() => onChange("list")} aria-pressed={view === "list"}>☰</button>
    </div>
  );
}
