// Dashboard settings from the workspace marker (.job-search-os.json).
import { readFileSync } from "node:fs";
import { join } from "node:path";

export const MARKER = ".job-search-os.json";
export const DEFAULT_STALL_DAYS = 21;

/** `dashboard.stallDays` if it's a positive integer, else the default. */
export function readStallDays(workspace: string): number {
  try {
    const cfg = JSON.parse(readFileSync(join(workspace, MARKER), "utf8")) as { dashboard?: { stallDays?: unknown } };
    const v = cfg?.dashboard?.stallDays;
    return typeof v === "number" && Number.isInteger(v) && v > 0 ? v : DEFAULT_STALL_DAYS;
  } catch {
    return DEFAULT_STALL_DAYS;
  }
}
