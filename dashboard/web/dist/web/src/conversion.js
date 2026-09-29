// Stage conversion + time in stage: one row per ladder transition.
import { conversion } from "../../shared/aggregate.js";
import { days, h, pct, table } from "./dom.js";
export const SMALL_SAMPLE = 5;
function row(r, select) {
    const small = r.n < SMALL_SAMPLE;
    const bar = h("div", { class: "bar-track", "aria-hidden": "true" });
    const fill = bar.appendChild(h("div", { class: "bar-fill" }));
    fill.style.width = `${Math.round((r.rate ?? 0) * 100)}%`;
    const b = h("button", { type: "button", class: `conv-row${small ? " small" : ""}`,
        "aria-label": `${r.from} to ${r.to}: ${pct(r.rate)} of ${r.n} decided; median ${days(r.medianDays)} in ${r.from}` }, h("span", { class: "conv-stage" }, h("span", {}, r.from), h("span", { class: "arrow" }, " → "), h("span", {}, r.to)), bar, h("span", { class: "conv-rate" }, pct(r.rate), h("span", { class: "muted" }, ` ${r.advanced} of ${r.n}`), small ? h("span", { class: "tag" }, "small sample") : null), h("span", { class: "conv-days" }, `median ${days(r.medianDays)}`, h("span", { class: "muted" }, `· p75 ${days(r.p75Days)}`)), h("span", { class: "conv-open muted" }, r.open ? `${r.open} open` : ""));
    b.addEventListener("click", () => select(`Reached ${r.from}`, r.recordKeys));
    return b;
}
export function renderConversion(records, stages, select) {
    const rows = conversion(records, stages);
    return h("div", { class: "conv" }, h("div", { class: "conv-head", "aria-hidden": "true" }, h("span", {}, "Transition"), h("span", {}, "Converted"), h("span", {}, ""), h("span", {}, "Time in first stage"), h("span", {}, "")), ...rows.map((r) => row(r, select)));
}
export function conversionTable(records, stages) {
    return table("Stage conversion and time in stage", ["From", "To", "Reached", "Advanced", "Still open", "Rate", "Median days", "p75 days"], conversion(records, stages).map((r) => [r.from, r.to, r.reached, r.advanced, r.open, pct(r.rate),
        days(r.medianDays), days(r.p75Days)]));
}
