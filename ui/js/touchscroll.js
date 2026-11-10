// Drag-to-scroll for the wall touchscreen. Chromium's own touch panning does not work in the Pi's Wayland kiosk (taps do),
// so the page scrolls itself: drag a scrollable area and it follows your finger, then coasts. Plain JS, no dependencies.
// Active only when the page is loaded from the Pi itself (127.0.0.1 / localhost); phones keep their native scrolling.
// Override with ?ts=1 (force on) or ?ts=0 (force off). The scrollbar and mouse wheel still work as normal.

const param = new URLSearchParams(location.search).get('ts');
const ON = param === '1' || (param !== '0' && ['127.0.0.1', 'localhost', '[::1]'].includes(location.hostname));
const THRESHOLD = 8;   // px of movement before a press becomes a drag (a smaller move is still a tap)
const COAST_MS = 325;  // how long a flick keeps gliding

if (ON) {
  document.documentElement.classList.add('ts');  // style.css: touch-action:none, so the browser leaves panning to us
  let g = null, raf = 0;

  const canScroll = (el, axis) => {
    const s = getComputedStyle(el), o = axis === 'y' ? s.overflowY : s.overflowX;
    return /(auto|scroll)/.test(o) && (axis === 'y' ? el.scrollHeight > el.clientHeight + 1 : el.scrollWidth > el.clientWidth + 1);
  };
  const scroller = (el, axis) => {
    for (; el && el !== document.documentElement; el = el.parentElement) if (canScroll(el, axis)) return el;
    return null;
  };
  const prop = axis => axis === 'y' ? 'scrollTop' : 'scrollLeft';

  document.addEventListener('pointerdown', e => {
    cancelAnimationFrame(raf);  // touching stops any glide
    if ((e.pointerType === 'mouse' && e.button !== 0) || e.target.closest('input, textarea, select, #kb')) return;
    g = { id: e.pointerId, sx: e.clientX, sy: e.clientY, x: e.clientX, y: e.clientY, target: e.target, axis: null, el: null,
          drag: false, samples: [[performance.now(), e.clientX, e.clientY]] };
  });

  document.addEventListener('pointermove', e => {
    if (!g || e.pointerId !== g.id) return;
    if (!g.drag) {
      const tx = e.clientX - g.sx, ty = e.clientY - g.sy;
      if (Math.hypot(tx, ty) < THRESHOLD) return;
      g.axis = Math.abs(ty) >= Math.abs(tx) ? 'y' : 'x';
      g.el = scroller(g.target, g.axis);
      if (!g.el) { g = null; return; }  // nothing to scroll that way
      g.drag = true;
    }
    g.el[prop(g.axis)] -= g.axis === 'y' ? e.clientY - g.y : e.clientX - g.x;
    g.x = e.clientX; g.y = e.clientY;
    const now = performance.now();
    g.samples.push([now, e.clientX, e.clientY]);
    while (g.samples.length > 2 && now - g.samples[0][0] > 100) g.samples.shift();
  });

  const end = e => {
    if (!g || e.pointerId !== g.id) return;
    const { drag, axis, el, samples } = g; g = null;
    if (!drag) return;
    // A drag is not a tap: swallow the click the browser is about to send.
    const stop = ev => { ev.stopPropagation(); ev.preventDefault(); };
    window.addEventListener('click', stop, { capture: true, once: true });
    setTimeout(() => window.removeEventListener('click', stop, true), 80);
    if (e.type === 'pointercancel') return;
    // Coast on release, using the speed over the last ~100 ms.
    const [t0, x0, y0] = samples[0], [t1, x1, y1] = samples[samples.length - 1];
    let v = t1 > t0 ? -((axis === 'y' ? y1 - y0 : x1 - x0) / (t1 - t0)) : 0;  // px per ms
    if (Math.abs(v) < 0.1) return;
    let last = performance.now();
    const step = now => {
      const dt = now - last; last = now;
      el[prop(axis)] += v * dt;
      v *= Math.exp(-dt / COAST_MS);
      if (Math.abs(v) > 0.02) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
  };
  document.addEventListener('pointerup', end);
  document.addEventListener('pointercancel', end);
}
