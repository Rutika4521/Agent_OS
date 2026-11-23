import React, { useMemo, useState } from 'react'
import { api } from '../api.js'

export default function IPCPanel({ events, processes }) {
  const [from, setFrom]     = useState('')
  const [to, setTo]         = useState('')
  const [payload, setPayload] = useState('{"msg": "hello"}')
  const [sending, setSending] = useState(false)
  const [result, setResult]   = useState(null)

  const ipcEvents = useMemo(() =>
    events.filter(e => ['IPC_SENT','IPC_RECEIVED','IPC_DROPPED'].includes(e.event_type))
          .slice().reverse(),
    [events]
  )

  // Build flow map: sender → receiver message counts
  const flowMap = useMemo(() => {
    const map = {}
    ipcEvents.filter(e => e.event_type === 'IPC_SENT').forEach(e => {
      const key = `${e.metadata?.sender_pid ?? e.process_id} → ${e.metadata?.receiver_pid ?? '?'}`
      map[key] = (map[key] ?? 0) + 1
    })
    return map
  }, [ipcEvents])

  async function send() {
    setSending(true)
    setResult(null)
    try {
      const parsed = JSON.parse(payload)
      const r = await api.sendIPC({ sender_pid: Number(from), receiver_pid: Number(to), payload: parsed })
      setResult({ ok: true, text: `Message sent: ${r.message_id}` })
    } catch (e) {
      setResult({ ok: false, text: e.message })
    } finally {
      setSending(false)
    }
  }

  const pidNames = useMemo(() => {
    const m = {}
    processes.forEach(p => { m[p.process_id] = p.name })
    return m
  }, [processes])

  return (
    <div>
      <div style={styles.header}>
        <h1 style={styles.title}>IPC Flow</h1>
        <span style={styles.subtitle}>Inter-process communication messages</span>
      </div>

      <div style={styles.grid}>
        {/* ── Send message panel ── */}
        <div style={styles.panel}>
          <h2 style={styles.panelTitle}>Send IPC Message</h2>
          <label style={styles.label}>From PID</label>
          <input style={styles.input} value={from} onChange={e => setFrom(e.target.value)} placeholder="e.g. 1" />
          <label style={styles.label}>To PID</label>
          <input style={styles.input} value={to} onChange={e => setTo(e.target.value)} placeholder="e.g. 2" />
          <label style={styles.label}>Payload (JSON)</label>
          <textarea
            style={{ ...styles.input, height: 80, resize: 'vertical', fontFamily: 'monospace', fontSize: 12 }}
            value={payload}
            onChange={e => setPayload(e.target.value)}
          />
          <button style={styles.sendBtn} onClick={send} disabled={sending || !from || !to}>
            {sending ? 'Sending...' : '→ Send'}
          </button>
          {result && (
            <div style={{ ...styles.result, color: result.ok ? '#86efac' : '#fca5a5' }}>
              {result.text}
            </div>
          )}
        </div>

        {/* ── Flow summary ── */}
        <div style={styles.panel}>
          <h2 style={styles.panelTitle}>Message Flows</h2>
          {Object.keys(flowMap).length === 0 ? (
            <div style={styles.empty}>No IPC messages yet.</div>
          ) : (
            Object.entries(flowMap).map(([route, count]) => (
              <div key={route} style={styles.flowRow}>
                <span style={styles.route}>{route}</span>
                <span style={styles.flowCount}>{count} msg{count !== 1 ? 's' : ''}</span>
              </div>
            ))
          )}
        </div>
      </div>

      {/* ── IPC event table ── */}
      <div style={styles.eventSection}>
        <h2 style={styles.panelTitle}>Recent IPC Events</h2>
        {ipcEvents.length === 0 ? (
          <div style={styles.empty}>No IPC events yet.</div>
        ) : (
          <div style={styles.eventList}>
            {ipcEvents.slice(0, 50).map((e, i) => {
              const color = e.event_type === 'IPC_SENT'     ? '#a855f7'
                          : e.event_type === 'IPC_RECEIVED' ? '#ec4899'
                          : '#ef4444'
              return (
                <div key={e.event_id ?? i} style={styles.eventRow}>
                  <span style={{ ...styles.badge, color, borderColor: color + '44', background: color + '11' }}>
                    {e.event_type}
                  </span>
                  <span style={styles.ePid}>PID {e.process_id}</span>
                  <span style={styles.eMeta}>
                    {e.metadata?.sender_pid != null && `${pidNames[e.metadata.sender_pid] ?? e.metadata.sender_pid} → ${pidNames[e.metadata.receiver_pid] ?? e.metadata.receiver_pid}`}
                    {e.metadata?.message_id && `  id: ${e.metadata.message_id.slice(0, 8)}...`}
                  </span>
                  <span style={styles.eTs}>
                    {e.timestamp ? new Date(e.timestamp * 1000).toLocaleTimeString() : ''}
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

const styles = {
  header: { marginBottom: 20 },
  title: { fontSize: 22, fontWeight: 700, color: '#e2e8f0' },
  subtitle: { color: '#64748b', fontSize: 13 },
  grid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24 },
  panel: {
    background: '#1a1d27',
    border: '1px solid #2d3148',
    borderRadius: 10,
    padding: 20,
  },
  panelTitle: { fontSize: 14, fontWeight: 600, color: '#94a3b8', marginBottom: 16, letterSpacing: 0.5 },
  label: { display: 'block', fontSize: 12, color: '#64748b', marginBottom: 4, marginTop: 10 },
  input: {
    display: 'block',
    width: '100%',
    background: '#0f1117',
    border: '1px solid #2d3148',
    color: '#e2e8f0',
    padding: '8px 10px',
    borderRadius: 6,
    fontSize: 13,
  },
  sendBtn: {
    marginTop: 14,
    width: '100%',
    background: '#312e81',
    border: '1px solid #4338ca',
    color: '#a5b4fc',
    padding: '9px',
    borderRadius: 7,
    cursor: 'pointer',
    fontWeight: 700,
    fontSize: 14,
  },
  result: { marginTop: 10, fontSize: 12, fontFamily: 'monospace' },
  empty: { color: '#475569', fontSize: 13 },
  flowRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '8px 0',
    borderBottom: '1px solid #1e2235',
  },
  route: { color: '#a5b4fc', fontFamily: 'monospace', fontSize: 13 },
  flowCount: { color: '#64748b', fontSize: 12 },
  eventSection: {},
  eventList: { display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 340, overflowY: 'auto' },
  eventRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '7px 10px',
    background: '#1a1d27',
    borderRadius: 6,
    fontSize: 12,
  },
  badge: {
    padding: '2px 8px',
    borderRadius: 12,
    border: '1px solid',
    fontWeight: 700,
    fontSize: 11,
    whiteSpace: 'nowrap',
  },
  ePid: { color: '#818cf8', fontWeight: 600, minWidth: 50 },
  eMeta: { color: '#64748b', flex: 1, fontFamily: 'monospace' },
  eTs: { color: '#374151', fontSize: 11 },
}
