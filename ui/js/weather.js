import { esc, fmt, fmtTime, parse } from './util.js';
import { openSheet } from './modal.js';

const W = {
  0: ['☀️', 'Clear'], 1: ['🌤️', 'Mostly clear'], 2: ['⛅', 'Partly cloudy'], 3: ['☁️', 'Overcast'],
  45: ['🌫️', 'Fog'], 48: ['🌫️', 'Freezing fog'], 51: ['🌦️', 'Light drizzle'], 53: ['🌦️', 'Drizzle'], 55: ['🌧️', 'Heavy drizzle'],
  56: ['🌧️', 'Freezing drizzle'], 57: ['🌧️', 'Freezing drizzle'], 61: ['🌧️', 'Light rain'], 63: ['🌧️', 'Rain'], 65: ['🌧️', 'Heavy rain'],
  66: ['🌧️', 'Freezing rain'], 67: ['🌧️', 'Freezing rain'], 71: ['🌨️', 'Light snow'], 73: ['🌨️', 'Snow'], 75: ['❄️', 'Heavy snow'],
  77: ['🌨️', 'Snow grains'], 80: ['🌦️', 'Light showers'], 81: ['🌧️', 'Showers'], 82: ['⛈️', 'Heavy showers'],
  85: ['🌨️', 'Snow showers'], 86: ['❄️', 'Heavy snow showers'], 95: ['⛈️', 'Thunderstorm'], 96: ['⛈️', 'Thunderstorm, hail'], 99: ['⛈️', 'Thunderstorm, hail'],
};
export const icon = (code, day = true) => (!day && code <= 1 ? '🌙' : (W[code] || ['❔'])[0]);
export const label = code => (W[code] || ['', 'Unknown'])[1];

export function renderChip(el, w) {
  if (!w) { el.innerHTML = '<span class="ico">🌡️</span><small>Weather</small>'; return; }
  const d = w.daily[0];
  el.innerHTML = `<span class="ico">${icon(w.current.code, w.current.is_day)}</span>${w.current.temp}°
    <small>H ${d.high}°<br>L ${d.low}°</small>`;
}

export function openWeather(w, units, onUnits) {
  const s = openSheet({ title: w ? `Weather · ${w.location}` : 'Weather' });
  s.setFoot(`<span class="spacer"></span><div id="units" class="pills">
    <button class="pill ${units === 'imperial' ? 'on' : ''}" data-u="imperial">°F</button>
    <button class="pill ${units === 'metric' ? 'on' : ''}" data-u="metric">°C</button></div>`);
  s.foot.onclick = e => { const b = e.target.closest('[data-u]'); if (b && b.dataset.u !== units) onUnits(b.dataset.u); };
  if (!w) { s.body.innerHTML = '<div class="empty" style="padding:2rem;text-align:center">Weather isn’t available right now.</div>'; return; }
  const c = w.current, u = w.units, t0 = w.daily[0];
  s.body.innerHTML = `
    <div class="wx-now"><div class="big">${icon(c.code, c.is_day)}</div><div class="temp">${c.temp}${u.temp}</div>
      <div class="meta"><b>${label(c.code)}</b><br>Feels like ${c.feels_like}°  ·  Humidity ${c.humidity}%<br>
      Wind ${c.wind} ${u.wind}  ·  ☀️ ${fmtTime(parse(t0.sunrise))} – 🌇 ${fmtTime(parse(t0.sunset))}
      ${w.stale ? '<br><span class="stale">Offline — showing last known forecast</span>' : ''}</div></div>
    <div class="hours">${w.hourly.map(h => `<div class="hr">${fmtTime(parse(h.time)).replace(/:00/, '')}
      <div class="e">${icon(h.code, true)}</div>${h.temp}°<div class="p">${h.precip > 0 ? '💧' + h.precip + '%' : ''}</div></div>`).join('')}</div>
    <div>${w.daily.map((d, i) => `<div class="dyr"><span class="dd">${i === 0 ? 'Today' : fmt(parse(d.date), { weekday: 'short', day: 'numeric' })}</span>
      <span class="e">${icon(d.code)}</span><span class="pp">${d.precip > 0 ? '💧' + d.precip + '%' : ''}</span>
      <span style="color:var(--dim)">${esc(label(d.code))}</span><span class="lh"><b>${d.high}°</b> <span class="lo">${d.low}°</span></span></div>`).join('')}</div>`;
}
