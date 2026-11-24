// Shopping page: two lists side by side, "Groceries" (the store) and "To order" (online). Type an item and tap Add, tap the
// circle to check it off, tap the name to edit. Checked items drop to the bottom until "Clear checked".
import { api } from './api.js';
import { esc, $ } from './util.js';
import { openSheet, closeSheet } from './modal.js';

const LISTS = [{ id: 'grocery', name: 'Groceries', icon: '🛒', color: 'var(--ok)', hint: 'Add to the grocery list' },
               { id: 'order', name: 'To order', icon: '📦', color: 'var(--accent)', hint: 'Add something to order' }];

let actions, page, timer;
const st = { items: [] };

const inList = (id, done) => st.items.filter(i => i.list === id && i.done === done);

function row(i) {
  return `<div class="si ${i.done ? 'done' : ''}" data-item="${i.id}">
    <button class="si-chk" data-check aria-label="${i.done ? 'Put back on the list' : 'Got it'}">${i.done ? '✓' : ''}</button>
    <div class="si-b"><div class="ti">${esc(i.name)}</div>${i.note ? `<div class="sub">${esc(i.note)}</div>` : ''}</div></div>`;
}

// Redraw only the lists and counts, never the add boxes, so whatever is being typed (and the keyboard) is left alone.
function draw() {
  for (const L of LISTS) {
    const col = $(`[data-list="${L.id}"]`, page), open = inList(L.id, false), done = inList(L.id, true), list = $('.sl-items', col);
    const old = list.scrollTop;
    $('.sl-count', col).textContent = open.length ? `${open.length} to get` : st.items.some(i => i.list === L.id) ? 'All done 🎉' : 'Nothing yet';
    list.innerHTML = (open.map(row).join('') || (done.length ? '' : `<div class="none">Nothing here yet.<br>Type below to add something.</div>`))
      + (done.length ? `<div class="si-sep"><span>Got it (${done.length})</span><button data-clear="${L.id}">Clear</button></div>${done.map(row).join('')}` : '');
    list.scrollTop = old;
  }
}

async function load() {
  try { st.items = await api.shopping(); } catch (err) { console.error(err); }
  if (!page.hidden) draw();
}

async function add(listId) {
  const input = $(`[data-list="${listId}"] .sl-in`, page), name = input.value.trim();
  if (!name) return;
  input.value = '';
  try { await api.addShopping(name, listId); } catch (err) { console.error(err); input.value = name; }
  await load();
}

function openForm(item) {
  const f = { name: item.name, note: item.note, list: item.list };
  const sheet = openSheet({ title: 'Edit item' });
  const render = () => {
    sheet.body.innerHTML = `
      <div class="f"><label>Item</label><input id="s-name" value="${esc(f.name)}" maxlength="120"></div>
      <div class="f"><label>Note (quantity, brand…)</label><input id="s-note" value="${esc(f.note)}" maxlength="200" placeholder="Optional"></div>
      <div class="f"><label>List</label><div class="pills">${LISTS.map(L =>
        `<button class="pill ${f.list === L.id ? 'on' : ''}" style="--c:${L.color}" data-list-pick="${L.id}">${L.icon} ${L.name}</button>`).join('')}</div></div>
      <div id="s-err" class="stale"></div>`;
  };
  render();
  sheet.setFoot(`<button class="danger" data-del>Delete</button><span class="spacer"></span><button data-close>Cancel</button><button class="primary" data-save>Save</button>`);
  sheet.body.oninput = e => { if (e.target.id === 's-name') f.name = e.target.value; if (e.target.id === 's-note') f.note = e.target.value; };
  sheet.body.onclick = e => { const p = e.target.closest('[data-list-pick]'); if (p) { f.list = p.dataset.listPick; render(); } };
  sheet.foot.onclick = async e => {
    if (e.target.closest('[data-del]')) { await api.deleteShopping(item.id).catch(console.error); closeSheet(); return load(); }
    if (!e.target.closest('[data-save]')) return;
    const err = m => { $('#s-err', sheet.body).textContent = m; };
    if (!f.name.trim()) return err('Please enter a name.');
    try { await api.saveShopping({ name: f.name.trim(), note: f.note.trim(), list: f.list }, item.id); closeSheet(); load(); }
    catch (ex) { err(/409/.test(ex.message) ? 'That is already on the list.' : String(ex.message).slice(0, 120)); }
  };
}

function close() {
  page.hidden = true; clearInterval(timer);
  history.replaceState(null, '', location.pathname + location.search);
  actions.refreshShopping();
}

export function closeShopping() { if (page && !page.hidden) close(); }

function build() {
  page = document.createElement('section');
  page.id = 'shop-page'; page.hidden = true;
  page.innerHTML = `
    <header class="cp-top">
      <button data-back>‹ Calendar</button>
      <div class="cp-h"><h2>Shopping</h2><div class="cp-date">Tap the circle when you've got it</div></div>
    </header>
    <main class="sb">${LISTS.map(L => `
      <section class="sl" data-list="${L.id}" style="--c:${L.color}">
        <header class="sl-h"><span class="sl-ico">${L.icon}</span><div><div class="nm">${L.name}</div><div class="sl-count"></div></div></header>
        <form class="sl-add"><input class="sl-in" maxlength="120" placeholder="${L.hint}" autocomplete="off" enterkeyhint="done"><button class="primary" type="submit">Add</button></form>
        <div class="sl-items"></div>
      </section>`).join('')}</main>`;
  document.body.append(page);
  // Tapping Add must not take focus from the box, so the on-screen keyboard stays up for the next item.
  for (const ev of ['mousedown', 'pointerdown']) page.addEventListener(ev, e => { if (e.target.closest('.sl-add button')) e.preventDefault(); });
  page.addEventListener('submit', e => { e.preventDefault(); add(e.target.closest('[data-list]').dataset.list); });
  page.onclick = async e => {
    const t = e.target;
    if (t.closest('[data-back]')) return close();
    const clear = t.closest('[data-clear]');
    if (clear) { await api.clearShopping(clear.dataset.clear).catch(console.error); return load(); }
    const el = t.closest('[data-item]');
    if (!el) return;
    const item = st.items.find(i => i.id === +el.dataset.item);
    if (!item) return;
    if (t.closest('[data-check]')) {
      item.done = !item.done; draw();  // show it straight away; the reload below puts the server's order back
      await api.checkShopping(item.id, item.done).catch(console.error);
      return load();
    }
    openForm(item);
  };
}

export async function openShopping(state, acts) {
  actions = acts;
  if (!page) build();
  page.hidden = false;
  history.replaceState(null, '', location.pathname + location.search + '#shopping');
  await load();
  clearInterval(timer);  // pick up changes from another device, but never while someone is typing or editing
  timer = setInterval(() => { if (!$('#overlay').classList.contains('open') && document.activeElement?.tagName !== 'INPUT') load(); }, 30_000);
}
