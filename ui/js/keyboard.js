// On-screen keyboard for the wall touchscreen. Plain JS, no dependencies.
// Shown only when the page is loaded from the Pi itself (127.0.0.1 / localhost); phones use their own keyboard.
// Override with ?kb=1 (force on) or ?kb=0 (force off). A physical keyboard still works as normal.

const param = new URLSearchParams(location.search).get('kb');
const ON = param === '1' || (param !== '0' && ['127.0.0.1', 'localhost', '[::1]'].includes(location.hostname));

const ROWS = {
  lower: ['qwertyuiop', 'asdfghjkl', '^zxcvbnm<'],
  upper: ['QWERTYUIOP', 'ASDFGHJKL', '^ZXCVBNM<'],
  sym:   ['1234567890', '@#$%&-+()/', '^*"\':;!?<'],
};
const TEXTY = new Set(['text', 'search', 'url', 'email', 'password', 'tel', 'number', '']);
const eligible = el => el && ((el.tagName === 'INPUT' && TEXTY.has(el.type)) || el.tagName === 'TEXTAREA') && !el.readOnly && !el.disabled;

if (ON) {
  let kb, target = null, layer = 'lower', shift = false, caps = false, rep = null;

  const build = () => {
    kb = document.createElement('div');
    kb.id = 'kb'; kb.hidden = true;
    document.body.append(kb);
    // Keep focus in the text field: never let a key press steal it.
    kb.addEventListener('mousedown', e => e.preventDefault());
    kb.addEventListener('pointerdown', e => {
      e.preventDefault();
      const b = e.target.closest('[data-k]'); if (!b) return;
      press(b.dataset.k);
      if (b.dataset.k === '<') {  // hold backspace to repeat
        clearTimeout(rep); rep = setTimeout(function again() { press('<'); rep = setTimeout(again, 70); }, 400);
      }
    });
    for (const ev of ['pointerup', 'pointercancel', 'pointerleave']) kb.addEventListener(ev, () => clearTimeout(rep));
  };

  const draw = () => {
    const sym = layer === 'sym', rows = ROWS[sym ? 'sym' : caps || shift ? 'upper' : 'lower'];
    const key = (k, txt, cls = '') => `<button data-k="${k === '"' ? '&quot;' : k}" class="kb-key ${cls}">${txt}</button>`;
    const fn = { '^': caps ? '⇪' : '⇧', '<': '⌫' };
    const html = rows.map(r => `<div class="kb-r">${[...r].map(c => '^<'.includes(c)
      ? key(c, fn[c], 'kb-fn' + (c === '^' && (shift || caps) ? ' on' : '')) : key(c, c)).join('')}</div>`);
    html.push(`<div class="kb-r">${key(sym ? '@abc' : '@sym', sym ? 'ABC' : '?123', 'kb-fn')}${key(',', ',')}${key(' ', 'space', 'kb-space')}${key('.', '.')}
      ${key('@enter', target?.tagName === 'TEXTAREA' ? '↵' : 'Done', 'kb-fn kb-done')}</div>`);
    kb.innerHTML = html.join('');
  };

  const press = k => {
    if (!target) return;
    if (k === '^') { if (caps) caps = shift = false; else if (shift) { caps = true; } else shift = true; return draw(); }
    if (k === '@sym') { layer = 'sym'; shift = caps = false; return draw(); }
    if (k === '@abc') { layer = 'lower'; return draw(); }
    if (k === '@enter') {
      if (target.tagName === 'TEXTAREA') return insert('\n');
      return hide(true);
    }
    if (k === '<') return back();
    insert(k);
    if (shift && !caps) { shift = false; draw(); }
  };

  const fire = () => target.dispatchEvent(new Event('input', { bubbles: true }));
  const insert = s => {
    const el = target, max = el.maxLength;
    if (max > 0 && el.value.length >= max && el.selectionStart === el.selectionEnd) return;
    if (typeof el.selectionStart === 'number') el.setRangeText(s, el.selectionStart, el.selectionEnd, 'end');
    else el.value += s;  // email / number inputs do not expose a caret
    fire();
  };
  const back = () => {
    const el = target; let a = el.selectionStart, b = el.selectionEnd;
    if (typeof a !== 'number') { el.value = el.value.slice(0, -1); return fire(); }
    if (a === b) { if (!a) return; a -= 1; }
    el.setRangeText('', a, b, 'end'); fire();
  };

  const show = el => {
    target = el;
    el.inputMode = 'none';  // stop any system keyboard from also opening
    if (!kb) build();
    layer = el.type === 'number' || el.type === 'tel' ? 'sym' : 'lower';
    caps = false; shift = el.tagName === 'TEXTAREA' || el.type === 'text' ? !el.value : false;  // capitalise the first letter
    kb.hidden = false; draw();
    const h = kb.offsetHeight;
    document.documentElement.style.setProperty('--kbh', h + 'px');
    document.getElementById('overlay')?.classList.add('kb');
    requestAnimationFrame(() => el.scrollIntoView({ block: 'center', behavior: 'smooth' }));
  };
  const hide = blur => {
    clearTimeout(rep);
    if (blur && target) target.blur();
    target = null;
    if (!kb) return;
    kb.hidden = true;
    document.documentElement.style.setProperty('--kbh', '0px');
    document.getElementById('overlay')?.classList.remove('kb');
  };

  document.addEventListener('pointerdown', e => { if (eligible(e.target)) e.target.inputMode = 'none'; }, true);
  document.addEventListener('focusin', e => { if (eligible(e.target)) show(e.target); else if (!e.target.closest?.('#kb')) hide(); });
  document.addEventListener('focusout', e => {
    if (e.target !== target) return;
    setTimeout(() => { if (target === e.target && document.activeElement !== e.target) hide(); }, 0);
  });
  // A sheet that closes or re-renders removes the focused field without a blur: tidy up then.
  new MutationObserver(() => { if (target && !target.isConnected) hide(); })
    .observe(document.body, { childList: true, subtree: true });
}
