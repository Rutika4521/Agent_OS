/**
 * Agent-OS REST API client.
 * All calls go through /api which the Vite proxy forwards to http://127.0.0.1:8000
 */

const BASE = '/api'

async function get(path) {
  const r = await fetch(`${BASE}${path}`)
  if (!r.ok) throw new Error(`GET ${path} → ${r.status}`)
  return r.json()
}

async function post(path, body = {}) {
  const r = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`POST ${path} → ${r.status}`)
  return r.json()
}

export const api = {
  // ── System ────────────────────────────────────────────────────────────────
  getHealth:     ()            => get('/health'),
  getMetrics:    ()            => get('/metrics'),

  // ── Processes ─────────────────────────────────────────────────────────────
  getProcesses:  ()            => get('/processes'),
  getProcess:    (pid)         => get(`/processes/${pid}`),
  spawnProcess:  (body)        => post('/processes', body),
  cancelProcess: (pid)         => post(`/processes/${pid}/cancel`),
  pauseProcess:  (pid)         => post(`/processes/${pid}/pause`),
  resumeProcess: (pid)         => post(`/processes/${pid}/resume`),
  terminateProcess: (pid)      => post(`/processes/${pid}/terminate`),

  // ── IPC ───────────────────────────────────────────────────────────────────
  sendIPC:       (body)        => post('/ipc/send', body),
  receiveIPC:    (pid)         => get(`/ipc/receive/${pid}`),
  sendToPid:     (pid, body)   => post(`/processes/${pid}/messages`, body),
  getMessages:   (pid)         => get(`/processes/${pid}/messages`),

  // ── Events ────────────────────────────────────────────────────────────────
  getEvents:     (params = '') => get(`/events${params}`),

  // ── Demo ──────────────────────────────────────────────────────────────────
  runDemo:       ()            => post('/demo/run'),
  getDemoStatus: ()            => get('/demo/status'),
  resetDemo:     ()            => post('/demo/reset'),
  getDemoReport: ()            => get('/demo/report'),
}
