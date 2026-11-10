// The UI only talks to the Skybolt backend.
async function call(method, url, body) {
  const r = await fetch(url, {
    method, headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.status === 204 ? null : r.json();
}
export const api = {
  events: (start, end) => call('GET', `/api/events?start=${start}&end=${end}`),
  event: id => call('GET', `/api/events/${id}`),
  saveEvent: (e, id) => id ? call('PUT', `/api/events/${id}`, e) : call('POST', '/api/events', e),
  deleteEvent: id => call('DELETE', `/api/events/${id}`),
  members: () => call('GET', '/api/members'),
  addMember: (name, color) => call('POST', '/api/members', { name, color }),
  updateMember: (id, m) => call('PUT', `/api/members/${id}`, m),
  deleteMember: id => call('DELETE', `/api/members/${id}`),
  chores: (start, end) => call('GET', `/api/chores?start=${start}&end=${end}`),
  openChores: () => call('GET', '/api/chores/open'),
  saveChore: (c, id) => id ? call('PUT', `/api/chores/${id}`, c) : call('POST', '/api/chores', c),
  setDone: (id, done, day) => call('PATCH', `/api/chores/${id}`, { done, day }),
  deleteChore: id => call('DELETE', `/api/chores/${id}`),
  photos: () => call('GET', '/api/photos'),
  weather: units => call('GET', '/api/weather' + (units ? `?units=${units}` : '')),
  google: () => call('GET', '/api/google/status'),
  googleClient: (client_id, client_secret) => call('POST', '/api/google/client', { client_id, client_secret }),
  googleSync: () => call('POST', '/api/google/sync'),
  googleCalendar: (id, enabled) => call('PUT', `/api/google/calendars/${encodeURIComponent(id)}`, { enabled }),
  googleDisconnect: () => call('POST', '/api/google/disconnect'),
};
