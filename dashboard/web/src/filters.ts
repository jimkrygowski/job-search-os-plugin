// Filter state lives in the URL hash so a view can be bookmarked.
import type { Filters } from "../../shared/types.ts";
import { h } from "./dom.ts";

export const DEFAULT_FILTERS: Filters = { range: "all", sources: [], status: "all" };

export function parseHash(hash: string): Filters {
  const p = new URLSearchParams(hash.replace(/^#/, ""));
  const range = p.get("range");
  const status = p.get("status");
  return {
    range: range === "30" || range === "90" ? range : "all",
    status: status === "active" || status === "closed" ? status : "all",
    sources: (p.get("sources") ?? "").split(",").map((x) => x.trim()).filter(Boolean),
  };
}

export function toHash(f: Filters): string {
  const p = new URLSearchParams();
  if (f.range !== "all") p.set("range", f.range);
  if (f.status !== "all") p.set("status", f.status);
  if (f.sources.length) p.set("sources", f.sources.join(","));
  const s = p.toString();
  return s ? `#${s}` : "#";
}

function segmented<T extends string>(label: string, options: [T, string][], value: T, set: (v: T) => void) {
  return h("div", { class: "segmented", role: "group", "aria-label": label },
    h("span", { class: "filter-label" }, label),
    ...options.map(([v, text]) => {
      const b = h("button", { type: "button", "aria-pressed": String(v === value) }, text);
      b.addEventListener("click", () => set(v));
      return b;
    }));
}

export function filterBar(f: Filters, sources: string[], onChange: (f: Filters) => void) {
  const chips = h("div", { class: "chips", role: "group", "aria-label": "Source" },
    h("span", { class: "filter-label" }, "Source"),
    ...sources.map((src) => {
      const on = f.sources.includes(src);
      const b = h("button", { type: "button", class: "chip", "aria-pressed": String(on) }, src);
      b.addEventListener("click", () =>
        onChange({ ...f, sources: on ? f.sources.filter((x) => x !== src) : [...f.sources, src] }));
      return b;
    }));
  const clear = h("button", { type: "button", class: "link-button", disabled: f.sources.length === 0 }, "All sources");
  clear.addEventListener("click", () => onChange({ ...f, sources: [] }));
  chips.append(clear);
  return h("div", { class: "filter-row" },
    segmented("Added", [["30", "Last 30 days"], ["90", "Last 90 days"], ["all", "All time"]], f.range,
      (range) => onChange({ ...f, range })),
    segmented("Status", [["active", "Active"], ["closed", "Closed"], ["all", "All"]], f.status,
      (status) => onChange({ ...f, status })),
    chips);
}
