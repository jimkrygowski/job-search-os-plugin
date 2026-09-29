// The contract between tracker.py's `export --json`, the server, and the
// browser. dashboard/fixtures/export.json is a real instance of `Export`.

export type ExportRow = {
  company: string;
  role: string;
  slug: string;
  stage: string;
  source: string;
  last_activity: string;
  next_action: string;
  next_action_date: string;
  outcome?: string;
};

export type TrackerEvent = {
  ts: string;
  company: string;
  role: string;
  type: "add" | "stage" | "close" | "source" | "remove";
  from?: string;
  to?: string;
  outcome?: string;
  source?: string;
  inferred?: boolean;
};

export type Export = {
  schema: number;
  stages: string[];
  outcomes: string[];
  sources: string[];
  active: ExportRow[];
  closed: ExportRow[];
  events: TrackerEvent[];
  warnings: string[];
};

export type PathStep = { stage: string; ts: string; inferred: boolean };

export type OpportunityRecord = {
  company: string;
  role: string;
  /** Unique per record. Usually the folder slug; a re-added opportunity's
   * earlier, closed lifetime gets a `#closed-<n>` suffix. */
  key: string;
  /** Folder under <workspace>/opportunity/, for the notes endpoint. */
  slug: string;
  source: string;
  status: "active" | "closed";
  stage: string;
  path: PathStep[];
  outcome: string | null;
  /** When the closing happened, if known (close event, else last activity). */
  closedAt: string | null;
  addedAt: string;
  lastActivity: string;
  stalled: boolean;
  nextAction: string;
  nextActionDate: string;
};

export type Payload = {
  records: OpportunityRecord[];
  stages: string[];
  outcomes: string[];
  sources: string[];
  stallDays: number;
  warnings: string[];
  generatedAt: string;
  /** True when no opportunity has any recorded (non-fallback) history. */
  noHistory: boolean;
};

export type Filters = {
  range: "30" | "90" | "all";
  sources: string[];
  status: "active" | "closed" | "all";
};
