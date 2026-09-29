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

function buildRecord(row: ExportRow, status: "active" | "closed", key: string,
                     events: TrackerEvent[], stallDays: number, now: Date): OpportunityRecord {
  const path: PathStep[] = [];
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
  for (const e of [...exp.events].sort((a, b) => a.ts.localeCompare(b.ts))) {
    const k = keyOf(e.company, e.role);
    eventsByKey.set(k, [...(eventsByKey.get(k) ?? []), e]);
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
      if (events.length) anyHistory = true;
      const key = slots.length > 1 && slot.status === "closed" ? `${k}#closed-${i + 1}` : k;
      records.push(buildRecord(slot.row, slot.status, key, events, opts.stallDays, opts.now));
    });
  }

  for (const events of eventsByKey.values()) {
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
