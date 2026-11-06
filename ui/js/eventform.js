import { api } from './api.js';
import { dkey, esc, parse } from './util.js';
import { openSheet, closeSheet } from './modal.js';

const hhmm = d => `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;

export function openEventForm(state, actions, ev, defaultDay, hour = null) {
  let f;
  if (ev) {
    const s = parse(ev.start), e = parse(ev.end);
    f = { title: ev.title, sd: dkey(s), ed: dkey(e), st: hhmm(s), et: hhmm(e), allDay: ev.all_day,
          member_id: ev.member_id, location: ev.location, description: ev.description };
  } else {
    const d = new Date(defaultDay || Date.now()); const now = new Date();
    const h = hour ?? (defaultDay && dkey(defaultDay) !== dkey(now) ? 9 : Math.min(now.getHours() + 1, 22));
    f = { title: '', sd: dkey(d), ed: dkey(d), st: `${String(h).padStart(2, '0')}:00`, et: h >= 23 ? '23:59' : `${String(h + 1).padStart(2, '0')}:00`,
          allDay: false, member_id: null, location: '', description: '' };
  }
  const sheet = openSheet({ title: ev ? 'Edit event' : 'New event' });

  const render = () => {
    sheet.body.innerHTML = `
      <div class="f"><label>Title</label><input id="e-title" value="${esc(f.title)}" placeholder="Event title" maxlength="200"></div>
      <div class="row"><div class="f"><label>Starts</label><input id="e-sd" type="date" value="${f.sd}"></div>
        <div class="f"><label>Ends</label><input id="e-ed" type="date" value="${f.ed}"></div></div>
      <div class="f"><button class="pill ${f.allDay ? 'on' : ''}" data-allday>${f.allDay ? '✓ ' : ''}All day</button></div>
      ${f.allDay ? '' : `<div class="row"><div class="f"><label>From</label><input id="e-st" type="time" value="${f.st}"></div>
        <div class="f"><label>To</label><input id="e-et" type="time" value="${f.et}"></div></div>`}
      <div class="f"><label>Who</label><div class="pills">
        <button class="pill ${f.member_id == null ? 'on' : ''}" data-who="">Everyone</button>
        ${state.members.map(m => `<button class="pill ${f.member_id === m.id ? 'on' : ''}" style="--c:${m.color}" data-who="${m.id}"><span class="dot" style="--c:${m.color}"></span>${esc(m.name)}</button>`).join('')}</div></div>
      <div class="f"><label>Location</label><input id="e-loc" value="${esc(f.location)}" maxlength="300"></div>
      <div class="f"><label>Notes</label><textarea id="e-desc" maxlength="5000">${esc(f.description)}</textarea></div>
      <div id="e-err" class="stale"></div>`;
  };
  render();
  sheet.setFoot(`${ev ? '<button class="danger" data-del>Delete</button>' : ''}<span class="spacer"></span>
    <button data-close>Cancel</button><button class="primary" data-save>Save</button>`);

  const map = { 'e-title': 'title', 'e-sd': 'sd', 'e-ed': 'ed', 'e-st': 'st', 'e-et': 'et', 'e-loc': 'location', 'e-desc': 'description' };
  sheet.body.oninput = e => {
    const k = map[e.target.id]; if (!k) return;
    f[k] = e.target.value;
    if (k === 'sd' && f.ed < f.sd) { f.ed = f.sd; sheet.body.querySelector('#e-ed').value = f.ed; }
  };
  sheet.body.onclick = e => {
    if (e.target.closest('[data-allday]')) { f.allDay = !f.allDay; render(); }
    const w = e.target.closest('[data-who]');
    if (w) { f.member_id = w.dataset.who === '' ? null : +w.dataset.who; render(); }
  };
  sheet.foot.onclick = async e => {
    const err = m => { sheet.body.querySelector('#e-err').textContent = m; };
    if (e.target.closest('[data-del]')) { await api.deleteEvent(ev.id); closeSheet(); return actions.reload(); }
    if (!e.target.closest('[data-save]')) return;
    if (!f.title.trim()) return err('Please enter a title.');
    if (!f.sd || !f.ed) return err('Please pick dates.');
    const start = f.allDay ? `${f.sd}T00:00:00` : `${f.sd}T${f.st || '00:00'}:00`;
    const end = f.allDay ? `${f.ed}T23:59:00` : `${f.ed}T${f.et || '00:00'}:00`;
    if (end < start) return err('End must be after the start.');
    try {
      await api.saveEvent({ title: f.title.trim(), start, end, all_day: f.allDay, member_id: f.member_id,
                            location: f.location, description: f.description }, ev?.id);
      closeSheet(); actions.reload();
    } catch (ex) { err(String(ex.message).slice(0, 120)); }
  };
}
