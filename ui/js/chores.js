// Chores page, Skylight-style: one column per person for the chosen day (plus a shared "Everyone" column), a week strip
// to pick the day, big check cards grouped by time of day, and a progress ring on each person.
import { api } from './api.js';
import { addDays, dkey, esc, fmt, fmtTime, sameDay, startOfWeek, $ } from './util.js';
import { openSheet, closeSheet } from './modal.js';

const REPEAT = [['none', 'Never'], ['daily', 'Daily'], ['weekly', 'Weekly']];
const FAMILY = 'var(--family)';
const pad = n => String(n).padStart(2, '0');
const clock = t => fmtTime(new Date(`2000-01-01T${t}:00`));
const SECTIONS = ['Overdue', 'No date', 'Anytime', 'Morning', 'Afternoon', 'Evening'];

let app, actions, page, timer;
const st = { day: new Date(), chores: [], open: [] };  // chores = the whole week around st.day

const isToday = () => sameDay(st.day, new Date());
const weekOf = d => Array.from({ length: 7 }, (_, i) => addDays(startOfWeek(d), i));
const columns = () => [{ id: null, name: 'Everyone', color: FAMILY, icon: '👪' },
  ...app.members.map(m => ({ id: m.id, name: m.name, color: m.color, icon: [...m.name.trim()][0]?.toUpperCase() || '?' }))];

function sectionOf(c) {
  if (c.overdue) return 'Overdue';
  if (!c.day) return 'No date';
  if (!c.start_time) return 'Anytime';
  const h = +c.start_time.slice(0, 2);
  return h < 12 ? 'Morning' : h < 17 ? 'Afternoon' : 'Evening';
}

// What shows in a column: this day's chores, plus (so nothing gets lost) undated chores and, on today, overdue ones.
function itemsFor(col) {
  const mine = c => c.member_id === col.id;
  const day = st.chores.filter(c => c.day === dkey(st.day) && mine(c));
  const extra = st.open.filter(c => mine(c) && (!c.day || isToday())).map(c => ({ ...c, overdue: !!c.day }));
  return { day, all: [...extra, ...day] };
}

function card(c, col) {
  const sub = [c.start_time ? `${clock(c.start_time)}${c.end_time ? ' – ' + clock(c.end_time) : ''}` : '',
               c.repeat !== 'none' ? '🔁 ' + (c.repeat === 'daily' ? 'Daily' : 'Weekly') : '',
               c.overdue ? fmt(new Date(c.day + 'T12:00:00'), { month: 'short', day: 'numeric' }) : ''].filter(Boolean).join(' · ');
  return `<div class="cc ${c.done ? 'done' : ''} ${c.overdue ? 'late' : ''}" data-chore="${c.id}" data-day="${c.day || ''}" style="--c:${col.color}">
    <button class="cc-chk" data-check aria-label="${c.done ? 'Mark not done' : 'Mark done'}">${c.done ? '✓' : ''}</button>
    <div class="cc-b"><div class="ti">${esc(c.title)}</div>${sub ? `<div class="sub">${sub}</div>` : ''}</div></div>`;
}

function column(col) {
  const { day, all } = itemsFor(col), done = day.filter(c => c.done).length, total = day.length;
  const pct = total ? Math.round(done / total * 100) : 0, allDone = total > 0 && done === total;
  const sorted = [...all].sort((a, b) => (a.start_time || '').localeCompare(b.start_time || '') || a.id - b.id);
  const body = SECTIONS.map(s => {
    const list = sorted.filter(c => sectionOf(c) === s);
    return list.length ? `<div class="cs">${s}</div>${list.map(c => card(c, col)).join('')}` : '';
  }).join('');
  return `<section class="col" style="--c:${col.color}">
    <header class="ch"><div class="ring ${allDone ? 'full' : ''}" style="--p:${pct}"><span class="av big ${col.id == null ? 'fam' : ''}" style="--c:${col.color}">${col.icon}</span></div>
      <div class="nm">${esc(col.name)}</div>
      <div class="pr ${allDone ? 'ok' : ''}">${total ? (allDone ? 'All done! 🎉' : `${done} of ${total} done`) : 'Nothing planned'}</div></header>
    <div class="cl">${body || '<div class="none">Nothing for this day</div>'}
      <button class="cc-add" data-addfor="${col.id ?? ''}">+ Add chore</button></div></section>`;
}

