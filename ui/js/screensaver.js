// Screensaver ("ambient mode") for the wall display. After a few idle minutes it shows a calm full-screen dashboard:
// a big clock on the left and, on the right, highlight cards that cross-fade every few seconds (up next, chores, the week,
// the forecast). If there are photos (see backend/skybolt/photos.py) it alternates with a full-screen photo slideshow.
// Tap anywhere to close it and land on today's calendar. Plain JS and CSS, no dependencies, only gentle fades.
// Active only when the page is loaded from the Pi itself; ?ss=1 forces it on, ?ss=0 off. Open it now with ?open=screensaver.
// Test knobs: ?ssmode=dashboard|photos|both, ?ssrotate=ms (per card), ?ssphoto=ms (per photo), ?ssperround=n, ?sscard=n.
import { api } from './api.js';
import { addDays, dkey, esc, fmt, fmtTime, iso, onDay, parse, sameDay, startOfDay } from './util.js';
import { colorOf } from './views.js';
import { icon, label } from './weather.js';

const q = new URLSearchParams(location.search);
export const available = q.get('ss') === '1' || (q.get('ss') !== '0' && ['127.0.0.1', 'localhost', '[::1]'].includes(location.hostname));
export const getMinutes = () => { try { const v = localStorage.getItem('ssMinutes'); return v == null ? 5 : +v; } catch { return 5; } };  // 0 = off
export const setMinutes = m => { try { localStorage.setItem('ssMinutes', m); } catch { /* private mode: keep the default */ } };

export const getMode = () => {  // what to show: the dashboard, the photos, or both in turn
  const m = q.get('ssmode');
  if (['both', 'dashboard', 'photos'].includes(m)) return m;
  try { return localStorage.getItem('ssMode') || 'both'; } catch { return 'both'; }
};
export const setMode = m => { try { localStorage.setItem('ssMode', m); } catch { /* keep the default */ } };
export const getPhotoSeconds = () => { try { return +localStorage.getItem('ssPhotoSec') || 12; } catch { return 12; } };
export const setPhotoSeconds = n => { try { localStorage.setItem('ssPhotoSec', n); } catch { /* keep the default */ } };

const ROTATE_MS = +q.get('ssrotate') || 12_000;  // time on each card
const photoMs = () => +q.get('ssphoto') || getPhotoSeconds() * 1000;
const PER_ROUND = +q.get('ssperround') || 6;     // photos shown before going back to the dashboard (mode "both")
const REFRESH_MS = 60_000, DRIFT_MS = 45_000;
const FAMILY = 'var(--family)';

let cfg, el, visible = false, preview = false, idx = 0, fadeTimer = 0, freeTimer = 0;
let data = { events: [], chores: [], open: [] };
let photoIds = [], queue = [], qi = 0, active = 0, phaseName = 'dash', cardsShown = 0, photosShown = 0, stepTimer = 0;
const timers = [];

const hour = () => new Date().getHours();
const phase = h => (h >= 5 && h < 8) ? 'dawn' : (h >= 8 && h < 17) ? 'day' : (h >= 17 && h < 20) ? 'dusk' : 'night';
const greeting = h => h < 5 ? 'Good night' : h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : h < 22 ? 'Good evening' : 'Good night';
const plural = (n, one, many = one + 's') => `${n} ${n === 1 ? one : many}`;
const sortEv = (a, b) => (b.all_day - a.all_day) || a.start.localeCompare(b.start);

function columns() {
  return [{ id: null, name: 'Everyone', color: FAMILY, icon: '👪' },
    ...cfg.state.members.map(m => ({ id: m.id, name: m.name, color: m.color, icon: [...m.name.trim()][0]?.toUpperCase() || '?' }))];
}

// ---- data ---------------------------------------------------------------------------------------------------------
function todayEvents(now) { return data.events.filter(e => onDay(e, now) && (e.all_day || parse(e.end) > now)).sort(sortEv); }
const choresToday = () => data.chores.filter(c => c.day === dkey(new Date()));

export const photoCount = () => photoIds.length;
export async function refreshPhotos() {
  try { photoIds = await api.photos(); } catch { /* keep the last list */ }
  return photoIds.length;
}

