import React, { useMemo } from 'react'

const STATE_COLORS = {
  READY: '#22c55e', RUNNING: '#3b82f6', WAITING: '#f59e0b',
  BLOCKED: '#f97316', COMPLETED: '#6366f1', FAILED: '#ef4444',
  RESTARTING: '#a855f7', CANCELLING: '#ec4899',
  CANCELLED: '#64748b', TERMINATED: '#374151', CREATED: '#0ea5e9',
}

// Maps event type → process state column
const EVENT_TO_STATE = {
  PROCESS_READY:     'READY',
  PROCESS_STARTED:   'RUNNING',
  PROCESS_WAITING:   'WAITING',
  PROCESS_BLOCKED:   'BLOCKED',
  PROCESS_COMPLETED: 'COMPLETED',
  PROCESS_FAILED:    'FAILED',
  RESTART_STARTED:   'RESTARTING',
  RESTART_COMPLETED: 'READY',
}

export default function SchedulerTimeline({ events, processes }) {
  const pidNames = useMemo(() => {
    const m = {}
    processes.forEach(p => { m[p.process_id] = p.name })
    return m
  }, [processes])

  // Build timeline: one row per PID, columns = time-ordered ticks
  const timeline = useMemo(() => {
    const pids = [...new Set(events.filter(e => e.process_id != null).map(e => e.process_id))].sort((a,b)=>a-b)
    const lifecycleEvents = events.filter(e => EVENT_TO_STATE[e.event_type])
    const ticks = lifecycleEvents.slice(0, 60)

    const rows = pids.map(pid => {
      let currentState = 'CREATED'
      const cells = ticks.map(ev => {
        if (ev.process_id === pid && EVENT_TO_STATE[ev.event_type]) {
          currentState = EVENT_TO_STATE[ev.event_type]
        }
        return currentState
      })
      return { pid, name: pidNames[pid] ?? `PID ${pid}`, cells }
    })

    return { rows, ticks }
  }, [events, pidNames])

  // Scheduling stats
  const runCounts = useMemo(() => {
    const counts = {}
    events.filter(e => e.event_type === 'PROCESS_STARTED').forEach(e => {
      counts[e.process_id] = (counts[e.process_id] ?? 0) + 1
    })
    return counts
  }, [events])

  if (timeline.rows.length === 0) {
    return (
      <div>
        <div style={styles.header}>
          <h1 style={styles.title}>Scheduler Timeline</h1>
          <span style={styles.subtitle}>Visual timeline of which agent was scheduled each tick</span>
        </div>
        <div style={styles.empty}>No scheduling events yet. Run the demo first.</div>
      </div>
    )
  }

  return (
    <div>
      <div style={styles.header}>
        <h1 style={styles.title}>Scheduler Timeline</h1>
        <span style={styles.subtitle}>State transitions over time — each column is one event tick</span>
      </div>

      {/* Gantt-style grid */}
      <div style={styles.tableWrap}>
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.thName}>Agent</th>
              {timeline.ticks.map((_, i) => (
                <th key={i} style={styles.thTick}>{i + 1}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {timeline.rows.map(row => (
              <tr key={row.pid}>
                <td style={styles.tdName}>
                  <span style={styles.agentPid}>#{row.pid}</span> {row.name}
                </td>
                {row.cells.map((state, i) => (
                  <td key={i} style={{
                    ...styles.cell,
                    background: (STATE_COLORS[state] ?? '#1e293b') + '33',
                    borderColor: (STATE_COLORS[state] ?? '#2d3148') + '66',
                  }}
                    title={state}
                  />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div style={styles.legend}>
        {Object.entries(STATE_COLORS).map(([state, color]) => (
          <div key={state} style={styles.legendItem}>
            <div style={{ width: 12, height: 12, borderRadius: 3, background: color }} />
            <span style={{ fontSize: 11, color: '#94a3b8' }}>{state}</span>
          </div>
        ))}
      </div>

      {/* Run counts */}
      <div style={styles.statsSection}>
        <h2 style={styles.sectionTitle}>Times Scheduled (RUNNING)</h2>
        <div style={styles.statsGrid}>
          {Object.entries(runCounts).sort((a,b)=>b[1]-a[1]).map(([pid, count]) => (
            <div key={pid} style={styles.statCard}>
              <div style={styles.statValue}>{count}</div>
              <div style={styles.statLabel}>
                #{pid} {pidNames[pid] ?? ''}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

const styles = {
  header: { marginBottom: 20 },
  title: { fontSize: 22, fontWeight: 700, color: '#e2e8f0' },
  subtitle: { color: '#64748b', fontSize: 13 },
  empty: { color: '#475569', textAlign: 'center', padding: '60px 0' },
  tableWrap: { overflowX: 'auto', marginBottom: 16 },
  table: { borderCollapse: 'collapse', fontSize: 12 },
  thName: {
    padding: '8px 14px',
    background: '#1a1d27',
    color: '#64748b',
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: 1,
    borderBottom: '1px solid #2d3148',
    whiteSpace: 'nowrap',
    textAlign: 'left',
  },
  thTick: {
    padding: '6px 3px',
    background: '#1a1d27',
    color: '#374151',
    fontSize: 10,
    textAlign: 'center',
    borderBottom: '1px solid #2d3148',
    minWidth: 18,
  },
  tdName: {
    padding: '7px 14px',
    whiteSpace: 'nowrap',
    color: '#94a3b8',
    fontSize: 12,
    borderBottom: '1px solid #1e2235',
  },
  agentPid: { color: '#818cf8', fontWeight: 700 },
  cell: {
    width: 18,
    height: 28,
    border: '1px solid',
    transition: 'background 0.2s',
  },
  legend: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 12,
    marginBottom: 24,
  },
  legendItem: { display: 'flex', alignItems: 'center', gap: 5 },
  statsSection: { marginTop: 8 },
  sectionTitle: { fontSize: 14, fontWeight: 600, color: '#94a3b8', marginBottom: 12 },
  statsGrid: { display: 'flex', flexWrap: 'wrap', gap: 12 },
  statCard: {
    background: '#1a1d27',
    border: '1px solid #2d3148',
    borderRadius: 8,
    padding: '12px 18px',
    textAlign: 'center',
    minWidth: 100,
  },
  statValue: { fontSize: 28, fontWeight: 700, color: '#3b82f6' },
  statLabel: { fontSize: 11, color: '#64748b', marginTop: 4 },
}
