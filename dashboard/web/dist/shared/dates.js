// Calendar helpers shared by the server and the browser. Timestamps are
// tracker.py's local ISO strings ("2026-09-28" or "2026-09-28T10:00:00");
// only the date part matters here.
function utcDay(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
    return m ? Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
}
/** Whole days from `from` to `to` (both ISO date or date-time strings). */
export function daysBetween(from, to) {
    const a = utcDay(from);
    const b = utcDay(to);
    return a === null || b === null ? null : Math.round((b - a) / 86_400_000);
}
export function localIsoDate(d) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
/** Whole days from an ISO date to `now`'s local calendar date. */
export function daysSince(iso, now) {
    return daysBetween(iso, localIsoDate(now));
}
/** ISO-8601 week label, e.g. "2026-W01". */
export function isoWeek(iso) {
    const day = utcDay(iso);
    if (day === null)
        return "";
    const d = new Date(day);
    const weekday = d.getUTCDay() || 7; // Mon=1..Sun=7
    d.setUTCDate(d.getUTCDate() + 4 - weekday); // Thursday of this week
    const year = d.getUTCFullYear();
    const week = Math.ceil(((d.getTime() - Date.UTC(year, 0, 1)) / 86_400_000 + 1) / 7);
    return `${year}-W${String(week).padStart(2, "0")}`;
}
/** Monday (UTC ms) of an ISO week label. */
export function weekStart(label) {
    const [y, w] = label.split("-W").map(Number);
    const jan4 = new Date(Date.UTC(y, 0, 4));
    const monday1 = Date.UTC(y, 0, 4) - ((jan4.getUTCDay() || 7) - 1) * 86_400_000;
    return monday1 + (w - 1) * 7 * 86_400_000;
}
