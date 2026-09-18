/**
 * Visualization palette.
 *
 * Validated with the data-viz palette validator against this app's own dark
 * chart surface (#0f1626):
 *   - categorical trio  -> ALL CHECKS PASS (--pairs all)
 *   - ordinal blue ramp -> ALL CHECKS PASS (--ordinal)
 *   - status palette    -> clears 3:1 contrast; warning/serious sit close in
 *     CVD terms, so every status mark ships with a direct label (never colour
 *     alone), which is the documented mitigation.
 */
export const SURFACE = "#0f1626";
export const PAGE = "#080c17";

export const INK = {
  primary: "#ffffff",
  secondary: "#c3c2b7",
  muted: "#8b93a7",
  grid: "#1c2536",
  axis: "#334155",
};

/** Categorical - assign in fixed order, never cycled. Cap at 3 for all-pairs forms. */
export const CATEGORICAL = ["#3987e5", "#d95926", "#199e70"];

/** Ordinal single-hue ramp, light -> dark. */
export const ORDINAL_BLUE = ["#86b6ef", "#5598e7", "#3987e5", "#2a78d6", "#184f95"];

/** Status - reserved for state, never reused as a series colour. */
export const STATUS = {
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
  neutral: "#64748b",
};

/** "Can this past defect happen again?" */
export const CHANCE_COLOR = {
  Low: STATUS.good,
  Medium: STATUS.warning,
  High: STATUS.critical,
};

export const PRIORITY_COLOR = {
  P0: STATUS.critical,
  P1: STATUS.serious,
  P2: STATUS.warning,
  P3: STATUS.neutral,
};

export const PRIORITIES = ["P0", "P1", "P2", "P3"];

export function chanceColor(chance) {
  return CHANCE_COLOR[chance] || STATUS.neutral;
}

export function priorityColor(priority) {
  return PRIORITY_COLOR[priority] || STATUS.neutral;
}
