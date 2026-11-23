import React, { useMemo, useState } from 'react'

const EVENT_COLORS = {
  PROCESS_CREATED:   '#0ea5e9',
  PROCESS_READY:     '#22c55e',
  PROCESS_STARTED:   '#3b82f6',
  PROCESS_WAITING:   '#f59e0b',
  PROCESS_BLOCKED:   '#f97316',
  PROCESS_COMPLETED: '#6366f1',
  PROCESS_FAILED:    '#ef4444',
  PROCESS_CANCELLED: '#64748b',
  PROCESS_TERMINATED:'#374151',
  IPC_SENT:          '#a855f7',
  IPC_RECEIVED:      '#ec4899',
  IPC_DROPPED:       '#dc2626',
  CONTEXT_SWAP_OUT:  '#84cc16',
  CONTEXT_SWAP_IN:   '#10b981',
  CHECKPOINT_CREATED:'#f59e0b',
  DEADLOCK_DETECTED: '#ef4444',
  RESTART_STARTED:   '#a855f7',
  RESTART_COMPLETED: '#22c55e',
  LOCK_ACQUIRED:     '#38bdf8',
  LOCK_RELEASED:     '#64748b',
}

const ALL = '__ALL__'

export default function EventLog({ events }) {
  const [filter, setFilter]   = useState(ALL)
  const [pidFilter, setPid]   = useState('')
  const [search, setSearch]   = useState('')

  const types = useMemo(() => {
    const s = new Set(events.map(e => e.event_type))
    return [ALL, ...Array.from(s).sort()]
  }, [events])

  const filtered = useMemo(() => {
    return [...events]
      .reverse()
      .filter(e => {
        if (filter !== ALL && e.event_type !== filter) return false
        if (pidFilter && String(e.process_id) !== pidFilter) return false
        if (search && !JSON.stringify(e).toLowerCase().includes(search.toLowerCase())) return false
        return true
      })
  }, [events, filter, pidFilter, search])

  return (
    <div>
      <div style={styles.header}>
        <h1 style={styles.title}>Event Log</h1>
        <span style={styles.subtitle}>{events.length} events total</span>
      </div>

      {/* Filters */}
      <div style={styles.filters}>
        <select style={styles.select} value={filter} onChange={e => setFilter(e.target.value)}>
          {types.map(t => <option key={t} value={t}>{t === ALL ? 'All Types' : t}</option>)}
        </select>
        <input
          style={styles.input}
          placeholder="Filter by PID..."
          value={pidFilter}
          onChange={e => setPid(e.target.value)}
        />
        <input
          style={styles.input}
          placeholder="Search..."
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <span style={styles.count}>{filtered.length} shown</span>
      </div>

      {/* Events list */}
      <div style={styles.list}>
        {filtered.length === 0 ? (
          <div style={styles.empty}>No events yet. Run the demo to generate events.</div>
        ) : (
          filtered.map((ev, i) => {
            const color = EVENT_COLORS[ev.event_type] ?? '#94a3b8'
            const ts = ev.timestamp
              ? new Date(ev.timestamp * 1000).toLocaleTimeString()
              : '—'
            return (
              <div key={ev.event_id ?? i} style={styles.row}>
                <span style={styles.ts}>{ts}</span>
                <span style={{ ...styles.type, color, borderColor: color + '44', background: color + '11' }}>
                  {ev.event_type}
                </span>
                <span style={styles.pid}>
                  {ev.process_id != null ? `PID ${ev.process_id}` : '—'}
                </span>
                <span style={styles.meta}>
                  {ev.metadata && Object.keys(ev.metadata).length > 0
                    ? Object.entries(ev.metadata)
                        .filter(([, v]) => v != null)
                        .map(([k, v]) => `${k}: ${JSON.stringify(v)}`)
                        .join('  •  ')
                    : ''}
                </span>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}

const styles = {
  header: { marginBottom: 16 },
  title: { fontSize: 22, fontWeight: 700, color: '#e2e8f0' },
  subtitle: { color: '#64748b', fontSize: 13 },
  filters: {
    display: 'flex',
    gap: 10,
    marginBottom: 16,
    flexWrap: 'wrap',
    alignItems: 'center',
  },
  select: {
    background: '#1a1d27',
    border: '1px solid #2d3148',
    color: '#e2e8f0',
    padding: '7px 10px',
    borderRadius: 6,
    fontSize: 13,
  },
  input: {
    background: '#1a1d27',
    border: '1px solid #2d3148',
    color: '#e2e8f0',
    padding: '7px 10px',
    borderRadius: 6,
    fontSize: 13,
    width: 150,
  },
  count: { color: '#475569', fontSize: 12 },
  list: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
    maxHeight: 'calc(100vh - 240px)',
    overflowY: 'auto',
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '7px 12px',
    background: '#1a1d27',
    borderRadius: 6,
    border: '1px solid #1e2235',
    fontSize: 12,
    flexWrap: 'wrap',
  },
  ts: { color: '#475569', minWidth: 75, fontFamily: 'monospace' },
  type: {
    padding: '2px 8px',
    borderRadius: 12,
    border: '1px solid',
    fontWeight: 700,
    fontSize: 11,
    letterSpacing: 0.3,
    whiteSpace: 'nowrap',
  },
  pid: { color: '#818cf8', fontWeight: 600, minWidth: 50 },
  meta: { color: '#64748b', flex: 1, fontFamily: 'monospace' },
  empty: { color: '#475569', textAlign: 'center', padding: '40px 0' },
}
