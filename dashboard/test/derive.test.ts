import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { derive, slugify } from "../server/derive.ts";
import type { Export, ExportRow, TrackerEvent } from "../shared/types.ts";

const FIXTURE: Export = JSON.parse(
  readFileSync(new URL("../fixtures/export.json", import.meta.url), "utf8"),
);
const NOW = new Date(2026, 8, 28, 12, 0, 0); // 2026-09-28 local

function row(company: string, role: string, extra: Partial<ExportRow> = {}): ExportRow {
  return {
    company, role, slug: `${slugify(company)}/${slugify(role)}`, stage: "Applied",
    source: "Referral", last_activity: "2026-09-01", next_action: "", next_action_date: "",
    ...extra,
  };
}

function ev(company: string, role: string, type: TrackerEvent["type"], ts: string,
            extra: Partial<TrackerEvent> = {}): TrackerEvent {
  return { ts, company, role, type, inferred: false, ...extra };
}

function exp(parts: Partial<Export>): Export {
  return {
    schema: 1, stages: FIXTURE.stages, outcomes: FIXTURE.outcomes, sources: FIXTURE.sources,
    active: [], closed: [], events: [], warnings: [], ...parts,
  };
}

const opts = { stallDays: 21, now: NOW };

test("slugify matches tracker.py for every fixture row", () => {
  for (const r of [...FIXTURE.active, ...FIXTURE.closed]) {
    assert.equal(`${slugify(r.company)}/${slugify(r.role)}`, r.slug);
  }
  assert.equal(slugify("  ---  "), "unnamed");
});

test("path is built from events in order", () => {
  const p = derive(exp({
    active: [row("Acme", "VP", { stage: "Hiring Manager" })],
    events: [
      ev("Acme", "VP", "add", "2026-08-01T10:00:00", { to: "Identified" }),
      ev("Acme", "VP", "stage", "2026-08-03T10:00:00", { from: "Identified", to: "Applied" }),
      ev("Acme", "VP", "source", "2026-08-04T10:00:00", { source: "Other" }),
      ev("Acme", "VP", "stage", "2026-08-09T10:00:00", { from: "Applied", to: "Hiring Manager", inferred: true }),
    ],
  }), opts);
  const [r] = p.records;
  assert.deepEqual(r!.path, [
    { stage: "Identified", ts: "2026-08-01T10:00:00", inferred: false },
    { stage: "Applied", ts: "2026-08-03T10:00:00", inferred: false },
    { stage: "Hiring Manager", ts: "2026-08-09T10:00:00", inferred: true },
  ]);
  assert.equal(r!.addedAt, "2026-08-01T10:00:00");
  assert.equal(p.noHistory, false);
});

test("no events: path falls back to current stage, marked inferred", () => {
  const p = derive(exp({ active: [row("Acme", "VP", { stage: "Offer", last_activity: "2026-09-20" })] }), opts);
  assert.deepEqual(p.records[0]!.path, [{ stage: "Offer", ts: "2026-09-20", inferred: true }]);
  assert.equal(p.records[0]!.addedAt, "2026-09-20");
  assert.equal(p.noHistory, true);
});

test("stalled flips exactly at stallDays; closed never stalled", () => {
  const p = derive(exp({
    active: [
      row("A", "x", { last_activity: "2026-09-08" }), // 20 days
      row("B", "x", { last_activity: "2026-09-07" }), // 21 days
      row("C", "x", { last_activity: "" }),
    ],
    closed: [row("D", "x", { last_activity: "2026-01-01", outcome: "Rejected" })],
  }), opts);
  assert.deepEqual(p.records.map((r) => [r.company, r.stalled]),
    [["A", false], ["B", true], ["C", false], ["D", false]]);
});

test("closed records carry outcome and closedAt from the close event", () => {
  const p = derive(exp({
    closed: [row("Acme", "VP", { outcome: "Ghosted", last_activity: "2026-09-01" })],
    events: [
      ev("Acme", "VP", "add", "2026-08-01T10:00:00", { to: "Applied" }),
      ev("Acme", "VP", "close", "2026-08-30T10:00:00", { from: "Applied", outcome: "Ghosted" }),
    ],
  }), opts);
  const [r] = p.records;
  assert.equal(r!.status, "closed");
  assert.equal(r!.outcome, "Ghosted");
  assert.equal(r!.closedAt, "2026-08-30T10:00:00");
  assert.deepEqual(r!.path.map((s) => s.stage), ["Applied"]);
});

