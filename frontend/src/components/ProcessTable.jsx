import React, { useState } from 'react'
import { api } from '../api.js'

const STATE_COLORS = {
  READY:      '#22c55e',
  RUNNING:    '#3b82f6',
  WAITING:    '#f59e0b',
  BLOCKED:    '#f97316',
  COMPLETED:  '#6366f1',
  FAILED:     '#ef4444',
  RESTARTING: '#a855f7',
  CANCELLING: '#ec4899',
  CANCELLED:  '#64748b',
  TERMINATED: '#374151',
  CREATED:    '#0ea5e9',
}

export default function ProcessTable({ processes, onRefresh }) {
  const [spawning, setSpawning] = useState(false)
  const [actionPid, setActionPid] = useState(null)
  const [msg, setMsg] = useState(null)

  async function doAction(pid, action) {
    setActionPid(pid)
    try {
      if (action === 'cancel') await api.cancelProcess(pid)
      if (action === 'pause')  await api.pauseProcess(pid)
      if (action === 'resume') await api.resumeProcess(pid)
      setMsg({ ok: true, text: `PID ${pid} → ${action} done` })
      onRefresh()
    } catch (e) {
      setMsg({ ok: false, text: e.message })
    } finally {
      setActionPid(null)
    }
  }

  const ready   = processes.filter(p => p.state === 'READY').length
  const running = processes.filter(p => p.state === 'RUNNING').length
  const waiting = processes.filter(p => p.state === 'WAITING').length
  const done    = processes.filter(p => ['COMPLETED','TERMINATED','CANCELLED'].includes(p.state)).length

  return (
    <div>
      <div style={styles.header}>
        <h1 style={styles.title}>Process Table</h1>
        <span style={styles.subtitle}>Live snapshot of all Agent-OS processes</span>
      </div>

      {/* ── Summary cards ── */}
      <div style={styles.cards}>
        {[
          { label: 'READY',   value: ready,   color: '#22c55e' },
          { label: 'RUNNING', value: running, color: '#3b82f6' },
          { label: 'WAITING', value: waiting, color: '#f59e0b' },
          { label: 'DONE',    value: done,    color: '#6366f1' },
          { label: 'TOTAL',   value: processes.length, color: '#94a3b8' },
        ].map(c => (
          <div key={c.label} style={styles.card}>
            <div style={{ ...styles.cardValue, color: c.color }}>{c.value}</div>
            <div style={styles.cardLabel}>{c.label}</div>
          </div>
        ))}
      </div>

      {msg && (
        <div style={{ ...styles.msg, background: msg.ok ? '#052e16' : '#450a0a',
                      borderColor: msg.ok ? '#166534' : '#7f1d1d',
                      color: msg.ok ? '#86efac' : '#fca5a5' }}>
          {msg.text}
        </div>
      )}

      {processes.length === 0 ? (
        <div style={styles.empty}>No processes — start the demo or spawn an agent via the API.</div>
      ) : (
        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>
                {['PID','Name','State','Priority','Steps','Tokens','Wait Reason','Actions'].map(h => (
                  <th key={h} style={styles.th}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {processes.map(p => (
                <tr key={p.process_id ?? p.pid} style={styles.tr}>
                  <td style={styles.td}><span style={styles.pid}>#{p.process_id ?? p.pid}</span></td>
                  <td style={styles.td}>{p.name}</td>
                  <td style={styles.td}>
                    <span style={{
                      ...styles.stateBadge,
                      background: (STATE_COLORS[p.state] ?? '#475569') + '22',
                      color: STATE_COLORS[p.state] ?? '#94a3b8',
                      borderColor: STATE_COLORS[p.state] ?? '#475569',
                    }}>
                      {p.state}
                    </span>
                  </td>
                  <td style={{ ...styles.td, textAlign: 'center' }}>{p.priority}</td>
                  <td style={{ ...styles.td, textAlign: 'center' }}>{p.resource_usage?.steps ?? 0}</td>
                  <td style={{ ...styles.td, textAlign: 'center' }}>{p.resource_usage?.total_tokens ?? 0}</td>
                  <td style={{ ...styles.td, color: '#f59e0b', fontSize: 12 }}>{p.waiting_for ?? '—'}</td>
                  <td style={styles.td}>
                    <div style={styles.actions}>
                      {p.state === 'RUNNING' && (
                        <Btn label="Pause"  color="#f59e0b" onClick={() => doAction(p.process_id, 'pause')}  loading={actionPid === p.process_id} />
                      )}
                      {p.state === 'WAITING' && (
                        <Btn label="Resume" color="#22c55e" onClick={() => doAction(p.process_id, 'resume')} loading={actionPid === p.process_id} />
                      )}
                      {['READY','RUNNING','WAITING'].includes(p.state) && (
                        <Btn label="Cancel" color="#ef4444" onClick={() => doAction(p.process_id, 'cancel')} loading={actionPid === p.process_id} />
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function Btn({ label, color, onClick, loading }) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      style={{
        background: color + '22',
        border: `1px solid ${color}`,
        color,
        padding: '3px 10px',
        borderRadius: 5,
        cursor: loading ? 'wait' : 'pointer',
        fontSize: 11,
        fontWeight: 600,
        marginRight: 4,
      }}
    >
      {loading ? '...' : label}
    </button>
  )
}

const styles = {
  header: { marginBottom: 20 },
  title: { fontSize: 22, fontWeight: 700, color: '#e2e8f0' },
  subtitle: { color: '#64748b', fontSize: 13 },
  cards: { display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' },
  card: {
    background: '#1a1d27',
    border: '1px solid #2d3148',
    borderRadius: 10,
    padding: '14px 20px',
    minWidth: 90,
    textAlign: 'center',
  },
  cardValue: { fontSize: 28, fontWeight: 700 },
  cardLabel: { fontSize: 11, color: '#64748b', marginTop: 4, letterSpacing: 1 },
  msg: {
    border: '1px solid',
    borderRadius: 6,
    padding: '8px 14px',
    fontSize: 13,
    marginBottom: 14,
  },
  empty: { color: '#475569', textAlign: 'center', padding: '60px 0', fontSize: 15 },
  tableWrap: { overflowX: 'auto' },
  table: { width: '100%', borderCollapse: 'collapse' },
  th: {
    textAlign: 'left',
    padding: '10px 14px',
    background: '#1a1d27',
    color: '#64748b',
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: 1,
    borderBottom: '1px solid #2d3148',
  },
  tr: { borderBottom: '1px solid #1e2235' },
  td: { padding: '10px 14px', fontSize: 13, verticalAlign: 'middle' },
  pid: { color: '#818cf8', fontWeight: 700 },
  stateBadge: {
    display: 'inline-block',
    padding: '2px 10px',
    borderRadius: 20,
    fontSize: 11,
    fontWeight: 700,
    border: '1px solid',
    letterSpacing: 0.5,
  },
  actions: { display: 'flex', alignItems: 'center' },
}