function draw() {
  const old = $('.cb', page)?.scrollTop, days = weekOf(st.day), today = new Date();
  $('.cp-title', page).textContent = fmt(st.day, { weekday: 'long' });
  $('.cp-date', page).textContent = fmt(st.day, { month: 'long', day: 'numeric', year: 'numeric' });
  $('.cp-days', page).innerHTML = `<button data-wk="-1" aria-label="Previous week">‹</button>${days.map(d => {
    const left = st.chores.filter(c => c.day === dkey(d) && !c.done).length;
    return `<button class="dchip ${sameDay(d, st.day) ? 'on' : ''} ${sameDay(d, today) ? 'today' : ''}" data-pick="${dkey(d)}">
      <span class="dn">${fmt(d, { weekday: 'short' })}</span><span class="num">${d.getDate()}</span>${left ? `<i class="cnt">${left}</i>` : ''}</button>`;
  }).join('')}<button data-wk="1" aria-label="Next week">›</button>`;
  const cb = $('.cb', page);
  cb.innerHTML = columns().map(column).join('');
  cb.style.setProperty('--cols', columns().length);
  if (old != null) cb.scrollTop = old;
}

async function load() {
  const s = startOfWeek(st.day);
  try { [st.chores, st.open] = await Promise.all([api.chores(dkey(s), dkey(addDays(s, 7))), api.openChores()]); } catch (err) { console.error(err); }
  if (!page.hidden) draw();
}

const find = (id, day) => [...st.chores, ...st.open].find(c => c.id === id && (c.day || '') === day);

const pills = (name, opts, sel) => `<div class="pills">${opts.map(([v, l, c]) =>
  `<button class="pill ${String(sel) === String(v) ? 'on' : ''}" ${c ? `style="--c:${c}"` : ''} data-pill="${name}" data-v="${v}">${l}</button>`).join('')}</div>`;

function openForm(chore, preset = {}) {
  const f = chore
    ? { title: chore.title, member_id: chore.member_id, due: chore.due, allDay: !chore.start_time, st: chore.start_time || '09:00',
        et: chore.end_time || '09:30', repeat: chore.repeat }
    : { title: '', member_id: preset.memberId ?? null, due: dkey(st.day), allDay: true, st: '09:00', et: '09:30', repeat: 'none' };
  f.newPerson = false; f.personName = '';
  const sheet = openSheet({ title: chore ? 'Edit chore' : 'New chore' });
  const render = () => {
    sheet.body.innerHTML = `
      <div class="f"><label>What needs doing?</label><input id="c-title" value="${esc(f.title)}" placeholder="e.g. Empty dishwasher" maxlength="200"></div>
      <div class="f"><label>Who</label>${pills('who', [['', '👪 Everyone', FAMILY],
        ...app.members.map(m => [m.id, `<span class="dot" style="--c:${m.color}"></span>${esc(m.name)}`, m.color]), ['new', '+ New person']],
        f.newPerson ? 'new' : (f.member_id ?? ''))}
        ${f.newPerson ? `<input id="c-person" style="margin-top:.5rem" placeholder="Name" value="${esc(f.personName)}" maxlength="40">` : ''}</div>
      <div class="row"><div class="f"><label>${f.repeat !== 'none' ? 'Starts' : 'Date'}</label><input id="c-date" type="date" value="${f.due || ''}"></div>
        <div class="f"><label>&nbsp;</label><button class="pill ${f.allDay ? 'on' : ''}" data-allday style="width:100%">${f.allDay ? '✓ ' : ''}All day</button></div></div>
      ${f.allDay ? '' : `<div class="row"><div class="f"><label>From</label><input id="c-st" type="time" value="${f.st}"></div>
        <div class="f"><label>To</label><input id="c-et" type="time" value="${f.et}"></div></div>`}
      <div class="f"><label>Repeat</label>${pills('repeat', REPEAT, f.repeat)}</div>
      <div id="c-err" class="stale"></div>`;
  };
  render();
  sheet.setFoot(`${chore ? `<button class="danger" data-del>${chore.repeat !== 'none' ? 'Delete all repeats' : 'Delete'}</button>` : ''}<span class="spacer"></span>
    <button data-close>Cancel</button><button class="primary" data-save>Save</button>`);
  const map = { 'c-title': 'title', 'c-person': 'personName', 'c-date': 'due', 'c-st': 'st', 'c-et': 'et' };
  sheet.body.oninput = e => { const k = map[e.target.id]; if (k) f[k] = e.target.value; };
  sheet.body.onclick = e => {
    if (e.target.closest('[data-allday]')) { f.allDay = !f.allDay; return render(); }
    const p = e.target.closest('[data-pill]'); if (!p) return;
    const v = p.dataset.v;
    if (p.dataset.pill === 'who') { f.newPerson = v === 'new'; f.member_id = v === '' || v === 'new' ? null : +v; }
    if (p.dataset.pill === 'repeat') f.repeat = v;
    render();
  };
  sheet.foot.onclick = async e => {
    const err = m => { $('#c-err', sheet.body).textContent = m; };
    if (e.target.closest('[data-del]')) { await api.deleteChore(chore.id); closeSheet(); return load(); }
    if (!e.target.closest('[data-save]')) return;
    if (!f.title.trim()) return err('Please enter a title.');
    if (!f.due) return err('Please pick a date.');
    if (!f.allDay && f.et <= f.st) return err('End must be after the start.');
    try {
      let mid = f.member_id;
      if (f.newPerson) {
        if (!f.personName.trim()) return err('Please enter a name.');
        const m = await api.addMember(f.personName.trim()); app.members.push(m); mid = m.id;
      }
      await api.saveChore({ title: f.title.trim(), member_id: mid, due: f.due, start_time: f.allDay ? null : f.st,
                            end_time: f.allDay ? null : f.et, repeat: f.repeat }, chore?.id);
      closeSheet(); load();
    } catch (ex) { err(String(ex.message).slice(0, 120)); }
  };
}

