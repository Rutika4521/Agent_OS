import React, { useMemo } from 'react'

export default function DeadlockGraph({ events, processes }) {
  const deadlockEvents = useMemo(() =>
    events.filter(e => e.event_type === 'DEADLOCK_DETECTED').slice().reverse(),
    [events]
  )

  const lockEvents = useMemo(() =>
    events.filter(e => ['LOCK_ACQUIRED','LOCK_RELEASED'].includes(e.event_type)).slice().reverse(),
    [events]
  )

  const pidNames = useMemo(() => {
    const m = {}
    processes.forEach(p => { m[p.process_id] = p.name })
    return m
  }, [processes])

  // Build current lock ownership from events
  const lockOwnership = useMemo(() => {
    const acquired = {}
    events.filter(e => e.event_type === 'LOCK_ACQUIRED').forEach(e => {
      const lid = e.metadata?.lock_id ?? 'unknown'
      acquired[lid] = e.process_id
    })
    events.filter(e => e.event_type === 'LOCK_RELEASED').forEach(e => {
      const lid = e.metadata?.lock_id ?? 'unknown'
      delete acquired[lid]
    })
    return acquired
  }, [events])

  return (
    <div>
      <div style={styles.header}>
        <h1 style={styles.title}>Deadlock Detection</h1>
        <span style={styles.subtitle}>Wait-for graph and lock ownership</span>
      </div>

      {/* Deadlock alerts */}
      <section style={styles.section}>
        <h2 style={styles.sectionTitle}>Deadlock Events</h2>
        {deadlockEvents.length === 0 ? (
          <div style={styles.noDeadlock}>✅ No deadlocks detected</div>
        ) : (
          deadlockEvents.slice(0, 10).map((e, i) => (
            <div key={e.event_id ?? i} style={styles.deadlockAlert}>
              <div style={styles.alertHeader}>
                <span style={styles.alertBadge}>🔒 DEADLOCK</span>
                <span style={styles.alertTs}>
                  {e.timestamp ? new Date(e.timestamp * 1000).toLocaleTimeString() : ''}
                </span>
              </div>
              {e.metadata?.cycle && (
                <div style={styles.cycle}>
                  Cycle: {e.metadata.cycle.map(pid =>
                    `PID ${pid} (${pidNames[pid] ?? '?'})`
                  ).join(' → ')}
                </div>
              )}
              {e.metadata?.victim_pid != null && (
                <div style={styles.victim}>
                  Victim selected: PID {e.metadata.victim_pid} ({pidNames[e.metadata.victim_pid] ?? '?'})
                </div>
              )}
            </div>
          ))
        )}
      </section>

      <div style={styles.grid}>
        {/* Lock ownership */}
        <section style={styles.panel}>
          <h2 style={styles.sectionTitle}>Current Lock Owners</h2>
          {Object.keys(lockOwnership).length === 0 ? (
            <div style={styles.empty}>No locks currently held.</div>
          ) : (
            Object.entries(lockOwnership).map(([lid, pid]) => (
              <div key={lid} style={styles.lockRow}>
                <span style={styles.lockId}>🔑 {lid}</span>
                <span style={styles.lockOwner}>
                  PID {pid} — {pidNames[pid] ?? 'unknown'}
                </span>
              </div>
            ))
          )}
        </section>

        {/* Recent lock events */}
        <section style={styles.panel}>
          <h2 style={styles.sectionTitle}>Recent Lock Events</h2>
          {lockEvents.length === 0 ? (
            <div style={styles.empty}>No lock events yet.</div>
          ) : (
            <div style={styles.lockList}>
              {lockEvents.slice(0, 20).map((e, i) => {
                const acquired = e.event_type === 'LOCK_ACQUIRED'
                return (
                  <div key={e.event_id ?? i} style={styles.lockEvent}>
                    <span style={{ color: acquired ? '#22c55e' : '#64748b', fontWeight: 700, fontSize: 11 }}>
                      {acquired ? '🔒 ACQUIRED' : '🔓 RELEASED'}
                    </span>
                    <span style={styles.lePid}>PID {e.process_id}</span>
                    <span style={styles.leMeta}>
                      {e.metadata?.lock_id ?? ''}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </section>
      </div>

      {/* Wait-for graph explanation */}
      <section style={styles.panel}>
        <h2 style={styles.sectionTitle}>How Deadlock Detection Works</h2>
        <div style={styles.explainer}>
          <div style={styles.step}>
            <span style={styles.stepNum}>1</span>
            <span>When a process tries to acquire a lock held by another, a <strong>wait-for edge</strong> is added to the graph: <code>waiter → holder</code></span>
          </div>
          <div style={styles.step}>
            <span style={styles.stepNum}>2</span>
            <span>After every lock acquisition attempt, Agent-OS runs <strong>DFS cycle detection</strong> on the wait-for graph.</span>
          </div>
          <div style={styles.step}>
            <span style={styles.stepNum}>3</span>
            <span>If a cycle is found → <strong>deadlock detected</strong>. The <strong>lowest-priority process</strong> in the cycle is chosen as the victim.</span>
          </div>
          <div style={styles.step}>
            <span style={styles.stepNum}>4</span>
            <span>The victim's locks are released and it is moved to <strong>FAILED</strong> state. The Supervisor can then restart it.</span>
          </div>
        </div>
      </section>
    </div>
  )
}

const styles = {
  header: { marginBottom: 20 },
  title: { fontSize: 22, fontWeight: 700, color: '#e2e8f0' },
  subtitle: { color: '#64748b', fontSize: 13 },
  section: { marginBottom: 24 },
  sectionTitle: { fontSize: 14, fontWeight: 600, color: '#94a3b8', marginBottom: 12, letterSpacing: 0.5 },
  noDeadlock: {
    background: '#052e16',
    border: '1px solid #166534',
    color: '#86efac',
    padding: '14px 18px',
    borderRadius: 8,
    fontWeight: 600,
  },
  deadlockAlert: {
    background: '#450a0a',
    border: '1px solid #7f1d1d',
    borderRadius: 8,
    padding: '14px 18px',
    marginBottom: 10,
  },
  alertHeader: { display: 'flex', justifyContent: 'space-between', marginBottom: 8 },
  alertBadge: { color: '#fca5a5', fontWeight: 700 },
  alertTs: { color: '#64748b', fontSize: 12 },
  cycle: { color: '#fca5a5', fontSize: 13, fontFamily: 'monospace' },
  victim: { color: '#f97316', fontSize: 12, marginTop: 6 },
  grid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24 },
  panel: {
    background: '#1a1d27',
    border: '1px solid #2d3148',
    borderRadius: 10,
    padding: 20,
    marginBottom: 16,
  },
  empty: { color: '#475569', fontSize: 13 },
  lockRow: {
    display: 'flex',
    justifyContent: 'space-between',
    padding: '8px 0',
    borderBottom: '1px solid #1e2235',
    fontSize: 13,
  },
  lockId: { color: '#f59e0b', fontFamily: 'monospace' },
  lockOwner: { color: '#818cf8' },
  lockList: { display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 240, overflowY: 'auto' },
  lockEvent: {
    display: 'flex',
    gap: 10,
    padding: '6px 8px',
    background: '#0f1117',
    borderRadius: 5,
    fontSize: 12,
  },
  lePid: { color: '#818cf8', fontWeight: 600 },
  leMeta: { color: '#64748b', fontFamily: 'monospace' },
  explainer: { display: 'flex', flexDirection: 'column', gap: 12 },
  step: { display: 'flex', gap: 12, alignItems: 'flex-start', fontSize: 13, color: '#94a3b8' },
  stepNum: {
    background: '#312e81',
    color: '#a5b4fc',
    width: 24,
    height: 24,
    borderRadius: '50%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontWeight: 700,
    fontSize: 12,
    flexShrink: 0,
  },
}
