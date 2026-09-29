import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  activity, applyFilters, conversion, isoWeek, quantile, sankey, sourceLabel, summary,
} from "../shared/aggregate.ts";
import { derive } from "../server/derive.ts";
import type { Export, OpportunityRecord, PathStep } from "../shared/types.ts";

const STAGES = ["Identified", "Applied", "Recruiter Screen", "Hiring Manager", "Interview Loop", "Offer"];
const NOW = new Date(2026, 8, 28, 12);

let n = 0;
function rec(steps: [string, string, boolean?][], extra: Partial<OpportunityRecord> = {}): OpportunityRecord {
  n += 1;
  const path: PathStep[] = steps.map(([stage, ts, inferred]) => ({ stage, ts, inferred: inferred ?? false }));
  return {
    company: `C${n}`, role: "R", key: `c${n}/r`, slug: `c${n}/r`, source: "Referral",
    status: "active", stage: path[path.length - 1]!.stage, path, outcome: null, closedAt: null,
    addedAt: path[0]!.ts, lastActivity: path[path.length - 1]!.ts.slice(0, 10), stalled: false,
    nextAction: "", nextActionDate: "", ...extra,
  };
}

function flows(g: ReturnType<typeof sankey>) {
  const into = new Map<string, number>();
  const out = new Map<string, number>();
  for (const l of g.links) {
    out.set(l.source, (out.get(l.source) ?? 0) + l.value);
    into.set(l.target, (into.get(l.target) ?? 0) + l.value);
  }
  return { into, out };
}

test("sankey conserves flow at every stage node", () => {
  const FIXTURE: Export = JSON.parse(readFileSync(new URL("../fixtures/export.json", import.meta.url), "utf8"));
  const p = derive(FIXTURE, { stallDays: 21, now: NOW });
  const g = sankey(p.records, p.stages);
  const { into, out } = flows(g);
  for (const node of g.nodes.filter((x) => x.kind === "stage")) {
    assert.equal(into.get(node.id), out.get(node.id), node.id);
  }
  const total = g.nodes.filter((x) => x.kind === "source").reduce((s, x) => s + (out.get(x.id) ?? 0), 0);
  assert.equal(total, p.records.length);
});

test("sankey links skipped stages directly and ends by status", () => {
  const closed = rec([["Identified", "2026-08-01"], ["Hiring Manager", "2026-08-05"]],
    { status: "closed", outcome: "Rejected" });
  const active = rec([["Applied", "2026-08-01"]]);
  const stalled = rec([["Applied", "2026-08-01"]], { stalled: true, source: "" });
  const g = sankey([closed, active, stalled], STAGES);
  const ids = g.links.map((l) => `${l.source} -> ${l.target} (${l.value})`).sort();
  assert.deepEqual(ids, [
    "source:Referral -> stage:Applied (1)",
    "source:Referral -> stage:Identified (1)",
    "source:Unknown -> stage:Applied (1)",
    "stage:Applied -> end:Stalled in Applied (1)",
    "stage:Applied -> end:Still in Applied (1)",
    "stage:Hiring Manager -> end:Rejected (1)",
    "stage:Identified -> stage:Hiring Manager (1)",
  ]);
  const link = g.links.find((l) => l.target === "stage:Hiring Manager")!;
  assert.deepEqual(link.recordKeys, [closed.key]);
});

test("sankey never goes backwards (keeps the graph acyclic)", () => {
  const r = rec([["Interview Loop", "2026-08-01"], ["Hiring Manager", "2026-08-02"], ["Offer", "2026-08-03"]]);
  const g = sankey([r], STAGES);
  assert.ok(!g.links.some((l) => l.target === "stage:Hiring Manager"));
  assert.ok(g.links.some((l) => l.source === "stage:Interview Loop" && l.target === "stage:Offer"));
});

test("sankey places an unknown stage before the ladder", () => {
  const r = rec([["Networking", "2026-08-01"], ["Applied", "2026-08-02"]]);
  const g = sankey([r], STAGES);
  assert.ok(g.links.some((l) => l.source === "stage:Networking" && l.target === "stage:Applied"));
  const later = rec([["Applied", "2026-08-01"], ["Networking", "2026-08-02"]]);
  assert.ok(!sankey([later], STAGES).links.some((l) => l.target === "stage:Networking"));
});

test("allInferred is true only when every contributing transition is inferred", () => {
  const a = rec([["Identified", "2026-08-01", true], ["Applied", "2026-08-02", true]]);
  const b = rec([["Identified", "2026-08-01", true], ["Applied", "2026-08-03", false]]);
  const onlyA = sankey([a], STAGES).links.find((l) => l.target === "stage:Applied")!;
  const both = sankey([a, b], STAGES).links.find((l) => l.target === "stage:Applied")!;
  assert.equal(onlyA.allInferred, true);
  assert.equal(both.allInferred, false);
  assert.equal(both.value, 2);
});

