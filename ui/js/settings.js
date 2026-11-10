import { api } from './api.js';
import { esc } from './util.js';
import { openSheet } from './modal.js';
import { available as ssAvailable, getMinutes, setMinutes, getMode, setMode, getPhotoSeconds, setPhotoSeconds, photoCount, refreshPhotos, show as showScreensaver } from './screensaver.js';

const SWATCHES = ['#4f9cf9', '#f2994a', '#6fcf97', '#bb6bd9', '#eb5757', '#f2c94c', '#56ccf2', '#9b9b9b'];

const ago = t => { const m = Math.round((Date.now() - new Date(t)) / 60000); return m < 1 ? 'just now' : m < 60 ? `${m} min ago` : new Date(t).toLocaleString(); };

const CONSOLE = 'https://console.cloud.google.com';
const onPi = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
const link = (path, text) => `<a href="${CONSOLE}${path}" target="_blank" rel="noopener">${text}</a>`;

// One-time Google Cloud setup, shown right in Settings with direct links.
const SETUP = `<ol class="steps">
  <li>${link('/projectcreate', 'Create a Google Cloud project')} named <b>Skybolt</b> (sign in with your Google account).</li>
  <li>${link('/apis/library/calendar-json.googleapis.com', 'Open the Google Calendar API')} and click <b>Enable</b>.</li>
  <li>${link('/auth/overview', 'Set up sign-in')}: click <b>Get started</b>, name it <b>Skybolt</b>, pick your email, choose <b>External</b>, then <b>Create</b>.</li>
  <li>${link('/auth/audience', 'Audience')}: click <b>Publish app</b>, then <b>Confirm</b>. This stops Google from signing you out every week.</li>
  <li>${link('/auth/clients/create', 'Create a client')}: for Application type choose <b>Desktop app</b>, then <b>Create</b>. Copy the two values it shows into the boxes below.</li>
</ol>
<div class="f"><label>Client ID</label><input id="g-id" autocomplete="off" spellcheck="false" placeholder="….apps.googleusercontent.com"></div>
<div class="f"><label>Client secret</label><input id="g-secret" autocomplete="off" spellcheck="false" placeholder="GOCSPX-…"></div>
<button class="primary" data-gsave style="width:100%">Connect Google account</button>`;

function googleSection(g, armed, editClient) {
  if (!g) return '';
  let h = '<div class="sec"><h4>Google Calendar</h4>';
  if (g.problem) h += `<div class="stale">${esc(g.problem)}</div>`;
  else if (!g.connected && !onPi) h += '<div class="note">To connect Google, open <b>http://localhost:8000</b> in the browser on the Pi itself.</div>';
  else if (!g.has_client || editClient) h += SETUP;
  else if (!g.connected) h += `<button class="primary" data-gconnect style="width:100%">Connect Google account</button>
      <button data-gedit style="width:100%;margin-top:.4rem">Use a different Client ID</button>`;
  else {
    h += `<div class="note">Signed in as <b>${esc(g.account || '')}</b>. Tap a calendar to show or hide it.</div>
      ${g.calendars.map(c => `<button class="prow" data-gcal="${esc(c.id)}"><span class="dot" style="--c:${c.color}"></span>${esc(c.summary)}${c.writable ? '' : ' <small>(view only)</small>'}
        <span class="go">${c.enabled ? '✓ Shown' : 'Hidden'}</span></button>`).join('')}
      <div class="pills" style="margin-top:.5rem"><button data-gsync>Sync now</button><span class="spacer"></span>
        <button class="danger" data-gdisc>${armed ? 'Tap again to disconnect' : 'Disconnect'}</button></div>`;
  }
  if (g.error) h += `<div class="stale">${esc(g.error)}</div>`;
  else if (g.connected && g.last_sync) h += `<div class="note">Last synced ${ago(g.last_sync)}.</div>`;
  return h + '</div>';
}

