import { addDays, startOfWeek, startOfDay, dkey, sameDay, parse, fmtTime, fmt, esc, onDay } from './util.js';

export const colorOf = (state, e) => state.members.find(m => m.id === e.member_id)?.color
  || state.google?.calendars.find(c => c.id === e.calendar_id)?.color || 'var(--accent)';
const sortEv = (a, b) => (b.all_day - a.all_day) || a.start.localeCompare(b.start);
const dayEvents = (state, d) => state.events.filter(e => onDay(e, d)).sort(sortEv);

export function rangeFor(view, cursor) {
  if (view === 'day') { const s = startOfDay(cursor); return [s, addDays(s, 1)]; }
  if (view === 'week') { const s = startOfWeek(cursor); return [s, addDays(s, 7)]; }
  const s = startOfWeek(new Date(cursor.getFullYear(), cursor.getMonth(), 1));
  return [s, addDays(s, 42)];
}

export function rangeTitle(view, cursor) {
  if (view === 'day') return fmt(cursor, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
  if (view === 'month') return fmt(cursor, { month: 'long', year: 'numeric' });
  const s = startOfWeek(cursor), e = addDays(s, 6);
  const sameM = s.getMonth() === e.getMonth();
  return `${fmt(s, { month: 'short', day: 'numeric' })} – ${fmt(e, sameM ? { day: 'numeric' } : { month: 'short', day: 'numeric' })}, ${e.getFullYear()}`;
}

// Greedy lane assignment so overlapping events sit side by side.
function layout(items) {
  items.sort((x, y) => x.s - y.s || y.en - x.en);
  const out = []; let cluster = [], clusterEnd = -1;
  const flush = () => {
    const lanes = [];
    for (const it of cluster) {
      let l = lanes.findIndex(end => end <= it.s);
      if (l < 0) { l = lanes.length; lanes.push(0); }
      lanes[l] = it.en; it.lane = l;
    }
    cluster.forEach(it => { it.lanes = lanes.length; out.push(it); }); cluster = [];
  };
  for (const it of items) {
    if (cluster.length && it.s >= clusterEnd) { flush(); clusterEnd = -1; }
    cluster.push(it); clusterEnd = Math.max(clusterEnd, it.en);
  }
  flush(); return out;
}

const hourLabel = h => `${h % 12 || 12}${h < 12 ? 'am' : 'pm'}`;

function timedItems(state, d) {
  const ds = startOfDay(d), de = addDays(ds, 1), items = [];
  for (const e of state.events) {
    if (e.all_day || !onDay(e, d)) continue;
    const st = parse(e.start), en = parse(e.end);
    const s = (Math.max(st, ds) - ds) / 6e4, t = (Math.min(en, de) - ds) / 6e4;
    if (t <= s && st < ds) continue; // ends exactly at midnight: belongs to the previous day
    items.push({ e, s, en: Math.max(t, s + 30) });
  }
  return layout(items);
}

function grid(state, days) {
  const n = days.length, today = new Date(), nowMin = today.getHours() * 60 + today.getMinutes();
  const head = n > 1 ? `<div class="tg-row"><div></div>${days.map(d => `<div class="tg-hd ${sameDay(d, today) ? 'today' : ''}" data-day="${dkey(d)}">
      <span class="dn">${fmt(d, { weekday: 'short' })}</span> <span class="num">${d.getDate()}</span></div>`).join('')}</div>` : '';
  const allDay = days.map(d => state.events.filter(e => e.all_day && onDay(e, d)).sort(sortEv)
    .map(e => `<div class="ev allday" style="--c:${colorOf(state, e)}" data-event="${e.id}"><div class="ti">${esc(e.title)}</div></div>`).join(''));
  const hasAllDay = allDay.some(Boolean);
  const cols = days.map((d, i) => {
    const isToday = sameDay(d, today);
    const evs = timedItems(state, d).map(({ e, s, en, lane, lanes }) => {
      const tall = en - s >= 50;
      return `<div class="tg-ev" data-event="${e.id}" style="--c:${colorOf(state, e)};top:calc(var(--hh)*${(s / 60).toFixed(3)});
        height:calc(var(--hh)*${((en - s) / 60).toFixed(3)});left:${(lane / lanes * 100).toFixed(2)}%;width:${(100 / lanes).toFixed(2)}%">
        <div class="ti">${esc(e.title)}</div>${tall ? `<div class="t">${fmtTime(parse(e.start))}${e.location ? ' · ' + esc(e.location) : ''}</div>` : ''}</div>`;
    }).join('');
    return `<div class="tg-col ${isToday ? 'today' : ''}" data-slot="${dkey(d)}">${evs}${isToday ? `<div class="now" style="top:calc(var(--hh)*${(nowMin / 60).toFixed(3)})"></div>` : ''}</div>`;
  }).join('');
  const gut = Array.from({ length: 23 }, (_, i) => `<span style="top:calc(var(--hh)*${i + 1})">${hourLabel(i + 1)}</span>`).join('');
  return `<div class="tg" style="--n:${n}">${head}
    ${hasAllDay ? `<div class="tg-row tg-allday"><div class="gl">all-day</div>${allDay.map(h => `<div class="cx">${h}</div>`).join('')}</div>` : ''}
    <div class="tg-scroll"><div class="tg-body"><div class="tg-gut">${gut}</div>${cols}</div></div></div>`;
}

const week = state => grid(state, Array.from({ length: 7 }, (_, i) => addDays(startOfWeek(state.cursor), i)));
const day = state => grid(state, [startOfDay(state.cursor)]);

function month(state) {
  const [s] = rangeFor('month', state.cursor), today = new Date();
  let h = '<div class="month">';
  for (let i = 0; i < 7; i++) h += `<div class="mh">${fmt(addDays(s, i), { weekday: 'short' })}</div>`;
  for (let i = 0; i < 42; i++) {
    const d = addDays(s, i), evs = dayEvents(state, d), shown = evs.slice(0, 3);
    h += `<div class="cell ${d.getMonth() !== state.cursor.getMonth() ? 'other' : ''} ${sameDay(d, today) ? 'today' : ''}" data-day="${dkey(d)}">
      <div class="n">${d.getDate()}</div>
      ${shown.map(e => `<div class="chip" style="--c:${colorOf(state, e)}">${esc(e.title)}</div>`).join('')}
      ${evs.length > shown.length ? `<div class="more">+${evs.length - shown.length} more</div>` : ''}</div>`;
  }
  return h + '</div>';
}

export const renderView = state => ({ day, week, month })[state.view](state);
