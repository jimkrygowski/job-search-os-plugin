// Turns tracker.py's export into one record per opportunity. Pure: the
// clock is passed in, nothing is read or written.
import { daysSince } from "../shared/dates.ts";
import type { Export, ExportRow, OpportunityRecord, Payload, PathStep, TrackerEvent } from "../shared/types.ts";

/** Same transform as tracker.py's slugify(); a test pins them together. */
export function slugify(text: string): string {
  const slug = text.trim().replace(/[^a-zA-Z0-9]+/g, "_").replace(/^_+|_+$/g, "").toLowerCase();
  return slug || "unnamed";
}

const keyOf = (company: string, role: string) => `${slugify(company)}/${slugify(role)}`;

/** Splits one opportunity's events into lifetimes, one per `add`. Events
 * before the first `add` (e.g. a log started mid-pipeline) join the first. */
function lifetimes(events: TrackerEvent[]): TrackerEvent[][] {
  const out: TrackerEvent[][] = [];
  for (const e of events) {
    if (e.type === "add" || out.length === 0) out.push([]);
    out[out.length - 1]!.push(e);
  }
  return out;
}

/** The tracker row's stage is the truth. `update-status --correction` and
 * `amend-closed` change it without writing an event, so the event path can
 * lag or overshoot it; bring the path in line, marking the fix as inferred. */
function reconcile(path: PathStep[], stage: string, lastActivity: string, stages: string[]): PathStep[] {
  const last = path[path.length - 1]!;
  if (last.stage === stage) return path;
  const at = path.map((s) => s.stage).lastIndexOf(stage);
  if (at !== -1) return path.slice(0, at + 1); // corrected back to a stage it did reach
  let kept = path;
  let cut: PathStep | undefined;
  const idx = stages.indexOf(stage);
  if (idx !== -1) {
    // Steps past the corrected stage were mis-recorded; the correction
    // takes the place (and date) of the first of them.
    const firstPast = path.findIndex((s) => stages.indexOf(s.stage) > idx);
    if (firstPast !== -1) {
      cut = path[firstPast];
      kept = path.slice(0, firstPast);
    }
  }
  const ts = cut?.ts ?? (lastActivity && lastActivity >= last.ts.slice(0, 10) ? lastActivity : last.ts);
  return [...kept, { stage, ts, inferred: true }];
}

function buildRecord(row: ExportRow, status: "active" | "closed", key: string, events: TrackerEvent[],
                     stages: string[], stallDays: number, now: Date): OpportunityRecord {
  let path: PathStep[] = [];
  let closedAt: string | null = null;
  for (const e of events) {
    if ((e.type === "add" || e.type === "stage") && e.to) {
      path.push({ stage: e.to, ts: e.ts, inferred: e.inferred === true });
    } else if (e.type === "close") {
      closedAt = e.ts;
    }
  }
  if (path.length === 0) {
    path.push({ stage: row.stage, ts: row.last_activity, inferred: true });
  }
  path = reconcile(path, row.stage, row.last_activity, stages);
  const idle = daysSince(row.last_activity, now);
  return {
    company: row.company,
    role: row.role,
    key,
    slug: row.slug,
    source: row.source,
    status,
    stage: row.stage,
    path,
    outcome: status === "closed" ? row.outcome || null : null,
    closedAt: status === "closed" ? closedAt ?? (row.last_activity || null) : null,
    addedAt: path[0]!.ts,
    lastActivity: row.last_activity,
    stalled: status === "active" && idle !== null && idle >= stallDays,
    nextAction: row.next_action,
    nextActionDate: row.next_action_date,
  };
}

