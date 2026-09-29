// Starts three dashboard servers for the Playwright suite, each on a fresh
// temp copy so nothing in the repo is ever a workspace or gets written:
//   8798: the 30-opportunity fixture   8797: an empty workspace
//   8796: a v0.1 workspace (legacy stages, no Source column, no history)
import { spawn, type ChildProcess } from "node:child_process";
import { cpSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = mkdtempSync(join(tmpdir(), "jso-e2e-"));
const main = fileURLToPath(new URL("../server/main.ts", import.meta.url));
const marker = '{"schema": 1}\n';

const fixture = join(root, "fixture");
cpSync(fileURLToPath(new URL("../fixtures/workspace", import.meta.url)), fixture, { recursive: true });
writeFileSync(join(fixture, ".job-search-os.json"), marker);

const empty = join(root, "empty");
cpSync(fixture, empty, { recursive: true, filter: (src) => src === fixture || src.endsWith(".job-search-os.json") });

const legacy = join(root, "legacy");
cpSync(empty, legacy, { recursive: true });
const header = "| Company | Role | Stage | Last Activity | Next Action | Next Action Date |\n| --- | --- | --- | --- | --- | --- |\n";
writeFileSync(join(legacy, "tracker.md"), `# Active Opportunities\n\n${header}| Acme | VP | Phone Screen | 2026-09-01 | Call | 2026-10-02 |\n| Beta | CTO | Applied | 2026-09-25 |  |  |\n`);
writeFileSync(join(legacy, "tracker_closed.md"), `# Closed Opportunities\n\n${header}| Gamma | Head of Eng | Onsite | 2026-08-01 |  |  |\n`);

const children: ChildProcess[] = [[fixture, 8798], [empty, 8797], [legacy, 8796]].map(([ws, port]) =>
  spawn(process.execPath, [main, "--workspace", String(ws), "--port", String(port)], { stdio: "inherit" }));

const stop = () => {
  children.forEach((c) => c.kill("SIGTERM"));
  rmSync(root, { recursive: true, force: true });
  process.exit(0);
};
process.on("SIGTERM", stop);
process.on("SIGINT", stop);