async function load() {
  refreshPhotos();
  const t = startOfDay(new Date());
  try {
    const [events, chores, open] = await Promise.all([api.events(iso(t), iso(addDays(t, 8))), api.chores(dkey(t), dkey(addDays(t, 1))), api.openChores()]);
    data = { events, chores, open };
  } catch (err) { console.error(err); }  // keep what we had
  if (visible) { paintLeft(); paintCard(false); }
}

// ---- cards (each returns { title, meta, html } or null to be skipped) ----------------------------------------------
function agendaCard() {
  const now = new Date(), tom = addDays(now, 1);
  const today = todayEvents(now), tomorrow = data.events.filter(e => onDay(e, tom)).sort(sortEv);
  const shownToday = today.slice(0, 5), shownTom = tomorrow.slice(0, 5 - shownToday.length);
  const row = e => {
    const live = !e.all_day && parse(e.start) <= now;
    const when = e.all_day ? 'All day' : live ? 'Now' : fmtTime(parse(e.start));
    const sub = [e.all_day || e.end === e.start ? '' : `${fmtTime(parse(e.start))} – ${fmtTime(parse(e.end))}`, e.location].filter(Boolean).join(' · ');
    return `<div class="ss-ev" style="--c:${colorOf(cfg.state, e)}"><div class="ss-when ${live ? 'live' : ''}">${when}</div><i class="bar"></i>
      <div class="ss-what"><b>${esc(e.title)}</b>${sub ? `<small>${esc(sub)}</small>` : ''}</div></div>`;
  };
  let html = '';
  if (shownToday.length) html += `<div class="ss-day">Today</div>${shownToday.map(row).join('')}`;
  if (shownTom.length) html += `<div class="ss-day">Tomorrow</div>${shownTom.map(row).join('')}`;
  if (!html) html = '<div class="ss-empty"><span>🌿</span>Nothing on the calendar<br>for today or tomorrow</div>';
  return { title: 'Up next', meta: fmt(now, { weekday: 'long' }), html };
}

function choresCard() {
  const cols = columns().map(c => {
    const mine = x => x.member_id === c.id, today = choresToday().filter(mine), done = today.filter(x => x.done).length;
    const pending = [...data.open.filter(mine), ...today.filter(x => !x.done)];
    return { ...c, total: today.length, done, pending, pct: today.length ? Math.round(done / today.length * 100) : 0 };
  }).filter(c => c.total || c.pending.length);
  if (!cols.length) return null;
  const left = cols.reduce((n, c) => n + c.pending.length, 0);
  const body = cols.map(c => {
    const all = c.total > 0 && c.done === c.total;
    return `<div class="ss-pc"><div class="ring ${all ? 'full' : ''}" style="--c:${c.color};--p:${c.pct}"><span class="av big ${c.id == null ? 'fam' : ''}" style="--c:${c.color}">${c.icon}</span></div>
      <div class="nm">${esc(c.name)}</div><div class="pr ${all ? 'ok' : ''}">${all ? 'All done 🎉' : c.total ? `${c.done} of ${c.total}` : 'To do'}</div>
      <div class="ss-pend">${c.pending.slice(0, 3).map(x => esc(x.title)).join('<br>')}${c.pending.length > 3 ? `<br>+${c.pending.length - 3} more` : ''}</div></div>`;
  }).join('');
  return { title: 'Chores', meta: left ? `${left} to do` : 'All done 🎉', html: `<div class="ss-pcols">${body}</div>` };
}

