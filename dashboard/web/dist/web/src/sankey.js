// Outcome Sankey: Source -> stages reached -> outcome / current state.
import { sankey as buildGraph } from "../../shared/aggregate.js";
import { activatable, s, table, withTip } from "./dom.js";
import { endClass, sourceClass } from "./theme.js";
function nodeClass(n, sources) {
    if (n.kind === "source")
        return sourceClass(n.label, sources);
    if (n.kind === "end")
        return endClass(n.label);
    return "c-stage";
}
function nodeKeys(n, links) {
    const keys = new Set();
    for (const l of links) {
        if (l.source === n.id || l.target === n.id)
            l.recordKeys.forEach((k) => keys.add(k));
    }
    return [...keys];
}
const END_ORDER = ["Accepted", "Declined Offer", "Withdrew", "Passed", "Rejected", "Role Filled", "No Role", "Ghosted", "Closed"];
/** Vertical order within a column: sources in the tracker's fixed order,
 * the ladder in order, outcomes first, then open ones by stage. */
function rank(n, stages, sources) {
    if (n.kind === "source")
        return sources.includes(n.label) ? sources.indexOf(n.label) : 99;
    if (n.kind === "stage")
        return stages.includes(n.label) ? stages.indexOf(n.label) : -1;
    if (END_ORDER.includes(n.label))
        return END_ORDER.indexOf(n.label);
    const stage = n.label.replace(/^(Still|Stalled) in /, "");
    const i = stages.includes(stage) ? stages.indexOf(stage) : -1;
    return 10 + (i + 1) * 2 + (n.label.startsWith("Stalled") ? 1 : 0);
}
export function renderSankey(records, stages, sources, width, select) {
    const graph = buildGraph(records, stages);
    const order = new Map(graph.nodes.map((n) => [n.id, rank(n, stages, sources)]));
    const plain = graph.links.map((l) => ({ ...l, recordKeys: [...l.recordKeys] }));
    const left = width < 640 ? 90 : 130;
    const right = width < 640 ? 130 : 220;
    const perNode = Math.max(...[0, 1, 2].map((k) => graph.nodes.filter((n) => (k === 0 ? n.kind === "source" : k === 1 ? n.kind === "end" : n.kind === "stage")).length));
    const height = Math.max(340, Math.min(860, 60 + perNode * 48));
    const layout = d3.sankey()
        .nodeId((n) => n.id)
        .nodeWidth(12)
        .nodePadding(26)
        .nodeAlign(d3.sankeyJustify)
        .nodeSort((a, b) => (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0))
        .extent([[left, 24], [Math.max(left + 200, width - right), height - 8]]);
    const { nodes, links } = layout({ nodes: graph.nodes.map((n) => ({ ...n })), links: plain });
    const svg = s("svg", {
        class: "sankey", width, height, viewBox: `0 0 ${width} ${height}`, role: "group",
        "aria-label": `Outcome flow for ${records.length} opportunities`,
    });
    const path = d3.sankeyLinkHorizontal();
    const nodeOf = (x) => x;
    const linkLayer = s("g", { class: "links" });
    for (const l of links) {
        const src = nodeOf(l.source);
        const tgt = nodeOf(l.target);
        const cls = src.kind === "source" ? sourceClass(src.label, sources) : "c-flow";
        const el = s("path", {
            d: path(l) ?? "", class: `link ${cls}${l.allInferred ? " inferred" : ""}`,
            "stroke-width": Math.max(1, l.width ?? 1),
        });
        const label = `${src.label} → ${tgt.label}: ${l.value}${l.allInferred ? " (reconstructed history)" : ""}`;
        activatable(el, label, () => select(`${src.label} → ${tgt.label}`, l.recordKeys));
        withTip(el, () => [`${src.label} → ${tgt.label}`, `${l.value} ${l.value === 1 ? "opportunity" : "opportunities"}`,
            ...(l.allInferred ? ["Reconstructed (inferred) history"] : [])]);
        linkLayer.append(el);
    }
    const nodeLayer = s("g", { class: "nodes" });
    for (const n of nodes) {
        const x0 = n.x0 ?? 0, x1 = n.x1 ?? 0, y0 = n.y0 ?? 0, y1 = n.y1 ?? 0;
        const g = s("g", { class: `node ${nodeClass(n, sources)}` });
        g.append(s("rect", { x: x0, y: y0, width: x1 - x0, height: Math.max(2, y1 - y0), rx: 2 }));
        const keys = nodeKeys(n, graph.links);
        const count = n.kind === "stage" ? keys.length : n.value ?? keys.length;
        // Sources label to the left, ends to the right; stages sit above their
        // bar (with a surface halo) so they never run into the next column.
        // An off-ladder stage shares a column with a ladder stage, so it is
        // labelled on its left instead.
        const stage = n.kind === "stage" && stages.includes(n.label);
        const onLeft = n.kind === "source" || n.kind === "stage";
        g.append(s("text", {
            x: stage ? (x0 + x1) / 2 : onLeft ? x0 - 8 : x1 + 6,
            y: stage ? y0 - 7 : (y0 + y1) / 2, dy: stage ? 0 : "0.35em",
            "text-anchor": stage ? "middle" : onLeft ? "end" : "start", class: n.kind === "stage" ? "halo" : undefined,
        }, s("tspan", { class: "node-label" }, n.label), s("tspan", { class: "node-count", dx: 5 }, String(count))));
        activatable(g, `${n.label}: ${count}`, () => select(n.label, keys));
        withTip(g, () => [n.label, `${count} ${count === 1 ? "opportunity" : "opportunities"}`]);
        nodeLayer.append(g);
    }
    svg.append(linkLayer, nodeLayer);
    return svg;
}
export function sankeyTable(records, stages) {
    const graph = buildGraph(records, stages);
    const label = new Map(graph.nodes.map((n) => [n.id, n.label]));
    return table("Outcome flow: every link in the diagram", ["From", "To", "Opportunities", "History"], graph.links.map((l) => [label.get(l.source) ?? l.source, label.get(l.target) ?? l.target, l.value,
        l.allInferred ? "Reconstructed" : "Recorded"]));
}
