import { endLabel, sourceLabel } from "../../shared/aggregate.js";
import { h, shortDate } from "./dom.js";
import { renderMarkdown } from "./markdown.js";
let panel = null;
let returnFocus = null;
function focusables(root) {
    return [...root.querySelectorAll("button, a[href], [tabindex='0']")].filter((e) => !e.hasAttribute("disabled"));
}
function ensurePanel() {
    if (panel)
        return panel;
    panel = h("aside", { class: "drawer", role: "dialog", "aria-modal": "true", "aria-labelledby": "drawer-title", hidden: true });
    panel.addEventListener("keydown", (e) => {
        if (e.key === "Escape")
            return closeDrawer();
        if (e.key !== "Tab")
            return;
        const items = focusables(panel);
        if (!items.length)
            return;
        const first = items[0], last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
        }
        else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
        }
    });
    document.body.append(h("div", { class: "scrim", hidden: true }), panel);
    document.querySelector(".scrim").addEventListener("click", closeDrawer);
    return panel;
}
export function closeDrawer() {
    if (!panel || panel.hidden)
        return;
    panel.hidden = true;
    document.querySelector(".scrim").hidden = true;
    if (returnFocus instanceof HTMLElement || returnFocus instanceof SVGElement)
        returnFocus.focus();
}
function frame(title, body, back) {
    const p = ensurePanel();
    const close = h("button", { type: "button", class: "icon-button", "aria-label": "Close" }, "×");
    close.addEventListener("click", closeDrawer);
    const backBtn = back ? h("button", { type: "button", class: "link-button" }, "← All in this group") : null;
    backBtn?.addEventListener("click", back);
    p.replaceChildren(h("header", { class: "drawer-head" }, h("h2", { id: "drawer-title" }, title), close), ...(backBtn ? [backBtn] : []), h("div", { class: "drawer-body" }, ...body));
    if (p.hidden) {
        returnFocus = document.activeElement;
        p.hidden = false;
        document.querySelector(".scrim").hidden = false;
    }
    (backBtn ?? close).focus();
}
export function openGroup(title, records) {
    const list = h("ul", { class: "opp-list" }, ...records.map((r) => {
        const b = h("button", { type: "button", class: "opp" }, h("span", { class: "opp-name" }, `${r.company} — ${r.role}`), h("span", { class: "muted" }, `${endLabel(r)} · ${sourceLabel(r)}`));
        b.addEventListener("click", () => openRecord(r, () => openGroup(title, records)));
        return h("li", {}, b);
    }));
    frame(`${title} (${records.length})`, records.length ? [list] : [h("p", { class: "muted" }, "No opportunities match.")]);
}
function field(label, value) {
    return [h("dt", {}, label), h("dd", {}, value || "—")];
}
export function openRecord(r, back) {
    const notes = h("div", { class: "notes" }, h("p", { class: "muted" }, "Loading notes…"));
    frame(`${r.company} — ${r.role}`, [
        h("dl", { class: "fields" }, ...field("Status", r.status === "closed" ? `Closed: ${r.outcome ?? "—"}` : r.stalled ? "Active (stalled)" : "Active"), ...field("Stage", r.stage), ...field("Source", sourceLabel(r)), ...field("Last activity", shortDate(r.lastActivity)), ...(r.status === "active" ? [...field("Next action", r.nextAction), ...field("Next action date", r.nextActionDate)] : [])),
        h("h3", {}, "Timeline"),
        h("ol", { class: "timeline" }, ...r.path.map((st) => h("li", {}, h("span", { class: "tl-date" }, shortDate(st.ts)), h("span", {}, st.stage), st.inferred ? h("span", { class: "tag" }, "inferred") : null)), ...(r.closedAt ? [h("li", {}, h("span", { class: "tl-date" }, shortDate(r.closedAt)), h("span", {}, `Closed: ${r.outcome ?? ""}`))] : [])),
        h("h3", {}, "Notes"),
        notes,
    ], back);
    fetch(`/api/notes/${r.slug}`).then(async (res) => {
        if (res.status === 404)
            return notes.replaceChildren(h("p", { class: "muted" }, "No notes.md for this opportunity."));
        if (!res.ok)
            throw new Error(`HTTP ${res.status}`);
        const html = renderMarkdown(await res.text()); // escaped by construction
        notes.innerHTML = html;
    }).catch((e) => notes.replaceChildren(h("p", { class: "muted" }, `Couldn't load notes (${String(e)}).`)));
}
