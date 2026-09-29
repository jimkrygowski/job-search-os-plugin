import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { cpSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { request } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { createServer } from "../server/http.ts";
import { ExportError, runExport } from "../server/exporter.ts";
import { readStallDays } from "../server/config.ts";
import type { Payload } from "../shared/types.ts";

const PLUGIN_ROOT = fileURLToPath(new URL("../../", import.meta.url));
const FIXTURE_WS = fileURLToPath(new URL("../fixtures/workspace", import.meta.url));

type Res = { status: number; body: string; headers: Record<string, string | string[] | undefined> };

function get(port: number, path: string, opts: { host?: string; method?: string } = {}): Promise<Res> {
  return new Promise((resolve, reject) => {
    const req = request({
      host: "127.0.0.1", port, path, method: opts.method ?? "GET",
      headers: { host: opts.host ?? `127.0.0.1:${port}` },
    }, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (c) => (body += c));
      res.on("end", () => resolve({ status: res.statusCode!, body, headers: res.headers }));
    });
    req.on("error", reject);
    req.end();
  });
}

let root: string;
let port: number;
let srv: ReturnType<typeof createServer>;
let payloadImpl: () => Promise<Payload>;

before(async () => {
  root = mkdtempSync(join(tmpdir(), "jso-http-"));
  const ws = join(root, "ws");
  mkdirSync(join(ws, "opportunity", "acme", "vp"), { recursive: true });
  writeFileSync(join(ws, "opportunity", "acme", "vp", "notes.md"), "# Acme notes\n");
  writeFileSync(join(ws, "secret.txt"), "workspace secret");
  const web = join(root, "web");
  mkdirSync(join(web, "dist", "web", "src"), { recursive: true });
  mkdirSync(join(web, "vendor"), { recursive: true });
  writeFileSync(join(web, "index.html"), "<!doctype html><title>t</title>");
  writeFileSync(join(web, "style.css"), "body{}");
  writeFileSync(join(web, "dist", "web", "src", "app.js"), "export {};");
  writeFileSync(join(web, "vendor", "d3.min.js"), "//d3");
  writeFileSync(join(root, "secret.txt"), "outside secret");
  payloadImpl = async () => ({ records: [], stages: [], outcomes: [], sources: [], stallDays: 21,
    warnings: [], generatedAt: "x", noHistory: false });
  srv = createServer({ workspace: ws, webRoot: web, getPayload: () => payloadImpl(), idleMs: 60_000 });
  port = await srv.listen(0);
});

after(async () => {
  await srv.close();
  rmSync(root, { recursive: true, force: true });
});

test("serves index, css, dist and vendor with security headers", async () => {
  const index = await get(port, "/");
  assert.equal(index.status, 200);
  assert.match(String(index.headers["content-type"]), /text\/html/);
  assert.match(String(index.headers["content-security-policy"]), /default-src 'self'/);
  assert.equal(index.headers["x-content-type-options"], "nosniff");
  assert.equal((await get(port, "/style.css")).status, 200);
  const js = await get(port, "/dist/web/src/app.js");
  assert.equal(js.status, 200);
  assert.match(String(js.headers["content-type"]), /javascript/);
  assert.equal((await get(port, "/vendor/d3.min.js")).status, 200);
});

test("localhost host header is accepted", async () => {
  assert.equal((await get(port, "/", { host: `localhost:${port}` })).status, 200);
});

test("foreign or missing-port Host header is refused", async () => {
  for (const host of ["evil.example", `evil.example:${port}`, "127.0.0.1", `127.0.0.1:${port + 1}`]) {
    assert.equal((await get(port, "/api/data", { host })).status, 403, host);
  }
});

test("only GET is allowed", async () => {
  for (const method of ["POST", "PUT", "DELETE"]) {
    assert.equal((await get(port, "/api/data", { method })).status, 405, method);
  }
});

test("no CORS headers", async () => {
  const r = await get(port, "/api/data");
  assert.equal(r.headers["access-control-allow-origin"], undefined);
});

test("api/data returns the payload as JSON", async () => {
  const r = await get(port, "/api/data");
  assert.equal(r.status, 200);
  assert.equal(JSON.parse(r.body).stallDays, 21);
  assert.equal(r.headers["cache-control"], "no-store");
});

test("api/data export failure is a 500 with detail", async () => {
  const prev = payloadImpl;
  payloadImpl = async () => { throw new ExportError("export failed", "Traceback: boom"); };
  try {
    const r = await get(port, "/api/data");
    assert.equal(r.status, 500);
    assert.deepEqual(JSON.parse(r.body), { error: "export failed", detail: "Traceback: boom" });
  } finally {
    payloadImpl = prev;
  }
});

test("notes endpoint serves notes.md as plain text", async () => {
  const r = await get(port, "/api/notes/acme/vp");
  assert.equal(r.status, 200);
  assert.equal(r.body, "# Acme notes\n");
  assert.match(String(r.headers["content-type"]), /text\/plain/);
  assert.equal((await get(port, "/api/notes/acme/cto")).status, 404);
});

