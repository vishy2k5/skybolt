import { $, esc } from './util.js';

const ov = $('#overlay');
let onClose = null;

export function openSheet({ title, right = false, close }) {
  ov.className = 'open' + (right ? ' right' : '');
  ov.innerHTML = `<div class="sheet"><div class="sheet-h"><h3>${esc(title)}</h3>
    <button data-close aria-label="Close">✕</button></div><div class="sheet-b"></div><div class="sheet-f" hidden></div></div>`;
  onClose = close || null;
  const foot = $('.sheet-f', ov);
  return {
    body: $('.sheet-b', ov), foot,
    setTitle: t => { $('h3', ov).textContent = t; },
    setFoot: html => { foot.hidden = !html; foot.innerHTML = html || ''; },
  };
}
export function closeSheet() {
  ov.className = ''; ov.innerHTML = '';
  const f = onClose; onClose = null; if (f) f();
}
export const isOpen = () => ov.classList.contains('open');

ov.addEventListener('click', e => {
  if (e.target === ov || e.target.closest('[data-close]')) closeSheet();
});
document.addEventListener('keydown', e => { if (e.key === 'Escape' && isOpen()) closeSheet(); });
