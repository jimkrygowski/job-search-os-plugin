// Read-only HTTP server for the dashboard. Localhost only, GET only, no
// CORS, and every path it serves is checked to stay inside its root.
import { createReadStream, realpathSync, statSync } from "node:fs";
import { createServer as createHttpServer, type IncomingMessage, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";
import { extname, join, resolve, sep } from "node:path";
import { ExportError } from "./exporter.ts";
import type { Payload } from "../shared/types.ts";

const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
};

const SECURITY_HEADERS = {
  "Content-Security-Policy":
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; " +
    "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "Cross-Origin-Resource-Policy": "same-origin",
};

const SLUG = /^[a-z0-9_]+\/[a-z0-9_]+$/;
// Static files the page may load; anything else under webRoot is not served.
const STATIC_PREFIXES = ["dist/", "vendor/"];
const STATIC_FILES = ["index.html", "style.css"];

export type ServerOptions = {
  workspace: string;
  webRoot: string;
  getPayload: () => Promise<Payload>;
  idleMs: number;
  onIdle?: () => void;
};

/** Resolves `rel` under `root`, following symlinks, or null if it escapes
 * or isn't a regular file. */
function containedFile(root: string, rel: string): string | null {
  try {
    const realRoot = realpathSync(root);
    const real = realpathSync(resolve(realRoot, rel));
    if (!real.startsWith(realRoot + sep)) return null;
    return statSync(real).isFile() ? real : null;
  } catch {
    return null;
  }
}

function send(res: ServerResponse, status: number, body: string, type = TYPES[".txt"]!, extra: Record<string, string> = {}) {
  res.writeHead(status, { ...SECURITY_HEADERS, "Content-Type": type, ...extra });
  res.end(body);
}

function sendFile(res: ServerResponse, file: string, type?: string) {
  res.writeHead(200, {
    ...SECURITY_HEADERS,
    "Content-Type": type ?? TYPES[extname(file)] ?? "application/octet-stream",
    "Cache-Control": "no-cache",
  });
  createReadStream(file).pipe(res);
}

export function createServer(opts: ServerOptions) {
  let port = 0;
  let idleTimer: NodeJS.Timeout | undefined;
  const armIdle = () => {
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => opts.onIdle?.(), opts.idleMs);
    idleTimer.unref();
  };

  async function handle(req: IncomingMessage, res: ServerResponse) {
    armIdle();
    const host = req.headers.host ?? "";
    if (host !== `127.0.0.1:${port}` && host !== `localhost:${port}`) {
      return send(res, 403, "Forbidden: unexpected Host header");
    }
    if (req.method !== "GET") {
      return send(res, 405, "Method Not Allowed", undefined, { Allow: "GET" });
    }
    const pathname = new URL(req.url ?? "/", "http://localhost").pathname;
    let decoded: string;
    try {
      decoded = decodeURIComponent(pathname);
    } catch {
      return send(res, 400, "Bad Request");
    }
    if (decoded.includes("\0")) return send(res, 400, "Bad Request");

    if (decoded === "/api/data") {
      try {
        const payload = await opts.getPayload();
        return send(res, 200, JSON.stringify(payload), "application/json; charset=utf-8", { "Cache-Control": "no-store" });
      } catch (e) {
        const body = e instanceof ExportError
          ? { error: e.message, detail: e.detail }
          : { error: "dashboard error", detail: String(e) };
        return send(res, 500, JSON.stringify(body), "application/json; charset=utf-8", { "Cache-Control": "no-store" });
      }
    }

    if (decoded.startsWith("/api/notes/")) {
      const slug = decoded.slice("/api/notes/".length);
      if (!SLUG.test(slug)) return send(res, 400, "Bad Request: invalid opportunity slug");
      const file = containedFile(join(opts.workspace, "opportunity"), join(slug, "notes.md"));
      if (!file) return send(res, 404, "No notes.md for this opportunity");
      return sendFile(res, file, TYPES[".txt"]);
    }

    const rel = decoded === "/" ? "index.html" : decoded.slice(1);
    if (STATIC_FILES.includes(rel) || STATIC_PREFIXES.some((p) => rel.startsWith(p))) {
      const file = containedFile(opts.webRoot, rel);
      if (file) return sendFile(res, file);
    }
    return send(res, 404, "Not Found");
  }

  const server = createHttpServer((req, res) => {
    handle(req, res).catch((e) => {
      if (!res.headersSent) send(res, 500, `Internal error: ${String(e)}`);
      else res.destroy();
    });
  });

  return {
    server,
    listen(requested: number): Promise<number> {
      return new Promise((resolveListen, reject) => {
        server.once("error", reject);
        server.listen(requested, "127.0.0.1", () => {
          port = (server.address() as AddressInfo).port;
          armIdle();
          resolveListen(port);
        });
      });
    },
    close(): Promise<void> {
      clearTimeout(idleTimer);
      server.closeAllConnections();
      return new Promise((r) => server.close(() => r()));
    },
  };
}
