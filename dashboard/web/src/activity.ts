// Weekly activity: stacked columns of added / advanced / closed.
import { activity, type ActivityWeek } from "../../shared/aggregate.ts";
import { weekStart } from "../../shared/dates.ts";
import type { OpportunityRecord } from "../../shared/types.ts";
import { h, s, shortDate, table, withTip } from "./dom.ts";

const SERIES: { key: keyof Omit<ActivityWeek, "week">; label: string; cls: string }[] = [
  { key: "added", label: "Added", cls: "c-series-1" },
  { key: "advanced", label: "Advanced a stage", cls: "c-series-2" },
  { key: "closed", label: "Closed", cls: "c-series-3" },
];

const weekLabel = (w: string) => `Week of ${shortDate(new Date(weekStart(w)).toISOString())}`;

/** Integer axis: a clean step and the ticks it produces. */
function niceScale(v: number): { max: number; ticks: number[] } {
  const step = v <= 4 ? 1 : v <= 10 ? 2 : v <= 25 ? 5 : v <= 50 ? 10 : 25;
  const max = Math.max(step, Math.ceil(v / step) * step);
  const every = max / step > 5 ? 2 : 1;
  const ticks: number[] = [];
  for (let t = 0; t <= max; t += step * every) ticks.push(t);
  return { max, ticks };
}

/** Column with a 4px rounded data-end and a square base. */
function column(x: number, y: number, w: number, hgt: number, rounded: boolean): string {
  const r = rounded ? Math.min(4, hgt, w / 2) : 0;
  return `M${x},${y + hgt}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + hgt}Z`;
}

export function legend() {
  return h("ul", { class: "legend" }, ...SERIES.map((sr) =>
    h("li", {}, h("span", { class: `swatch ${sr.cls}`, "aria-hidden": "true" }), sr.label)));
}

export function renderActivity(records: OpportunityRecord[], width: number) {
  const weeks = activity(records);
  const height = 240;
  const m = { top: 12, right: 8, bottom: 28, left: 32 };
  const svg = s("svg", { class: "activity", width, height, viewBox: `0 0 ${width} ${height}`, role: "img",
    "aria-label": `Weekly activity over ${weeks.length} weeks; see the table view for values` });
  if (!weeks.length) return svg;
  const { max, ticks } = niceScale(Math.max(...weeks.map((w) => w.added + w.advanced + w.closed)));
  const plotW = width - m.left - m.right;
  const plotH = height - m.top - m.bottom;
  const band = plotW / weeks.length;
  const colW = Math.max(2, Math.min(24, band * 0.7));
  const y = (v: number) => m.top + plotH - (v / max) * plotH;

  const grid = s("g", { class: "grid" });
  for (const t of ticks) {
    grid.append(s("line", { x1: m.left, x2: width - m.right, y1: y(t), y2: y(t), class: t === 0 ? "baseline" : undefined }),
      s("text", { x: m.left - 6, y: y(t), dy: "0.35em", "text-anchor": "end", class: "tick" }, String(t)));
  }
  svg.append(grid);

  const every = Math.max(1, Math.ceil(weeks.length / Math.max(1, Math.floor(plotW / 70))));
  weeks.forEach((w, i) => {
    const x = m.left + i * band + (band - colW) / 2;
    const g = s("g", { class: "col" });
    const total = w.added + w.advanced + w.closed;
    let acc = 0;
    const present = SERIES.filter((sr) => w[sr.key] > 0);
    present.forEach((sr, j) => {
      const v = w[sr.key];
      const top = y(acc + v);
      const bottom = y(acc);
      const gap = j > 0 ? 2 : 0; // surface gap between stacked segments
      const hgt = Math.max(0, bottom - top - gap);
      g.append(s("path", { d: column(x, top, colW, hgt, j === present.length - 1), class: `seg ${sr.cls}` }));
      acc += v;
    });
    // Hit target is the whole band, bigger than the mark.
    const hit = s("rect", { x: m.left + i * band, y: m.top, width: band, height: plotH, class: "hit", tabindex: 0,
      "aria-label": `${weekLabel(w.week)}: ${w.added} added, ${w.advanced} advanced, ${w.closed} closed` });
    withTip(hit, () => [weekLabel(w.week), ...SERIES.map((sr) => `${sr.label}: ${w[sr.key]}`), `Total: ${total}`]);
    g.append(hit);
    svg.append(g);
    if (i % every === 0) {
      svg.append(s("text", { x: m.left + i * band + band / 2, y: height - 8, "text-anchor": "middle", class: "tick" },
        shortDate(new Date(weekStart(w.week)).toISOString()).replace(/, \d{4}$/, "")));
    }
  });
  return svg;
}

export function activityTable(records: OpportunityRecord[]) {
  return table("Weekly activity", ["Week", "Added", "Advanced a stage", "Closed"],
    activity(records).map((w) => [weekLabel(w.week), w.added, w.advanced, w.closed]));
}
