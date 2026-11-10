import './keyboard.js';
import './touchscroll.js';
import { api } from './api.js';
import { $, addDays, dkey, fmt, iso } from './util.js';
import { rangeFor, rangeTitle, renderView } from './views.js';
import { renderChip, openWeather } from './weather.js';
import { openChores } from './chores.js';
import { openEventForm } from './eventform.js';
import { openSettings } from './settings.js';

const qs = new URLSearchParams(location.search); // ?view=month&open=weather — handy for testing
const state = { view: qs.get('view') || localStorage.getItem('view') || 'week', cursor: new Date(), events: [], members: [], choresLeft: 0, weather: null, google: null,
  units: localStorage.getItem('units') }; // null = use server default (SKYBOLT_UNITS)

const cal = $('#cal');

function render(keepScroll = false) {
  const old = $('.tg-scroll')?.scrollTop;
  cal.innerHTML = renderView(state);
  const sc = $('.tg-scroll');
  if (sc) {  // time grid: keep scroll position on refresh, otherwise start near "now" (or 7am)
    const now = new Date(), hh = sc.scrollHeight / 24, [a, b] = rangeFor(state.view, state.cursor), inRange = now >= a && now < b;
    sc.scrollTop = keepScroll && old != null ? old : Math.max(0, (inRange ? now.getHours() - 1 : 7) * hh - hh * 0.2);
  }
  $('#range').textContent = rangeTitle(state.view, state.cursor);
  document.querySelectorAll('#views button').forEach(b => b.classList.toggle('on', b.dataset.view === state.view));
}

async function loadEvents(keepScroll = false) {
  const [s, e] = rangeFor(state.view, state.cursor);
  try { state.events = await api.events(iso(s), iso(e)); } catch (err) { console.error(err); }
  render(keepScroll);
}
async function refreshChores() {  // badge = chores still to do today, plus overdue/undated ones
  try {
    const t = new Date();
    const [today, open] = await Promise.all([api.chores(dkey(t), dkey(addDays(t, 1))), api.openChores()]);
    state.members = await api.members();
    state.choresLeft = today.filter(c => !c.done).length + open.length;
  } catch (err) { console.error(err); }
  const b = $('#chores-btn .badge');
  b.hidden = !state.choresLeft; b.textContent = state.choresLeft;
}
async function refreshGoogle() {
  try { state.google = await api.google(); } catch { /* keep last */ }
}
async function refreshWeather() {
  try { state.weather = await api.weather(state.units);
    state.units ||= state.weather.units.temp === '°F' ? 'imperial' : 'metric'; } catch { /* keep last */ }
  renderChip($('#wx-chip'), state.weather);
}
const actions = { reload: () => loadEvents(true), refreshChores, refreshGoogle };

function tick() {
  const n = new Date();
  $('#time').textContent = n.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  $('#date').textContent = fmt(n, { weekday: 'long', month: 'long', day: 'numeric' });
}

function shift(dir) {
  const c = new Date(state.cursor);
  if (state.view === 'day') c.setDate(c.getDate() + dir);
  else if (state.view === 'week') c.setDate(c.getDate() + 7 * dir);
  else c.setMonth(c.getMonth() + dir, 1);
  state.cursor = c; loadEvents(true);
}
function setView(v) { state.view = v; localStorage.setItem('view', v); loadEvents(); }

$('#prev').onclick = () => shift(-1);
$('#next').onclick = () => shift(1);
$('#today').onclick = () => { state.cursor = new Date(); loadEvents(); };
$('#views').onclick = e => { const b = e.target.closest('[data-view]'); if (b) setView(b.dataset.view); };
$('#add-btn').onclick = () => openEventForm(state, actions, null, state.view === 'day' ? state.cursor : null);
$('#gear-btn').onclick = () => openSettings(state, { onUnits: setUnits, onClose: async () => { await Promise.all([refreshChores(), refreshGoogle()]); loadEvents(true); } });
$('#chores-btn').onclick = () => openChores(state, actions);
async function setUnits(u, reopen = true) {
  state.units = u; localStorage.setItem('units', u);
  await refreshWeather(); if (reopen) openWeather(state.weather, state.units, setUnits);
}
$('#wx-chip').onclick = () => openWeather(state.weather, state.units, setUnits);
cal.onclick = async e => {
  const ev = e.target.closest('[data-event]');
  if (ev) {  // repeating events: edit the series (its first occurrence), not the tapped date
    const occ = state.events.find(x => x.id === +ev.dataset.event);
    return openEventForm(state, actions, occ.repeat !== 'none' ? await api.event(occ.id) : occ);
  }
  const slot = e.target.closest('[data-slot]');
  if (slot) {  // empty time slot: new event at that hour
    const hour = Math.min(23, Math.floor((e.clientY - slot.getBoundingClientRect().top) / (slot.offsetHeight / 24)));
    return openEventForm(state, actions, null, new Date(slot.dataset.slot + 'T12:00:00'), hour);
  }
  const d = e.target.closest('[data-day]');
  if (d) { state.cursor = new Date(d.dataset.day + 'T12:00:00'); setView('day'); }
};

tick(); setInterval(tick, 10_000);
await Promise.all([refreshChores(), refreshWeather(), refreshGoogle()]);
await loadEvents();
setInterval(refreshWeather, 10 * 60_000);
setInterval(async () => { await refreshGoogle(); loadEvents(true); refreshChores(); }, 2 * 60_000);
const open = qs.get('open');
if (open === 'weather') $('#wx-chip').click();
if (open === 'chores' || location.hash === '#chores') $('#chores-btn').click();
if (open === 'settings') $('#gear-btn').click();
if (open === 'add') $('#add-btn').click();