function close() {
  page.hidden = true; clearInterval(timer);
  history.replaceState(null, '', location.pathname + location.search);
  actions.refreshChores();
}

function build() {
  page = document.createElement('section');
  page.id = 'chore-page'; page.hidden = true;
  page.innerHTML = `
    <header class="cp-top">
      <button data-back>‹ Calendar</button>
      <div class="cp-h"><h2 class="cp-title"></h2><div class="cp-date"></div></div><div class="spacer"></div>
      <button data-today>Today</button>
      <button class="primary" data-add aria-label="Add chore">+</button>
    </header>
    <nav class="cp-days"></nav>
    <main class="cb"></main>`;
  document.body.append(page);
  page.onclick = async e => {
    const t = e.target;
    if (t.closest('[data-back]')) return close();
    if (t.closest('[data-today]')) { const wk = dkey(startOfWeek(st.day)); st.day = new Date(); return dkey(startOfWeek(st.day)) === wk ? draw() : load(); }
    if (t.closest('[data-add]')) return openForm(null);
    const wk = t.closest('[data-wk]'); if (wk) { st.day = addDays(st.day, 7 * +wk.dataset.wk); return load(); }
    const pick = t.closest('[data-pick]'); if (pick) { st.day = new Date(pick.dataset.pick + 'T12:00:00'); return draw(); }
    const add = t.closest('[data-addfor]'); if (add) return openForm(null, { memberId: add.dataset.addfor === '' ? null : +add.dataset.addfor });
    const el = t.closest('[data-chore]');
    if (el) {
      const id = +el.dataset.chore, day = el.dataset.day;
      if (t.closest('[data-check]')) {
        try { await api.setDone(id, !el.classList.contains('done'), day || null); } catch (err) { console.error(err); }
        return load();
      }
      const c = find(id, day); if (c) openForm(c);
    }
  };
}

export async function openChores(state, acts) {
  app = state; actions = acts;
  if (!page) build();
  page.hidden = false;
  history.replaceState(null, '', location.pathname + location.search + '#chores');
  st.day = new Date();
  await load();
  clearInterval(timer); timer = setInterval(() => { if (!$('#overlay').classList.contains('open')) load(); }, 60_000);
}
