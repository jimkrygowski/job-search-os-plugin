import { test } from "node:test";
import assert from "node:assert/strict";
import { sourceClass } from "../web/src/theme.ts";

const SOURCES = ["A", "B", "C", "D", "E", "F", "G", "H", "I"];

test("sources take fixed slots by list position, up to the palette's 8", () => {
  assert.equal(sourceClass("A", SOURCES), "c-src-1");
  assert.equal(sourceClass("G", SOURCES), "c-src-7");
  assert.equal(sourceClass("H", SOURCES), "c-src-8");
});

test("a 9th source or one outside the list never gets a generated hue", () => {
  assert.equal(sourceClass("I", SOURCES), "c-unknown");
  assert.equal(sourceClass("Job Alert", SOURCES), "c-unknown");
  assert.equal(sourceClass("Unknown", SOURCES), "c-unknown");
});

test("every outcome has its own fixed class", async () => {
  const { endClass } = await import("../web/src/theme.ts");
  assert.equal(endClass("Passed"), "c-passed");
  assert.equal(endClass("Role Filled"), "c-filled");
  assert.equal(endClass("Rejected"), "c-rejected");
});