test("filters: AND across kinds, OR within sources, empty sources = all", () => {
  const recent = rec([["Applied", "2026-09-20"]], { source: "Referral" });
  const old = rec([["Applied", "2026-05-01"]], { source: "Job Alert" });
  const closed = rec([["Applied", "2026-09-10"]], { source: "Job Alert", status: "closed", outcome: "Rejected" });
  const blank = rec([["Applied", "2026-09-10"]], { source: "" });
  const all = [recent, old, closed, blank];
  const keys = (f: Parameters<typeof applyFilters>[1]) => applyFilters(all, f, NOW).map((r) => r.key);
  assert.deepEqual(keys({ range: "all", sources: [], status: "all" }), all.map((r) => r.key));
  assert.deepEqual(keys({ range: "30", sources: [], status: "all" }), [recent.key, closed.key, blank.key]);
  assert.deepEqual(keys({ range: "all", sources: ["Job Alert", "Unknown"], status: "all" }), [old.key, closed.key, blank.key]);
  assert.deepEqual(keys({ range: "30", sources: ["Job Alert"], status: "closed" }), [closed.key]);
  assert.deepEqual(keys({ range: "90", sources: [], status: "active" }), [recent.key, blank.key]);
  assert.equal(sourceLabel(blank), "Unknown");
});

test("quantile: median and p75 for small n", () => {
  assert.equal(quantile([], 0.5), null);
  assert.equal(quantile([4], 0.5), 4);
  assert.equal(quantile([4], 0.75), 4);
  assert.equal(quantile([2, 4], 0.5), 3);
  assert.equal(quantile([2, 4], 0.75), 3.5);
  assert.equal(quantile([9, 1, 5], 0.5), 5);
  assert.equal(quantile([1, 2, 3, 4], 0.5), 2.5);
  assert.equal(quantile([1, 2, 3, 4], 0.75), 3.25);
});

test("conversion: funnel counts, open excluded from rate, days in stage", () => {
  const a = rec([["Applied", "2026-08-01"], ["Recruiter Screen", "2026-08-05"], ["Offer", "2026-08-20"]],
    { status: "closed", outcome: "Accepted" });
  const b = rec([["Applied", "2026-08-01"], ["Recruiter Screen", "2026-08-11"]],
    { status: "closed", outcome: "Rejected", closedAt: "2026-08-15T10:00:00" });
  const c = rec([["Applied", "2026-08-01"]], { status: "closed", outcome: "Ghosted", closedAt: "2026-08-31" });
  const d = rec([["Applied", "2026-09-01"]]); // still open in Applied
  const rows = conversion([a, b, c, d], STAGES);
  const applied = rows.find((r) => r.from === "Applied")!;
  assert.deepEqual([applied.to, applied.reached, applied.advanced, applied.open, applied.n], ["Recruiter Screen", 4, 2, 1, 3]);
  assert.equal(applied.rate, 2 / 3);
  // days in Applied: a=4, b=10, c=30 (closedAt); d still open -> excluded
  assert.equal(applied.medianDays, 10);
  const screen = rows.find((r) => r.from === "Recruiter Screen")!;
  assert.deepEqual([screen.reached, screen.advanced, screen.n], [2, 1, 2]);
  assert.deepEqual([screen.medianDays, screen.p75Days], [9.5, 12.25]); // a=15, b=4
  // Funnel semantics: starting later than Identified counts as passing it.
  const identified = rows.find((r) => r.from === "Identified")!;
  assert.deepEqual([identified.reached, identified.rate, identified.medianDays], [4, 1, null]);
  const offer = rows.find((r) => r.from === "Interview Loop")!;
  assert.deepEqual([offer.reached, offer.n, offer.rate], [1, 1, 1]);
  assert.equal(rows.length, STAGES.length - 1);
});

test("isoWeek handles the year boundary", () => {
  assert.equal(isoWeek("2025-12-28"), "2025-W52");
  assert.equal(isoWeek("2025-12-29"), "2026-W01");
  assert.equal(isoWeek("2026-01-04T10:00:00"), "2026-W01");
  assert.equal(isoWeek("2026-01-05"), "2026-W02");
  assert.equal(isoWeek("2021-01-03"), "2020-W53");
});

test("activity buckets added/advanced/closed by week, filling gaps", () => {
  const a = rec([["Identified", "2025-12-29"], ["Applied", "2026-01-12"]],
    { status: "closed", outcome: "Rejected", closedAt: "2026-01-14T09:00:00" });
  const b = rec([["Applied", "2026-01-02"]]);
  const weeks = activity([a, b]);
  assert.deepEqual(weeks, [
    { week: "2026-W01", added: 2, advanced: 0, closed: 0 },
    { week: "2026-W02", added: 0, advanced: 0, closed: 0 },
    { week: "2026-W03", added: 0, advanced: 1, closed: 1 },
  ]);
  assert.deepEqual(activity([]), []);
});

test("summary counts", () => {
  const offer = rec([["Applied", "2026-08-01"], ["Offer", "2026-08-09"]]);
  const ident = rec([["Identified", "2026-08-01"]], { stalled: true });
  const rej = rec([["Applied", "2026-08-01"]], { status: "closed", outcome: "Rejected" });
  assert.deepEqual(summary([offer, ident, rej], STAGES),
    { total: 3, active: 2, offers: 1, appliedToOffer: 0.5, stalled: 1 });
  assert.equal(summary([], STAGES).appliedToOffer, null);
});
