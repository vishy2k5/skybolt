import { api } from './api.js';
import { esc } from './util.js';
import { openSheet } from './modal.js';

const SWATCHES = ['#4f9cf9', '#f2994a', '#6fcf97', '#bb6bd9', '#eb5757', '#f2c94c', '#56ccf2', '#9b9b9b'];

export function openSettings(state, { onClose, onUnits }) {
  const sheet = openSheet({ title: 'Settings', close: onClose });

  function list() {
    sheet.setTitle('Settings'); sheet.setFoot('');
    sheet.body.innerHTML = `
      <div class="sec"><h4>People</h4>
        ${state.members.map(m => `<button class="prow" data-edit="${m.id}"><span class="dot" style="--c:${m.color}"></span>${esc(m.name)}<span class="go">Edit ›</span></button>`).join('')
          || '<div style="color:var(--dim);margin-bottom:.5rem">No one added yet.</div>'}
        <button class="primary" data-add style="width:100%">+ Add person</button></div>
      <div class="sec"><h4>Temperature</h4><div class="pills">
        <button class="pill ${state.units === 'imperial' ? 'on' : ''}" data-u="imperial">°F</button>
        <button class="pill ${state.units === 'metric' ? 'on' : ''}" data-u="metric">°C</button></div></div>`;
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
  function show() {
    list();
    sheet.body.oninput = null;
    sheet.body.onclick = async e => {
      const ed = e.target.closest('[data-edit]'), u = e.target.closest('[data-u]');
      if (ed) form(state.members.find(x => x.id === +ed.dataset.edit));
      else if (e.target.closest('[data-add]')) form(null);
      else if (u && u.dataset.u !== state.units) { await onUnits(u.dataset.u, false); list(); }
    };
  }
  show();
}