export function derive(exp: Export, opts: { stallDays: number; now: Date }): Payload {
  const warnings = [...exp.warnings];

  const eventsByKey = new Map<string, TrackerEvent[]>();
  // Order by day, then add → stage → source → close → remove within a day,
  // then clock time. Back-dated and backfilled events carry nominal times
  // (a close dated "2026-09-02" is 00:00), so clock time alone would put a
  // same-day close before the add that started it.
  const RANK: Record<TrackerEvent["type"], number> = { add: 0, stage: 1, source: 2, close: 3, remove: 4 };
  // Exception: real (non-inferred) events are logged as they happen, so a
  // real re-add logged after a real close on the same day starts a new
  // application; it and that day's later real events sort after the close.
  const reopened = new Set<TrackerEvent>();
  const closedOn = new Map<string, string>();
  const reopenedOn = new Map<string, string>();
  for (const e of exp.events) { // file order
    if (e.inferred) continue;
    const k = keyOf(e.company, e.role);
    const day = e.ts.slice(0, 10);
    if (e.type === "close") closedOn.set(k, day);
    else if (e.type === "add" && closedOn.get(k) === day) reopenedOn.set(k, day);
    if (reopenedOn.get(k) === day && e.type !== "close") reopened.add(e);
  }
  const rank = (e: TrackerEvent) => (reopened.has(e) ? 10 : 0) + RANK[e.type];
  const ordered = [...exp.events].sort((a, b) =>
    a.ts.slice(0, 10).localeCompare(b.ts.slice(0, 10)) || rank(a) - rank(b) || a.ts.localeCompare(b.ts));
  for (const e of ordered) {
    const k = keyOf(e.company, e.role);
    const events = eventsByKey.get(k) ?? [];
    if (e.type === "remove") {
      // `remove` means the current application was never a real opportunity:
      // drop its events, but keep earlier (closed) applications' history.
      const lastAdd = events.map((x) => x.type).lastIndexOf("add");
      const lastClose = events.map((x) => x.type).lastIndexOf("close");
      eventsByKey.set(k, events.slice(0, lastAdd > lastClose ? lastAdd : lastClose + 1));
    } else {
      eventsByKey.set(k, [...events, e]);
    }
  }

  // Records list active opportunities first. Within one opportunity the
  // slots are oldest lifetime first: closed rows (table order), then active.
  type Slot = { row: ExportRow; status: "active" | "closed" };
  const slotsByKey = new Map<string, Slot[]>();
  const order: string[] = [];
  const add = (row: ExportRow, status: Slot["status"]) => {
    const k = keyOf(row.company, row.role);
    if (!slotsByKey.has(k)) { slotsByKey.set(k, []); order.push(k); }
    slotsByKey.get(k)!.push({ row, status });
  };
  exp.active.forEach((r) => add(r, "active"));
  exp.closed.forEach((r) => add(r, "closed"));
  for (const slots of slotsByKey.values()) {
    slots.sort((a, b) => (a.status === b.status ? 0 : a.status === "closed" ? -1 : 1));
  }

  const records: OpportunityRecord[] = [];
  let anyHistory = false;
  for (const k of order) {
    const slots = slotsByKey.get(k)!;
    const lives = lifetimes(eventsByKey.get(k) ?? []);
    eventsByKey.delete(k);
    // Newest lifetimes belong to the newest rows; surplus old lifetimes
    // have no row left to describe.
    const offset = lives.length - slots.length;
    if (offset > 0) {
      warnings.push(`${slots[0]!.row.company} / ${slots[0]!.row.role}: ${offset} earlier history ` +
        `segment(s) have no matching tracker row and were ignored`);
    }
    slots.forEach((slot, i) => {
      const events = lives[i + offset] ?? [];
      if (events.some((e) => e.type === "add" || e.type === "stage")) anyHistory = true;
      const key = slots.length > 1 && slot.status === "closed" ? `${k}#closed-${i + 1}` : k;
      records.push(buildRecord(slot.row, slot.status, key, events, exp.stages, opts.stallDays, opts.now));
    });
  }

  for (const events of eventsByKey.values()) {
    if (!events.length) continue;
    const e = events[0]!;
    warnings.push(`${e.company} / ${e.role}: ${events.length} event(s) match no tracker row and were ignored`);
  }

  return {
    records,
    stages: exp.stages,
    outcomes: exp.outcomes,
    sources: exp.sources,
    stallDays: opts.stallDays,
    warnings,
    generatedAt: opts.now.toISOString(),
    noHistory: records.length > 0 && !anyHistory,
  };
}
