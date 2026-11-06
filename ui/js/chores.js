import { api } from './api.js';
import { addDays, dkey, esc, fmt, parse, startOfDay } from './util.js';
import { openSheet } from './modal.js';

const REPEAT = { none: 'Never', daily: 'Daily', weekly: 'Weekly' };

function dueLabel(due) {
  if (!due) return { text: 'No due date', late: false };
  const today = startOfDay(new Date()), d = parse(due), diff = Math.round((d - today) / 864e5);
  if (diff === 0) return { text: 'Today', late: false };
  if (diff === 1) return { text: 'Tomorrow', late: false };
  if (diff < 0) return { text: `Overdue · ${fmt(d, { month: 'short', day: 'numeric' })}`, late: true };
  return { text: fmt(d, { weekday: 'short', month: 'short', day: 'numeric' }), late: false };
}

const pills = (name, opts, sel) => `<div class="pills">${opts.map(([v, l, c]) =>
  `<button class="pill ${String(sel) === String(v) ? 'on' : ''}" ${c ? `style="--c:${c}"` : ''} data-pill="${name}" data-v="${v}">${l}</button>`).join('')}</div>`;

export function openChores(state, actions) {
  const sheet = openSheet({ title: 'Chores', right: true, close: actions.refreshChores });
  const member = id => state.members.find(m => m.id === id);

  async function reload() { state.chores = await api.chores(); showList(); wire(); }

  function showList() {
    sheet.setTitle('Chores');
    sheet.setFoot('<button class="primary" data-add style="flex:1">+ Add chore</button>');
    const groups = [...state.members.map(m => [m, state.chores.filter(c => c.member_id === m.id)]),
                    [{ name: 'Anyone', color: null }, state.chores.filter(c => !member(c.member_id))]].filter(([, l]) => l.length);
    sheet.body.innerHTML = groups.length ? groups.map(([m, list]) => `<div class="grp"><h4>${esc(m.name)}</h4>${list.map(c => {
      const d = dueLabel(c.due);
      return `<div class="chore ${c.done ? 'done' : ''}" style="--c:${m.color || 'var(--dim)'}">
        <button class="chk" data-toggle="${c.id}" aria-label="Mark done">${c.done ? '✓' : ''}</button>
        <div class="body" data-edit="${c.id}"><div class="ct">${esc(c.title)}</div>
        <div class="cd ${d.late && !c.done ? 'late' : ''}">${d.text}${c.repeat !== 'none' ? ' · 🔁 ' + REPEAT[c.repeat] : ''}</div></div></div>`;
    }).join('')}</div>`).join('') : '<div class="empty" style="text-align:center;padding:2rem">No chores — you’re all caught up 🎉</div>';
  }

  function showForm(chore) {
    const f = { title: chore?.title || '', member_id: chore?.member_id ?? null, due: chore?.due || null,
                repeat: chore?.repeat || 'none', newPerson: false, personName: '', pickDate: false };
    const render = () => {
      sheet.setTitle(chore ? 'Edit chore' : 'New chore');
      const tomorrow = dkey(addDays(new Date(), 1)), today = dkey(new Date());
      const dueSel = f.pickDate ? 'pick' : !f.due ? 'none' : f.due === today ? 'today' : f.due === tomorrow ? 'tomorrow' : 'pick';
      sheet.body.innerHTML = `
        <div class="f"><label>What needs doing?</label><input id="c-title" value="${esc(f.title)}" placeholder="e.g. Empty dishwasher" maxlength="200"></div>
        <div class="f"><label>Who</label>${pills('who', [['', 'Anyone'], ...state.members.map(m => [m.id, `<span class="dot" style="--c:${m.color}"></span>${esc(m.name)}`, m.color]), ['new', '+ New person']],
          f.newPerson ? 'new' : (f.member_id ?? ''))}
          ${f.newPerson ? `<input id="c-person" style="margin-top:.5rem" placeholder="Name" value="${esc(f.personName)}" maxlength="40">` : ''}</div>
        <div class="f"><label>Due</label>${pills('due', [['none', 'None'], ['today', 'Today'], ['tomorrow', 'Tomorrow'], ['pick', 'Pick date']], dueSel)}
          ${dueSel === 'pick' ? `<input id="c-due" type="date" style="margin-top:.5rem" value="${f.due || ''}">` : ''}</div>
        <div class="f"><label>Repeat</label>${pills('repeat', Object.entries(REPEAT), f.repeat)}</div>
        <div id="c-err" class="stale"></div>`;
      sheet.setFoot(`${chore ? '<button class="danger" data-del>Delete</button>' : ''}<span class="spacer"></span>
        <button data-cancel>Cancel</button><button class="primary" data-save>Save</button>`);
    };
    render();
    sheet.body.oninput = e => {
      if (e.target.id === 'c-title') f.title = e.target.value;
      if (e.target.id === 'c-person') f.personName = e.target.value;
      if (e.target.id === 'c-due') f.due = e.target.value || null;
    };
    sheet.body.onclick = e => {
      const p = e.target.closest('[data-pill]'); if (!p) return;
      const v = p.dataset.v;
      if (p.dataset.pill === 'who') { f.newPerson = v === 'new'; f.member_id = v === '' || v === 'new' ? null : +v; }
      if (p.dataset.pill === 'repeat') f.repeat = v;
      if (p.dataset.pill === 'due') {
        f.pickDate = v === 'pick';
        f.due = v === 'none' ? null : v === 'today' ? dkey(new Date()) : v === 'tomorrow' ? dkey(addDays(new Date(), 1)) : (f.due || dkey(new Date()));
      }
      render();
    };
    sheet.foot.onclick = async e => {
      if (e.target.closest('[data-cancel]')) { showList(); return wire(); }
      if (e.target.closest('[data-del]')) { await api.deleteChore(chore.id); return reload(); }
      if (!e.target.closest('[data-save]')) return;
      const err = msg => { sheet.body.querySelector('#c-err').textContent = msg; };
      if (!f.title.trim()) return err('Please enter a title.');
      try {
        let mid = f.member_id;
        if (f.newPerson) {
          if (!f.personName.trim()) return err('Please enter a name.');
          const m = await api.addMember(f.personName.trim()); state.members.push(m); mid = m.id;
        }
        await api.saveChore({ title: f.title.trim(), member_id: mid, due: f.due, repeat: f.repeat }, chore?.id);
        await reload();
      } catch (ex) { err(String(ex.message).slice(0, 120)); }
    };
  }

  function wire() {
    sheet.body.oninput = null;
    sheet.body.onclick = async e => {
      const t = e.target.closest('[data-toggle]'), ed = e.target.closest('[data-edit]');
      if (t) {
        const c = state.chores.find(x => x.id === +t.dataset.toggle);
        await api.setDone(c.id, !c.done); await reload();
      } else if (ed) showForm(state.chores.find(x => x.id === +ed.dataset.edit));
    };
    sheet.foot.onclick = e => { if (e.target.closest('[data-add]')) showForm(null); };
  }
  showList(); wire();
}