function weekCard() {
  const now = startOfDay(new Date()), days = Array.from({ length: 7 }, (_, i) => addDays(now, i));
  const per = days.map(d => data.events.filter(e => onDay(e, d)));
  const tiles = days.map((d, i) => {
    const dots = per[i].slice(0, 4).map(e => `<i style="--c:${colorOf(cfg.state, e)}"></i>`).join('');
    return `<div class="ss-d ${i === 0 ? 'today' : ''}"><span>${i === 0 ? 'Today' : fmt(d, { weekday: 'short' })}</span><b>${d.getDate()}</b>
      <div class="ss-dots-row">${dots || '<em></em>'}</div><small>${per[i].length ? plural(per[i].length, 'event') : '&nbsp;'}</small></div>`;
  }).join('');
  const specials = [];
  days.forEach(d => data.events.filter(e => e.all_day && dkey(parse(e.start)) === dkey(d)).forEach(e => specials.push({ d, e })));
  const busiest = per.reduce((b, l, i) => (l.length > per[b].length ? i : b), 0);
  const foot = specials.length
    ? specials.slice(0, 3).map(({ d, e }) => `<div class="ss-sp"><span>${e.repeat === 'yearly' ? '🎂' : '📌'}</span><b>${esc(e.title)}</b><small>${sameDay(d, now) ? 'Today' : fmt(d, { weekday: 'long' })}</small></div>`).join('')
    : per[busiest].length ? `<div class="ss-sp"><span>📈</span><b>Busiest day</b><small>${fmt(days[busiest], { weekday: 'long' })} · ${plural(per[busiest].length, 'event')}</small></div>`
    : '<div class="ss-empty"><span>🌿</span>A quiet week ahead</div>';
  return { title: 'Your week', meta: `${fmt(days[0], { month: 'short', day: 'numeric' })} – ${fmt(days[6], { month: 'short', day: 'numeric' })}`,
           html: `<div class="ss-days">${tiles}</div><div class="ss-foot">${foot}</div>` };
}

function forecastCard() {
  const w = cfg.state.weather;
  if (!w) return null;
  const c = w.current, u = w.units, d0 = w.daily[0];
  const tiles = w.daily.slice(0, 5).map((d, i) => `<div class="ss-d"><span>${i === 0 ? 'Today' : fmt(parse(d.date), { weekday: 'short' })}</span>
    <div class="ss-wi">${icon(d.code)}</div><b>${d.high}°</b><small>${d.low}°${d.precip > 0 ? ` · 💧${d.precip}%` : ''}</small></div>`).join('');
  return { title: 'Forecast', meta: esc(w.location), html: `
    <div class="ss-now"><div class="ss-big">${icon(c.code, c.is_day)}</div><div><b>${c.temp}${u.temp}</b><span>${esc(label(c.code))}</span>
      <small>Feels like ${c.feels_like}° · Humidity ${c.humidity}% · Wind ${c.wind} ${u.wind}</small>
      <small>☀️ ${fmtTime(parse(d0.sunrise))} &nbsp;🌇 ${fmtTime(parse(d0.sunset))}</small></div></div>
    <div class="ss-days five">${tiles}</div>` };
}

const cards = () => [agendaCard(), choresCard(), weekCard(), forecastCard()].filter(Boolean);

// ---- painting ------------------------------------------------------------------------------------------------------
function paintLeft() {
  const now = new Date(), h = now.getHours();
  const parts = new Intl.DateTimeFormat([], { hour: 'numeric', minute: '2-digit' }).formatToParts(now);
  const get = t => parts.find(p => p.type === t)?.value || '';
  el.querySelector('.ss-time').innerHTML = `${get('hour')}<span class="colon">:</span>${get('minute')}${get('dayPeriod') ? `<small>${get('dayPeriod')}</small>` : ''}`;
  el.querySelector('.ss-date').textContent = fmt(now, { weekday: 'long', month: 'long', day: 'numeric' });
  const ev = todayEvents(now).length, ch = choresToday().filter(c => !c.done).length + data.open.length;
  el.querySelector('.ss-greet').innerHTML = `<b>${greeting(h)}</b>${ev || ch ? `<br>${[ev ? plural(ev, 'event') + ' left today' : '', ch ? plural(ch, 'chore') + ' to do' : ''].filter(Boolean).join(' · ')}` : '<br>All clear today 🎉'}`;
  const w = cfg.state.weather;
  el.querySelector('.ss-wx').innerHTML = w ? `<span>${icon(w.current.code, w.current.is_day)}</span><b>${w.current.temp}°</b>
    <small>${esc(label(w.current.code))}<br>H ${w.daily[0].high}° · L ${w.daily[0].low}°</small>` : '';
  el.className = `open ${phase(h)} ${h >= 22 || h < 6 ? 'late' : ''} ${phaseName === 'photo' ? 'photo' : ''}`;  // sky colour by time of day, dimmer late at night
  paintPill(now);
}

