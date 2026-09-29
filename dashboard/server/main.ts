// Entry point: node dashboard/server/main.ts --workspace <root> [--port N]
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { MARKER, readStallDays } from "./config.ts";
import { derive } from "./derive.ts";
import { runExport } from "./exporter.ts";
import { createServer } from "./http.ts";

const IDLE_MS = 2 * 60 * 60 * 1000;
const pluginRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

const { values } = parseArgs({
  options: { workspace: { type: "string" }, port: { type: "string", default: "0" } },
});
const workspace = resolve(values.workspace ?? ".");
const port = Number(values.port);

if (!existsSync(join(workspace, MARKER))) {
  console.error(`error: ${workspace} is not a job-search-os workspace (no ${MARKER})`);
  process.exit(2);
}
if (!Number.isInteger(port) || port < 0 || port > 65535) {
  console.error(`error: --port must be 0-65535, got ${values.port}`);
  process.exit(2);
}

const srv = createServer({
  workspace,
  webRoot: join(pluginRoot, "dashboard", "web"),
  getPayload: async () =>
    derive(await runExport({ pluginRoot, workspace }), { stallDays: readStallDays(workspace), now: new Date() }),
  idleMs: IDLE_MS,
  onIdle: () => {
    console.log("job-search-os dashboard: idle for 2 hours, shutting down");
    void srv.close().then(() => process.exit(0));
  },
});

const shutdown = () => void srv.close().then(() => process.exit(0));
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

try {
  const actual = await srv.listen(port);
  console.log(`job-search-os dashboard: http://127.0.0.1:${actual}/`);
} catch (e) {
  console.error(`error: could not start the dashboard server: ${String(e)}`);
  process.exit(1);
}
