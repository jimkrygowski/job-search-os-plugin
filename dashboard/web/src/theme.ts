// Fixed color roles. Colors live in style.css as classes on CSS custom
// properties (light and dark); this maps entities to those classes so an
// entity keeps its color in every view and under every filter.
import { UNKNOWN_SOURCE } from "../../shared/aggregate.ts";

/** The validated categorical palette has 8 slots; past that, and for any
 * source not in the list, a neutral gray (labels carry identity). */
const SLOTS = 8;

/** Sources take categorical slots in the order tracker.py lists them —
 * never by rank, so filtering never repaints a source. */
export function sourceClass(source: string, sources: string[]): string {
  const i = sources.indexOf(source);
  return source === UNKNOWN_SOURCE || i === -1 || i >= SLOTS ? "c-unknown" : `c-src-${i + 1}`;
}

const OUTCOME_CLASS: Record<string, string> = {
  Accepted: "c-accepted",
  "Declined Offer": "c-declined",
  Rejected: "c-rejected",
  Withdrew: "c-withdrew",
  Ghosted: "c-ghosted",
  Passed: "c-passed",
  "Role Filled": "c-filled",
  Closed: "c-ghosted",
};

export function endClass(label: string): string {
  if (label.startsWith("Stalled in ")) return "c-stalled";
  if (label.startsWith("Still in ")) return "c-active";
  return OUTCOME_CLASS[label] ?? "c-ghosted";
}