function paintCard(fade) {
  const list = cards(), at = idx % list.length;  // idx keeps counting; the list can grow once data arrives
  const c = list[at], slot = el.querySelector('.ss-slot');
  const draw = () => {
    slot.innerHTML = `<div class="ss-card"><div class="ss-h"><span>${c.title}</span><span>${c.meta}</span></div><div class="ss-body">${c.html}</div></div>`;
    requestAnimationFrame(() => slot.firstElementChild?.classList.add('on'));
  };
  el.querySelector('.ss-pager').innerHTML = list.map((_, i) => `<i class="${i === at ? 'on' : ''}"></i>`).join('');
  clearTimeout(fadeTimer);
  if (fade && slot.firstElementChild) { slot.firstElementChild.classList.remove('on'); fadeTimer = setTimeout(draw, 450); } else draw();
}

// ---- photo phase ---------------------------------------------------------------------------------------------------
function nextEventText(now) {
  const timed = e => !e.all_day;
  const today = todayEvents(now).find(timed);
  if (today) return `${esc(today.title)} · ${parse(today.start) <= now ? 'now' : fmtTime(parse(today.start))}`;
  const tomorrow = data.events.filter(e => onDay(e, addDays(now, 1))).sort(sortEv);
  const first = tomorrow.find(timed);
  if (first) return `Tomorrow · ${esc(first.title)} ${fmtTime(parse(first.start))}`;
  const allDay = todayEvents(now).find(e => e.all_day);
  return allDay ? `Today · ${esc(allDay.title)}` : '';
}

function paintPill(now = new Date()) {
  if (phaseName !== 'photo') return;
  const parts = new Intl.DateTimeFormat([], { hour: 'numeric', minute: '2-digit' }).formatToParts(now);
  const get = t => parts.find(p => p.type === t)?.value || '';
  const w = cfg.state.weather, next = nextEventText(now);
  el.querySelector('.ss-ptime').innerHTML = `${get('hour')}:${get('minute')}${get('dayPeriod') ? `<small>${get('dayPeriod')}</small>` : ''}`;
  el.querySelector('.ss-pmeta').textContent = [fmt(now, { weekday: 'long', month: 'long', day: 'numeric' }), w ? `${icon(w.current.code, w.current.is_day)} ${w.current.temp}°` : ''].filter(Boolean).join('  ·  ');
  const chip = el.querySelector('.ss-next');
  chip.hidden = !next; chip.innerHTML = next ? `<span>📅</span><b>${next}</b>` : '';
}

