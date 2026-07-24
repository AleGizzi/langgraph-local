/* Make a non-button element (a card, a table row, a list item) behave like a
 * button for keyboard and screen-reader users. Spread the returned props onto
 * the element:  <tr {...clickable(() => open(run))}>…</tr>
 *
 * This was the app's single biggest a11y gap — dozens of `<div onClick>` /
 * `<tr onClick>` with no keyboard path. One helper fixes them uniformly. */
export function clickable(onActivate, { label } = {}) {
  return {
    role: "button",
    tabIndex: 0,
    onClick: onActivate,
    onKeyDown: (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onActivate(e);
      }
    },
    ...(label ? { "aria-label": label } : {}),
  };
}
