// Dashboard entry: fetch /api/data once per load, then filter and render
// everything in the browser.
import { applyFilters, sourceLabel, summary, UNKNOWN_SOURCE } from "../../shared/aggregate.ts";
import type { Filters, OpportunityRecord, Payload } from "../../shared/types.ts";
import { activityTable, legend as activityLegend, renderActivity } from "./activity.ts";
import { conversionTable, renderConversion, SMALL_SAMPLE } from "./conversion.ts";
import { h, hideTip, pct } from "./dom.ts";
import { openGroup } from "./drilldown.ts";
import { filterBar, parseHash, toHash } from "./filters.ts";
import { renderSankey, sankeyTable } from "./sankey.ts";

const app = document.getElementById("app")!;
const tableViews = new Set<string>();
const dismissed = new Set<string>();
let payload: Payload | null = null;

function banner(kind: "info" | "warn" | "error", title: string, lines: string[] = [], dismissKey?: string) {
  const el = h("div", { class: `banner ${kind}`, role: kind === "error" ? "alert" : "status" },
    h("strong", {}, title), ...lines.map((l) => h("div", {}, l)));
  if (dismissKey) {
    const b = h("button", { type: "button", class: "icon-button", "aria-label": "Dismiss" }, "×");
    b.addEventListener("click", () => { dismissed.add(dismissKey); el.remove(); });
    el.append(b);
  }
  return el;
}

function tile(label: string, value: string, note?: string) {
  return h("div", { class: "tile" }, h("div", { class: "tile-label" }, label), h("div", { class: "tile-value" }, value),
    note ? h("div", { class: "tile-note" }, note) : null);
}

function section(id: string, title: string, subtitle: string, chart: () => Element, tableView: () => Element, extra?: Element) {
  const showTable = tableViews.has(id);
  const toggle = h("button", { type: "button", class: "link-button", "aria-pressed": String(showTable) },
    showTable ? "Show as chart" : "Show as table");
  toggle.addEventListener("click", () => {
    if (showTable) tableViews.delete(id); else tableViews.add(id);
    render();
  });
  return h("section", { class: "card", id, "aria-labelledby": `${id}-title` },
    h("header", { class: "card-head" },
      h("div", {}, h("h2", { id: `${id}-title` }, title), h("p", { class: "subtitle" }, subtitle)), toggle),
    showTable ? null : extra ?? null,
    h("div", { class: "card-body" }, showTable ? tableView() : chart()));
}

function selector(records: OpportunityRecord[]) {
  const byKey = new Map(records.map((r) => [r.key, r]));
  return (title: string, keys: string[]) =>
    openGroup(title, keys.map((k) => byKey.get(k)).filter((r): r is OpportunityRecord => !!r));
}

function setFilters(f: Filters) {
  const hash = toHash(f);
  if (location.hash !== hash) history.replaceState(null, "", hash === "#" ? location.pathname : hash);
  render();
}

function render() {
  hideTip();
  if (!payload) return;
  const p = payload;
  const filters = parseHash(location.hash);
  const allSources = [...p.sources, ...(p.records.some((r) => !r.source) ? [UNKNOWN_SOURCE] : [])];
  const records = applyFilters(p.records, filters, new Date());
  const select = selector(records);
  const width = Math.max(320, (app.querySelector(".card-body") as HTMLElement | null)?.clientWidth ?? app.clientWidth - 48);

  const notices: Element[] = [];
  if (p.noHistory && !dismissed.has("nohistory")) {
    notices.push(banner("info", "History isn't recorded yet.",
      ["Run backfill-history to see full paths. Until then each opportunity shows only its current stage."], "nohistory"));
  }
  if (p.warnings.length && !dismissed.has("warnings")) {
    notices.push(banner("warn", `${p.warnings.length} data ${p.warnings.length === 1 ? "warning" : "warnings"}`, p.warnings, "warnings"));
  }

  const sum = summary(records, p.stages);
  const body: (Element | null)[] = [
    h("div", { class: "filters", role: "region", "aria-label": "Filters" },
      filterBar(filters, allSources, setFilters)),
    ...notices,
  ];

  if (!p.records.length) {
    body.push(h("section", { class: "card empty" }, h("h2", {}, "No opportunities yet"),
      h("p", {}, "Score a job description with the score-opportunity skill to add your first one; it will show up here.")));
  } else if (!records.length) {
    body.push(h("section", { class: "card empty" }, h("h2", {}, "Nothing matches these filters"),
      h("p", {}, "Try a wider date range or clear the source filter.")));
  } else {
    body.push(
      h("div", { class: "tiles" },
        tile("Opportunities", String(sum.total)),
        tile("Active", String(sum.active)),
        tile("Reached offer", String(sum.offers)),
        tile("Applied → offer", pct(sum.appliedToOffer), "of those that reached Applied"),
        tile("Stalled", String(sum.stalled), `no activity for ${p.stallDays}+ days`)),
      section("flow", "Where opportunities go", "Source → stages reached → outcome. Select a node or link to see who's in it.",
        () => renderSankey(records, p.stages, p.sources, width, select),
        () => sankeyTable(records, p.stages),
        h("ul", { class: "legend" },
          h("li", {}, h("span", { class: "swatch key-inferred", "aria-hidden": "true" }), "Striped: reconstructed (inferred) history"),
          h("li", {}, h("span", { class: "swatch c-stalled", "aria-hidden": "true" }), `Stalled: active, no activity for ${p.stallDays}+ days`))),
      section("conversion", "Stage conversion and time in stage",
        `Share that moved past each stage, among those decided (open ones excluded). Fewer than ${SMALL_SAMPLE} decided is a small sample.`,
        () => renderConversion(records, p.stages, select),
        () => conversionTable(records, p.stages)),
      section("activity", "Activity by week", "New opportunities, stage advances and closes per week.",
        () => renderActivity(records, width),
        () => activityTable(records),
        activityLegend()),
    );
  }
  body.push(h("p", { class: "footer muted" },
    `${records.length} of ${p.records.length} opportunities shown · data read ${new Date(p.generatedAt).toLocaleString()} · `,
    `sources: ${[...new Set(records.map(sourceLabel))].length}`));
  app.replaceChildren(...body.filter((x): x is Element => !!x));
}

async function load() {
  try {
    const res = await fetch("/api/data", { cache: "no-store" });
    const data = await res.json();
    if (!res.ok) {
      app.replaceChildren(banner("error", `Couldn't load your tracker (${data.error ?? res.status})`,
        [String(data.detail ?? "")]));
      return;
    }
    payload = data as Payload;
    render();
  } catch (e) {
    app.replaceChildren(banner("error", "Couldn't reach the dashboard server", [String(e),
      "It may have stopped (it shuts down after 2 idle hours). Start it again with /job-search-os:dashboard."]));
  }
}

let resizeTimer: number | undefined;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = window.setTimeout(render, 150);
});
window.addEventListener("hashchange", render);
void load();
