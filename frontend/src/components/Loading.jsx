import React from "react";

/* One loading + empty-state pair, so every page shows the same "server hasn't
 * answered yet" moment instead of a blank flash (each page used to `return null`). */

export function Loading({ what = "" }) {
  return (
    <div className="loading-note" role="status" aria-live="polite">
      <span className="spin" aria-hidden="true" />
      Loading{what ? ` ${what}` : ""}…
    </div>
  );
}

export function EmptyState({ icon = "∅", children }) {
  return (
    <div className="empty">
      <div className="big">{icon}</div>
      {children}
    </div>
  );
}
