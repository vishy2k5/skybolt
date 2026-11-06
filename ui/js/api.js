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
  chores: () => call('GET', '/api/chores'),
  saveChore: (c, id) => id ? call('PUT', `/api/chores/${id}`, c) : call('POST', '/api/chores', c),
  setDone: (id, done) => call('PATCH', `/api/chores/${id}`, { done }),
  deleteChore: id => call('DELETE', `/api/chores/${id}`),
  weather: units => call('GET', '/api/weather' + (units ? `?units=${units}` : '')),
};
