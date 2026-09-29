// Tiny DOM helpers. All text goes in through textContent; the only
// innerHTML anywhere is renderMarkdown's escaped output.
function apply(el, attrs, children) {
    for (const [k, v] of Object.entries(attrs)) {
        if (v === undefined || v === null || v === false)
            continue;
        el.setAttribute(k, v === true ? "" : String(v));
    }
    for (const c of children) {
        if (c === null || c === undefined || c === false)
            continue;
        el.append(typeof c === "object" ? c : document.createTextNode(String(c)));
    }
    return el;
}
export function h(tag, attrs = {}, ...children) {
    return apply(document.createElement(tag), attrs, children);
}
const SVG_NS = "http://www.w3.org/2000/svg";
export function s(tag, attrs = {}, ...children) {
    return apply(document.createElementNS(SVG_NS, tag), attrs, children);
}
/** Makes an element keyboard-activatable like a button. */
export function activatable(el, label, onActivate) {
    el.setAttribute("tabindex", "0");
    el.setAttribute("role", "button");
    el.setAttribute("aria-label", label);
    el.addEventListener("click", onActivate);
    el.addEventListener("keydown", (e) => {
        const k = e.key;
        if (k === "Enter" || k === " ") {
            e.preventDefault();
            onActivate();
        }
    });
    return el;
}
// ---- Tooltip -----------------------------------------------------------------
let tip = null;
export function showTip(anchor, lines) {
    tip ??= document.body.appendChild(h("div", { class: "tooltip", role: "tooltip" }));
    tip.replaceChildren(...lines.map((l, i) => h("div", { class: i === 0 ? "tip-title" : "tip-line" }, l)));
    tip.hidden = false;
    const pad = 12;
    const { offsetWidth: w, offsetHeight: ht } = tip;
    const x = Math.min(anchor.clientX + pad, window.innerWidth - w - pad);
    const y = anchor.clientY + pad + ht > window.innerHeight ? anchor.clientY - ht - pad : anchor.clientY + pad;
    tip.style.left = `${Math.max(pad, x)}px`;
    tip.style.top = `${Math.max(pad, y)}px`;
}
export function hideTip() {
    if (tip)
        tip.hidden = true;
}
/** Hover and focus both show the tooltip, so keyboard users get it too. */
export function withTip(el, lines) {
    el.addEventListener("pointermove", (e) => showTip(e, lines()));
    el.addEventListener("pointerleave", hideTip);
    el.addEventListener("focus", () => {
        const r = el.getBoundingClientRect();
        showTip({ clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 }, lines());
    });
    el.addEventListener("blur", hideTip);
}
// ---- Tables & formatting -------------------------------------------------------
export function table(caption, headers, rows) {
    return h("div", { class: "table-wrap" }, h("table", {}, h("caption", {}, caption), h("thead", {}, h("tr", {}, ...headers.map((x) => h("th", { scope: "col" }, x)))), h("tbody", {}, ...rows.map((r) => h("tr", {}, ...r.map((c, i) => i === 0 ? h("th", { scope: "row" }, c) : h("td", { class: typeof c === "number" ? "num" : undefined }, c)))))));
}
export const pct = (x) => (x === null ? "—" : `${Math.round(x * 100)}%`);
export const days = (x) => (x === null ? "—" : `${Math.round(x * 10) / 10}d`);
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function shortDate(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
    return m ? `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}, ${m[1]}` : iso || "—";
}