test("notes endpoint rejects traversal and malformed slugs", async () => {
  for (const path of [
    "/api/notes/..%2F..%2Fsecret.txt", "/api/notes/acme/..", "/api/notes/acme/%2e%2e",
    "/api/notes/ACME/VP", "/api/notes/acme", "/api/notes/acme/vp/extra", "/api/notes/%E0%A4%A",
    "/api/notes/acme/vp%00",
  ]) {
    const r = await get(port, path);
    assert.ok(r.status === 400 || r.status === 404, `${path} -> ${r.status}`);
    assert.doesNotMatch(r.body, /secret/);
  }
});

test("static routes reject traversal", async () => {
  for (const path of [
    "/dist/../../secret.txt", "/dist/%2e%2e/%2e%2e/secret.txt", "/dist/..%2f..%2fsecret.txt",
    "/vendor/..%2F..%2Fsecret.txt", "/secret.txt", "/../secret.txt", "/dist/%E0%A4%A",
  ]) {
    const r = await get(port, path);
    assert.ok(r.status === 400 || r.status === 404, `${path} -> ${r.status}`);
    assert.doesNotMatch(r.body, /secret/);
  }
});

test("idle server calls onIdle after idleMs without requests", async () => {
  let fired = 0;
  const s = createServer({ workspace: root, webRoot: root, getPayload: () => payloadImpl(), idleMs: 80,
    onIdle: () => { fired += 1; } });
  const p = await s.listen(0);
  await new Promise((r) => setTimeout(r, 50));
  await get(p, "/api/data"); // resets the timer
  await new Promise((r) => setTimeout(r, 50));
  assert.equal(fired, 0);
  await new Promise((r) => setTimeout(r, 80));
  assert.equal(fired, 1);
  await s.close();
});

test("runExport reads the fixture through tracker.py", async () => {
  const ws = join(root, "fixture");
  cpSync(FIXTURE_WS, ws, { recursive: true });
  writeFileSync(join(ws, ".job-search-os.json"), '{"schema": 1}\n');
  const exp = await runExport({ pluginRoot: PLUGIN_ROOT, workspace: ws });
  assert.equal(exp.active.length + exp.closed.length, 30);
});

test("runExport failures become ExportError with detail", async () => {
  await assert.rejects(
    runExport({ pluginRoot: PLUGIN_ROOT, workspace: root,
      command: ["python3", "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"] }),
    (e: unknown) => e instanceof ExportError && /boom/.test(e.detail),
  );
  await assert.rejects(
    runExport({ pluginRoot: PLUGIN_ROOT, workspace: root, command: ["definitely-not-python3-xyz"] }),
    (e: unknown) => e instanceof ExportError && /definitely-not-python3-xyz/.test(e.detail),
  );
  await assert.rejects(
    runExport({ pluginRoot: PLUGIN_ROOT, workspace: root, command: ["python3", "-c", "print('not json')"] }),
    (e: unknown) => e instanceof ExportError,
  );
});

test("readStallDays: default, configured, and invalid values", () => {
  const ws = join(root, "cfg");
  mkdirSync(ws, { recursive: true });
  writeFileSync(join(ws, ".job-search-os.json"), '{"schema": 1}');
  assert.equal(readStallDays(ws), 21);
  writeFileSync(join(ws, ".job-search-os.json"), '{"schema": 1, "dashboard": {"stallDays": 30}}');
  assert.equal(readStallDays(ws), 30);
  for (const bad of ['{"dashboard": {"stallDays": -1}}', '{"dashboard": {"stallDays": "x"}}', "{oops"]) {
    writeFileSync(join(ws, ".job-search-os.json"), bad);
    assert.equal(readStallDays(ws), 21, bad);
  }
});

function runMain(args: string[]): Promise<{ code: number | null; out: string; err: string; kill: () => void; url?: string }> {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [fileURLToPath(new URL("../server/main.ts", import.meta.url)), ...args]);
    let out = "";
    let err = "";
    const done = (code: number | null, url?: string) =>
      resolve({ code, out, err, kill: () => child.kill("SIGTERM"), url });
    child.stdout.on("data", (c) => {
      out += c;
      const m = /http:\/\/127\.0\.0\.1:\d+\//.exec(out);
      if (m) done(null, m[0]);
    });
    child.stderr.on("data", (c) => (err += c));
    child.on("exit", (code) => done(code));
  });
}

test("main: refuses a folder that isn't a workspace", async () => {
  const r = await runMain(["--workspace", root]);
  assert.notEqual(r.code, 0);
  assert.match(r.err, /not a job-search-os workspace/);
});

test("main: serves the fixture end to end", async () => {
  const ws = join(root, "fixture-main");
  cpSync(FIXTURE_WS, ws, { recursive: true });
  writeFileSync(join(ws, ".job-search-os.json"), '{"schema": 1}\n');
  const r = await runMain(["--workspace", ws, "--port", "0"]);
  assert.ok(r.url, r.err);
  try {
    const p = Number(new URL(r.url!).port);
    const data = await get(p, "/api/data");
    assert.equal(data.status, 200);
    const payload = JSON.parse(data.body) as Payload;
    assert.equal(payload.records.length, 30);
    assert.equal((await get(p, "/")).status, 200);
  } finally {
    r.kill();
  }
});