export function openSettings(state, { onClose, onUnits }) {
  const sheet = openSheet({ title: 'Settings', close: onClose });
  let armed = false, editClient = false, shownPhotos = photoCount();

  function list() {
    sheet.setTitle('Settings'); sheet.setFoot('');
    sheet.body.innerHTML = `
      <div class="sec"><h4>People</h4>
        ${state.members.map(m => `<button class="prow" data-edit="${m.id}"><span class="dot" style="--c:${m.color}"></span>${esc(m.name)}<span class="go">Edit ›</span></button>`).join('')
          || '<div style="color:var(--dim);margin-bottom:.5rem">No one added yet.</div>'}
        <button class="primary" data-add style="width:100%">+ Add person</button></div>
      <div class="sec"><h4>Temperature</h4><div class="pills">
        <button class="pill ${state.units === 'imperial' ? 'on' : ''}" data-u="imperial">°F</button>
        <button class="pill ${state.units === 'metric' ? 'on' : ''}" data-u="metric">°C</button></div></div>
      ${ssAvailable ? `<div class="sec"><h4>Screensaver</h4><div class="note">Shows the clock, your day, chores and the forecast after the screen has been idle. Tap it to open the calendar.</div>
        <div class="pills">${[[0, 'Off'], [2, '2 min'], [5, '5 min'], [10, '10 min'], [30, '30 min']].map(([m, l]) =>
          `<button class="pill ${getMinutes() === m ? 'on' : ''}" data-ss="${m}">${l}</button>`).join('')}<span class="spacer"></span>
          <button data-sspreview>Preview</button></div>
        <h4 style="margin-top:.9rem">Show</h4><div class="pills">${[['both', 'Dashboard + photos'], ['dashboard', 'Dashboard only'], ['photos', 'Photos only']].map(([m, l]) =>
          `<button class="pill ${getMode() === m ? 'on' : ''}" data-ssmode="${m}">${l}</button>`).join('')}</div>
        ${getMode() !== 'dashboard' ? `<h4 style="margin-top:.9rem">Time per photo</h4><div class="pills">${[8, 12, 20, 30].map(n =>
          `<button class="pill ${getPhotoSeconds() === n ? 'on' : ''}" data-ssphoto="${n}">${n} sec</button>`).join('')}</div>
          <div class="note" style="margin-top:.5rem">${photoCount() ? `${photoCount()} photo${photoCount() === 1 ? '' : 's'} found.` : 'No photos yet. Copy pictures into <b>data/photos</b> on the Pi (JPG, PNG or WebP).'}</div>` : ''}</div>` : ''}
      ${googleSection(state.google, armed, editClient)}`;
    sheet.foot.onclick = null;
  }

  function form(m) {
    const used = new Set(state.members.map(x => x.color));
    const f = { name: m?.name || '', color: m?.color || SWATCHES.find(c => !used.has(c)) || SWATCHES[0], armed: false };
    const render = () => {
      sheet.setTitle(m ? 'Edit person' : 'Add person');
      sheet.body.innerHTML = `<div class="f"><label>Name</label><input id="p-name" value="${esc(f.name)}" maxlength="40" placeholder="e.g. Mia"></div>
        <div class="f"><label>Colour</label><div class="sw">${SWATCHES.map(c => `<button class="swatch ${c === f.color ? 'on' : ''}" style="--c:${c}" data-c="${c}" aria-label="${c}"></button>`).join('')}</div></div>
        ${f.armed ? '<div class="stale">Their events and chores will stay but become unassigned.</div>' : ''}<div id="p-err" class="stale"></div>`;
      sheet.setFoot(`${m ? `<button class="danger" data-del>${f.armed ? 'Tap again to delete' : 'Delete'}</button>` : ''}<span class="spacer"></span>
        <button data-cancel>Cancel</button><button class="primary" data-save>Save</button>`);
    };
    render();
    sheet.body.oninput = e => { if (e.target.id === 'p-name') f.name = e.target.value; };
    sheet.body.onclick = e => { const c = e.target.closest('[data-c]'); if (c) { f.color = c.dataset.c; render(); } };
    sheet.foot.onclick = async e => {
      const err = t => { sheet.body.querySelector('#p-err').textContent = t; };
      if (e.target.closest('[data-cancel]')) return back();
      if (e.target.closest('[data-del]')) {
        if (!f.armed) { f.armed = true; return render(); }
        await api.deleteMember(m.id); return back();
      }
      if (!e.target.closest('[data-save]')) return;
      if (!f.name.trim()) return err('Please enter a name.');
      try {
        await (m ? api.updateMember(m.id, { name: f.name.trim(), color: f.color }) : api.addMember(f.name.trim(), f.color));
        await back();
      } catch (ex) { err(/409|exists/.test(ex.message) ? 'That name is already taken.' : String(ex.message).slice(0, 100)); }
    };
  }

  async function back() { state.members = await api.members(); show(); }
  async function google(fn) {
    try { state.google = await fn(); } catch (ex) { state.google = { ...state.google, error: String(ex.message).slice(0, 160) }; }
    list();
  }
  function show() {
    list();
    sheet.body.oninput = null;
    sheet.body.onclick = async e => {
      const ed = e.target.closest('[data-edit]'), u = e.target.closest('[data-u]'), gcal = e.target.closest('[data-gcal]');
      if (!e.target.closest('[data-gdisc]')) armed = false;
      if (e.target.closest('[data-gconnect]')) location.href = '/api/google/connect';
      else if (e.target.closest('[data-gedit]')) { editClient = true; list(); }
      else if (e.target.closest('[data-gsave]')) {
        const v = id => sheet.body.querySelector(id).value.trim();
        const [client_id, client_secret] = [v('#g-id'), v('#g-secret')];
        if (!client_id || !client_secret) { state.google = { ...state.google, error: 'Paste both the Client ID and the Client secret.' }; return list(); }
        try { await api.googleClient(client_id, client_secret); location.href = '/api/google/connect'; }
        catch (ex) { state.google = { ...state.google, error: (() => { try { return JSON.parse(ex.message).detail; } catch { return ex.message; } })() }; list(); }
      }
      else if (gcal) {
        const c = state.google.calendars.find(x => x.id === gcal.dataset.gcal);
        gcal.querySelector('.go').textContent = 'Syncing…';
        await google(() => api.googleCalendar(c.id, !c.enabled));
      } else if (e.target.closest('[data-gsync]')) { e.target.textContent = 'Syncing…'; await google(api.googleSync); }
      else if (e.target.closest('[data-gdisc]')) {
        if (!armed) { armed = true; return list(); }
        armed = false; await google(async () => { await api.googleDisconnect(); return api.google(); });
      }
      else if (ed) form(state.members.find(x => x.id === +ed.dataset.edit));
      else if (e.target.closest('[data-add]')) form(null);
      else if (e.target.closest('[data-ss]')) { setMinutes(+e.target.closest('[data-ss]').dataset.ss); list(); }
      else if (e.target.closest('[data-ssmode]')) { setMode(e.target.closest('[data-ssmode]').dataset.ssmode); list(); }
      else if (e.target.closest('[data-ssphoto]')) { setPhotoSeconds(+e.target.closest('[data-ssphoto]').dataset.ssphoto); list(); }
      else if (e.target.closest('[data-sspreview]')) showScreensaver({ preview: true });
      else if (u && u.dataset.u !== state.units) { await onUnits(u.dataset.u, false); list(); }
    };
  }
  show();
  if (ssAvailable) refreshPhotos().then(n => { if (n !== shownPhotos && sheet.body.querySelector('[data-ssmode]')) { list(); shownPhotos = n; } });
}
