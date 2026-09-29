// Reads tracker state the only way the dashboard is allowed to: by asking
// tracker.py for its JSON export.
import { execFile } from "node:child_process";
import { join } from "node:path";
import type { Export } from "../shared/types.ts";

export class ExportError extends Error {
  detail: string;
  constructor(message: string, detail: string) {
    super(message);
    this.detail = detail;
  }
}

export function runExport(opts: { pluginRoot: string; workspace: string; command?: string[] }): Promise<Export> {
  const [cmd, ...args] = opts.command ?? ["python3", join(opts.pluginRoot, "tools", "tracker.py"), "export", "--json"];
  return new Promise((resolve, reject) => {
    execFile(cmd!, args, { cwd: opts.workspace, timeout: 30_000, maxBuffer: 64 * 1024 * 1024 },
      (err, stdout, stderr) => {
        if (err) {
          const detail = (stderr || "").trim() || `${cmd}: ${err.message}`;
          reject(new ExportError("tracker export failed", detail));
          return;
        }
        try {
          resolve(JSON.parse(stdout) as Export);
        } catch (e) {
          reject(new ExportError("tracker export returned invalid JSON", String(e)));
        }
      });
  });
}
