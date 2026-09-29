import { test } from "node:test";
import assert from "node:assert/strict";
import { renderMarkdown } from "../web/src/markdown.ts";

test("script tags and raw HTML come out as text", () => {
  const html = renderMarkdown("Hi <script>alert('x')</script> and <img src=x onerror=alert(1)>");
  assert.doesNotMatch(html, /<script|<img/i);
  assert.match(html, /&lt;script&gt;/);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
});

test("javascript: and other non-web links are not linked", () => {
  for (const url of ["javascript:alert(1)", "JAVASCRIPT:alert(1)", "data:text/html,x", "vbscript:x", "//evil.example"]) {
    const html = renderMarkdown(`[click](${url})`);
    assert.doesNotMatch(html, /<a /, url);
    assert.match(html, /click/);
  }
});

test("attribute breakout in a link URL is escaped", () => {
  const html = renderMarkdown('[x](https://a.example/?q="><script>alert(1)</script>)');
  assert.doesNotMatch(html, /<script/);
  assert.doesNotMatch(html, /href="[^"]*"[^ >]/);
});

test("http, https and mailto links render safely", () => {
  const html = renderMarkdown("See [the recruiter](https://example.com/r?a=1&b=2) or [mail](mailto:a@b.co)");
  assert.match(html, /<a href="https:\/\/example\.com\/r\?a=1&amp;b=2" target="_blank" rel="noopener noreferrer">the recruiter<\/a>/);
  assert.match(html, /<a href="mailto:a@b\.co"/);
});

test("headings, lists, emphasis, inline code and code blocks", () => {
  const html = renderMarkdown([
    "# Title", "## Section", "", "- **Strong** on *design*", "- `code <b>`", "",
    "1. first", "2. second", "", "```", "<b>raw</b>", "```", "", "plain para",
  ].join("\n"));
  assert.match(html, /<h3>Title<\/h3>/);
  assert.match(html, /<h4>Section<\/h4>/);
  assert.match(html, /<ul><li><strong>Strong<\/strong> on <em>design<\/em><\/li><li><code>code &lt;b&gt;<\/code><\/li><\/ul>/);
  assert.match(html, /<ol><li>first<\/li><li>second<\/li><\/ol>/);
  assert.match(html, /<pre><code>&lt;b&gt;raw&lt;\/b&gt;<\/code><\/pre>/);
  assert.match(html, /<p>plain para<\/p>/);
});

test("emphasis markers inside code are left alone", () => {
  assert.match(renderMarkdown("`a*b*c`"), /<code>a\*b\*c<\/code>/);
});

test("unterminated code fence still escapes", () => {
  const html = renderMarkdown("```\n<script>x</script>");
  assert.doesNotMatch(html, /<script/);
});

test("link URLs may contain one level of balanced parentheses", () => {
  const html = renderMarkdown("[wiki](https://en.wikipedia.org/wiki/Foo_(bar)) and [bad](javascript:alert(1))");
  assert.match(html, /href="https:\/\/en\.wikipedia\.org\/wiki\/Foo_\(bar\)"/);
  assert.doesNotMatch(html, /\)\)|bad\)/);
});
