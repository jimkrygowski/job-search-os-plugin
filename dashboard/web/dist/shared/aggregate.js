// Pure functions from derived records (+ filters) to chart data. Runs in
// the browser; tested with node --test.
import { daysBetween, daysSince, isoWeek, weekStart } from "./dates.js";
export { isoWeek } from "./dates.js";
export const UNKNOWN_SOURCE = "Unknown";
export function sourceLabel(r) {
    return r.source || UNKNOWN_SOURCE;
}
export function applyFilters(records, f, now) {
    const maxAge = f.range === "all" ? null : Number(f.range);
    return records.filter((r) => {
        if (f.status !== "all" && r.status !== f.status)
            return false;
        if (f.sources.length && !f.sources.includes(sourceLabel(r)))
            return false;
        if (maxAge !== null) {
            const age = daysSince(r.addedAt, now);
            if (age === null || age > maxAge)
                return false;
        }
        return true;
    });
}
export function endLabel(r) {
    if (r.status === "closed")
        return r.outcome || "Closed";
    const last = r.path[r.path.length - 1].stage;
    return r.stalled ? `Stalled in ${last}` : `Still in ${last}`;
}
/** The record's path as the Sankey draws it: strictly forward along the
 * ladder, so the graph is acyclic. A stage outside the ladder (a legacy
 * name nothing mapped) may appear once, before any ladder stage. */
function forwardPath(r, stages) {
    const kept = [];
    let reached = -1;
    let unknownUsed = false;
    for (const step of r.path) {
        const i = stages.indexOf(step.stage);
        if (i === -1) {
            if (reached === -1 && !unknownUsed) {
                kept.push(step);
                unknownUsed = true;
            }
        }
        else if (i > reached) {
            kept.push(step);
            reached = i;
        }
    }
    return kept;
}
export function sankey(records, stages) {
    const nodes = new Map();
    const links = new Map();
    const node = (kind, label) => {
        const id = `${kind}:${label}`;
        if (!nodes.has(id))
            nodes.set(id, { id, label, kind });
        return id;
    };
    const link = (source, target, inferred, key) => {
        const id = `${source}\u0000${target}`;
        const l = links.get(id) ?? { source, target, value: 0, allInferred: true, recordKeys: [] };
        l.value += 1;
        l.allInferred &&= inferred;
        l.recordKeys.push(key);
        links.set(id, l);
    };
    for (const r of records) {
        const path = forwardPath(r, stages);
        let prev = node("source", sourceLabel(r));
        let lastInferred = path[0]?.inferred ?? true;
        for (const step of path) {
            const id = node("stage", step.stage);
            link(prev, id, step.inferred, r.key);
            prev = id;
            lastInferred = step.inferred;
        }
        link(prev, node("end", endLabel(r)), lastInferred, r.key);
    }
    // Stable order: sources, then the ladder, then ends (outcomes first).
    const rank = (n) => n.kind === "source" ? 0 : n.kind === "stage" ? 1 + (stages.indexOf(n.label) + 1) : 100;
    return {
        nodes: [...nodes.values()].sort((a, b) => rank(a) - rank(b) || a.label.localeCompare(b.label)),
        links: [...links.values()],
    };
}
// ---- Conversion and time in stage ------------------------------------------
export function quantile(values, q) {
    if (!values.length)
        return null;
    const sorted = [...values].sort((a, b) => a - b);
    const pos = q * (sorted.length - 1);
    const lo = Math.floor(pos);
    const hi = Math.ceil(pos);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}
function furthest(r, stages) {
    return Math.max(-1, ...r.path.map((s) => stages.indexOf(s.stage)));
}
export function conversion(records, stages) {
    return stages.slice(0, -1).map((from, i) => {
        const reachedRecs = records.filter((r) => furthest(r, stages) >= i);
        const advanced = reachedRecs.filter((r) => furthest(r, stages) > i).length;
        const open = reachedRecs.filter((r) => r.status === "active" && furthest(r, stages) === i).length;
        const n = reachedRecs.length - open;
        const days = [];
        for (const r of records) {
            const at = r.path.findIndex((s) => s.stage === from);
            if (at === -1)
                continue;
            const next = r.path[at + 1]?.ts ?? (r.status === "closed" ? r.closedAt : null);
            const d = next ? daysBetween(r.path[at].ts, next) : null;
            if (d !== null && d >= 0)
                days.push(d);
        }
        return {
            from, to: stages[i + 1], reached: reachedRecs.length, advanced, open, n,
            rate: n ? advanced / n : null,
            medianDays: quantile(days, 0.5),
            p75Days: quantile(days, 0.75),
            recordKeys: reachedRecs.map((r) => r.key),
        };
    });
}
export function activity(records) {
    const buckets = new Map();
    const bump = (iso, field) => {
        if (!iso)
            return;
        const week = isoWeek(iso);
        if (!week)
            return;
        const b = buckets.get(week) ?? { week, added: 0, advanced: 0, closed: 0 };
        b[field] += 1;
        buckets.set(week, b);
    };
    for (const r of records) {
        bump(r.addedAt, "added");
        r.path.slice(1).forEach((s) => bump(s.ts, "advanced"));
        if (r.status === "closed")
            bump(r.closedAt, "closed");
    }
    if (!buckets.size)
        return [];
    const starts = [...buckets.keys()].map(weekStart);
    const out = [];
    const WEEK = 7 * 86_400_000;
    for (let t = Math.min(...starts); t <= Math.max(...starts); t += WEEK) {
        const week = isoWeek(new Date(t).toISOString());
        out.push(buckets.get(week) ?? { week, added: 0, advanced: 0, closed: 0 });
    }
    return out;
}
export function summary(records, stages) {
    const offerIdx = stages.indexOf("Offer");
    const appliedIdx = stages.indexOf("Applied");
    const offers = records.filter((r) => offerIdx !== -1 && furthest(r, stages) >= offerIdx).length;
    const applied = records.filter((r) => appliedIdx !== -1 && furthest(r, stages) >= appliedIdx).length;
    return {
        total: records.length,
        active: records.filter((r) => r.status === "active").length,
        offers,
        appliedToOffer: applied ? offers / applied : null,
        stalled: records.filter((r) => r.stalled).length,
    };
}
