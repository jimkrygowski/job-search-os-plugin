// A deliberately small markdown renderer for notes.md. Notes can contain
// pasted job descriptions and emails, so everything is HTML-escaped FIRST
// and only a fixed set of tags is ever produced. Raw HTML never survives.
// No DOM use here, so node --test can cover it.
function escapeHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
const SAFE_URL = /^(https?:\/\/|mailto:)/i;
function inline(raw) {
    const code = [];
    let s = escapeHtml(raw);
    // Code spans first, so emphasis/link syntax inside them is left alone.
    s = s.replace(/`([^`]+)`/g, (_, c) => {
        code.push(`<code>${c}</code>`);
        return `\u0000${code.length - 1}\u0000`;
    });
    s = s.replace(/\[([^\]]+)\]\(((?:[^()\s]|\([^()\s]*\))+)\)/g, (m, text, url) => SAFE_URL.test(url)
        ? `<a href="${url}" target="_blank" rel="noopener noreferrer">${text}</a>`
        : text);
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/\*([^*\s][^*]*)\*/g, "<em>$1</em>");
    return s.replace(/\u0000(\d+)\u0000/g, (_, i) => code[Number(i)]);
}
export function renderMarkdown(source) {
    const lines = source.replace(/\u0000/g, "").replace(/\r\n?/g, "\n").split("\n");
    const out = [];
    let para = [];
    let list = null;
    const flush = () => {
        if (para.length)
            out.push(`<p>${para.map(inline).join("<br>")}</p>`);
        para = [];
        if (list)
            out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`);
        list = null;
    };
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        if (/^```/.test(line)) {
            flush();
            const body = [];
            for (i++; i < lines.length && !/^```/.test(lines[i]); i++)
                body.push(lines[i]);
            out.push(`<pre><code>${escapeHtml(body.join("\n"))}</code></pre>`);
            continue;
        }
        const heading = /^(#{1,6})\s+(.*)$/.exec(line);
        if (heading) {
            flush();
            const level = Math.min(heading[1].length + 2, 6);
            out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
            continue;
        }
        const item = /^\s*(?:([-*+])|(\d+)[.)])\s+(.*)$/.exec(line);
        if (item) {
            const tag = item[1] ? "ul" : "ol";
            if (para.length || (list && list.tag !== tag))
                flush();
            list ??= { tag, items: [] };
            list.items.push(item[3]);
            continue;
        }
        if (!line.trim()) {
            flush();
            continue;
        }
        if (list)
            flush();
        para.push(line);
    }
    flush();
    return out.join("\n");
}