test("re-added opportunity: each lifetime's events go to its own record", () => {
  const p = derive(exp({
    active: [row("Acme", "VP", { stage: "Recruiter Screen" })],
    closed: [row("Acme", "VP", { outcome: "Rejected" })],
    events: [
      ev("Acme", "VP", "add", "2026-06-01T10:00:00", { to: "Applied" }),
      ev("Acme", "VP", "close", "2026-06-10T10:00:00", { from: "Applied", outcome: "Rejected" }),
      ev("Acme", "VP", "add", "2026-08-01T10:00:00", { to: "Identified" }),
      ev("Acme", "VP", "stage", "2026-08-05T10:00:00", { from: "Identified", to: "Recruiter Screen" }),
    ],
  }), opts);
  const active = p.records.find((r) => r.status === "active")!;
  const closed = p.records.find((r) => r.status === "closed")!;
  assert.deepEqual(active.path.map((s) => s.stage), ["Identified", "Recruiter Screen"]);
  assert.deepEqual(closed.path.map((s) => s.stage), ["Applied"]);
  assert.notEqual(active.key, closed.key);
  assert.equal(active.slug, closed.slug);
});

test("orphan events are dropped with a warning", () => {
  const p = derive(exp({
    active: [row("Acme", "VP")],
    events: [ev("Gone", "PM", "add", "2026-08-01T10:00:00", { to: "Applied" })],
  }), opts);
  assert.equal(p.records.length, 1);
  assert.match(p.warnings.join("\n"), /Gone \/ PM/);
});

test("unknown stages are kept as-is", () => {
  const p = derive(exp({ active: [row("Acme", "VP", { stage: "Networking" })] }), opts);
  assert.equal(p.records[0]!.stage, "Networking");
  assert.equal(p.records[0]!.path[0]!.stage, "Networking");
});

test("export warnings pass through", () => {
  const p = derive(exp({ warnings: ["line 3 is bad"] }), opts);
  assert.deepEqual(p.warnings, ["line 3 is bad"]);
  assert.equal(p.stallDays, 21);
});

test("fixture: one record per row, Northwind split, orphan warned", () => {
  const p = derive(FIXTURE, opts);
  assert.equal(p.records.length, FIXTURE.active.length + FIXTURE.closed.length);
  assert.equal(new Set(p.records.map((r) => r.key)).size, p.records.length);
  const northwind = p.records.filter((r) => r.company === "Northwind");
  assert.equal(northwind.length, 2);
  assert.match(p.warnings.join("\n"), /Deleted Co \/ PM/);
  const cobalt = p.records.find((r) => r.company === "Cobalt Labs")!;
  assert.ok(cobalt.path.every((s) => s.inferred));
});

test("events of a removed opportunity are dropped silently", () => {
  const p = derive(exp({
    active: [row("Acme", "VP")],
    events: [
      ev("Rich", "Networking", "add", "2026-08-01T10:00:00", { to: "Identified" }),
      ev("Rich", "Networking", "remove", "2026-09-29T10:00:00"),
    ],
  }), opts);
  assert.equal(p.records.length, 1);
  assert.deepEqual(p.warnings, []);
});

test("a removed-then-re-added opportunity keeps only its new lifetime", () => {
  const p = derive(exp({
    active: [row("Rich", "Networking", { stage: "Applied" })],
    events: [
      ev("Rich", "Networking", "add", "2026-08-01T10:00:00", { to: "Identified" }),
      ev("Rich", "Networking", "remove", "2026-08-05T10:00:00"),
      ev("Rich", "Networking", "add", "2026-09-01T10:00:00", { to: "Applied" }),
    ],
  }), opts);
  assert.deepEqual(p.records[0]!.path.map((s) => s.ts), ["2026-09-01T10:00:00"]);
  assert.deepEqual(p.warnings, []);
});

test("close and source events alone are not stage history", () => {
  const p = derive(exp({
    closed: [row("Acme", "VP", { outcome: "Passed" })],
    events: [
      ev("Acme", "VP", "close", "2026-09-02T00:00:00", { from: "Identified", outcome: "Passed" }),
      ev("Acme", "VP", "source", "2026-09-29T09:40:00", { source: "Other" }),
    ],
  }), opts);
  assert.equal(p.noHistory, true);
  assert.equal(p.records[0]!.closedAt, "2026-09-02T00:00:00");
});
