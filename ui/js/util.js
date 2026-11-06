// Date + DOM helpers. All times are naive local time ("YYYY-MM-DDTHH:MM:SS").
const p2 = n => String(n).padStart(2, '0');
export const dkey = d => `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`;
export const iso = (d) => `${dkey(d)}T${p2(d.getHours())}:${p2(d.getMinutes())}:00`;
export const parse = s => new Date(s.length === 10 ? s + 'T00:00:00' : s);
export const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
export const startOfDay = d => new Date(d.getFullYear(), d.getMonth(), d.getDate());
export const startOfWeek = d => addDays(startOfDay(d), -d.getDay()); // Sunday-first
export const sameDay = (a, b) => dkey(a) === dkey(b);
export const fmtTime = d => d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).replace(' ', '').toLowerCase();
export const fmt = (d, o) => d.toLocaleDateString([], o);
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const $ = (sel, root = document) => root.querySelector(sel);

// Does event e touch calendar day `d`?
export function onDay(e, d) {
  const k = dkey(d);
  return dkey(parse(e.start)) <= k && k <= dkey(parse(e.end));
}