const shuffle = a => { for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
const slides = () => [...el.querySelectorAll('.ss-slide')];
const releaseSlides = () => slides().forEach(s => { s.classList.remove('on', 'cover', 'contain'); s.removeAttribute('src'); });
const photoUrl = id => `/api/photos/${id}`;

async function showNextPhoto() {
  for (let tries = 0; tries < 4; tries++) {  // a missing or unreadable file is skipped
    if (qi >= queue.length) { queue = shuffle([...photoIds]); qi = 0; }  // every photo once per pass, in a fresh random order
    const next = slides()[1 - active];
    next.classList.remove('on', 'cover', 'contain');
    next.src = photoUrl(queue[qi++]);
    try { await next.decode(); } catch { continue; }
    if (!visible || phaseName !== 'photo') return;
    // Landscape photos fill the screen; portrait ones are shown whole, on the sky background.
    next.classList.add(next.naturalWidth / next.naturalHeight >= 1.25 ? 'cover' : 'contain', 'on');
    slides()[active].classList.remove('on');
    active = 1 - active;
    if (photoIds.length > 1) new Image().src = photoUrl(queue[qi % queue.length]);  // warm the next one so the fade is never late
    return;
  }
}

function enterPhoto() {
  phaseName = 'photo'; photosShown = 0; clearTimeout(freeTimer);
  el.classList.add('photo');
  paintPill(); showNextPhoto();
}

function enterDash() {
  phaseName = 'dash'; cardsShown = 0;
  el.classList.remove('photo');
  paintLeft(); paintCard(false);
  clearTimeout(freeTimer);  // its own timer: the cards' fade timer is cleared on every rotation
  freeTimer = setTimeout(releaseSlides, 1600);  // after the fade-out, free the decoded pictures
}

// ---- the loop: one pass of the dashboard cards, then some photos, then round again ---------------------------------------
const wantsPhotos = () => getMode() !== 'dashboard' && photoIds.length > 0;

function schedule() {
  clearTimeout(stepTimer);
  stepTimer = setTimeout(step, phaseName === 'photo' ? photoMs() : ROTATE_MS);
}

function step() {
  if (!visible) return;
  if (phaseName === 'dash') {
    cardsShown++;
    if (wantsPhotos() && cardsShown >= cards().length) enterPhoto();
    else { idx++; paintCard(true); }
  } else {
    photosShown++;
    if (!photoIds.length || (getMode() === 'both' && photosShown >= PER_ROUND)) enterDash();
    else showNextPhoto();
  }
  schedule();
}

function build() {
  el = document.createElement('div');
  el.id = 'screensaver';
  el.innerHTML = `<div class="ss-stage">
    <img class="ss-brand" src="/icon.svg" alt="" width="40" height="40">
    <section class="ss-left"><div class="ss-time"></div><div class="ss-date"></div><div class="ss-greet"></div><div class="ss-wx"></div></section>
    <section class="ss-right"><div class="ss-slot"></div><div class="ss-pager"></div></section>
    <div class="ss-hint">Tap anywhere to open the calendar</div></div>
    <div class="ss-photos"><img class="ss-slide" alt=""><img class="ss-slide" alt=""><div class="ss-scrim"></div>
      <div class="ss-pill"><div class="ss-ptime"></div><div class="ss-pmeta"></div></div><div class="ss-next" hidden></div></div>`;
  document.body.append(el);
  el.addEventListener('pointerup', wake);
}

// ---- show / hide ---------------------------------------------------------------------------------------------------
export function show(opts = {}) {
  if (!available || visible) return;
  preview = !!opts.preview;
  if (!el) build();
  visible = true; idx = +q.get('sscard') || 0;
  phaseName = 'dash'; cardsShown = 0; photosShown = 0;
  paintLeft(); paintCard(false); load();
  schedule();
  // "Photos only": switch as soon as the list has loaded (the dashboard shows for that split second).
  refreshPhotos().then(() => { if (visible && getMode() === 'photos' && photoIds.length && phaseName === 'dash') { enterPhoto(); schedule(); } });
  timers.push(setInterval(() => { paintLeft(); }, 5_000));
  timers.push(setInterval(load, REFRESH_MS));
  const stage = el.querySelector('.ss-stage'), shift = (n, m) => `translate(${Math.round(Math.random() * n - n / 2)}px, ${Math.round(Math.random() * m - m / 2)}px)`;
  timers.push(setInterval(() => {  // drift a few pixels now and then so a static layout never burns into the panel
    stage.style.transform = shift(20, 16);
    el.querySelector('.ss-pill').style.transform = shift(12, 10); el.querySelector('.ss-next').style.transform = shift(12, 10);
  }, DRIFT_MS));
}

function hide() {
  visible = false; clearTimeout(fadeTimer); clearTimeout(stepTimer); clearTimeout(freeTimer);
  timers.splice(0).forEach(clearInterval);
  phaseName = 'dash';
  releaseSlides();
  el.classList.remove('open'); el.style.display = '';
  el.className = '';
}

function wake() {
  if (!visible) return;
  hide();
  // The tap that woke the screen must not also press whatever is underneath it.
  const stop = e => { e.stopPropagation(); e.preventDefault(); };
  window.addEventListener('click', stop, { capture: true, once: true });
  setTimeout(() => window.removeEventListener('click', stop, true), 400);
  if (!preview) cfg.onWake();
}

// ---- idle detection ------------------------------------------------------------------------------------------------
export function init(options) {
  if (!available) return;
  cfg = options;
  let last = Date.now();
  for (const ev of ['pointerdown', 'pointermove', 'keydown', 'wheel', 'touchstart']) addEventListener(ev, () => { last = Date.now(); }, { passive: true, capture: true });
  addEventListener('keydown', () => { if (visible) wake(); });
  setInterval(() => {
    const m = getMinutes();
    if (visible || !m) return;
    const busy = document.querySelector('#overlay.open') || document.querySelector('#kb:not([hidden])');  // someone may be mid-form: wait 3x longer
    if (Date.now() - last > m * 60_000 * (busy ? 3 : 1)) show();
  }, 10_000);
}
