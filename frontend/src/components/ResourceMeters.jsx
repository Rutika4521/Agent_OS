import React, { useMemo } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

const STATE_COLORS = {
  READY: '#22c55e', RUNNING: '#3b82f6', WAITING: '#f59e0b',
  BLOCKED: '#f97316', COMPLETED: '#6366f1', FAILED: '#ef4444',
}

export default function ResourceMeters({ processes, metrics }) {
  // Show all processes that consumed any tokens — includes completed ones for post-demo view
  const alive = processes.filter(p =>
    (p.resource_usage?.total_tokens ?? 0) > 0 ||
    !['COMPLETED','TERMINATED','CANCELLED'].includes(p.state)
  )

  const tokenData = useMemo(() => alive.map(p => ({
    name: p.name,
    tokens: p.resource_usage?.total_tokens ?? 0,
    limit:  p.resource_limits?.token_limit ?? 5000,
    pct: Math.round(((p.resource_usage?.total_tokens ?? 0) / (p.resource_limits?.token_limit ?? 5000)) * 100),
    color: STATE_COLORS[p.state] ?? '#94a3b8',
  })), [alive])

  const stepData = useMemo(() => alive.map(p => ({
    name:  p.name,
    steps: p.resource_usage?.steps ?? 0,
    limit: p.resource_limits?.step_limit ?? 100,
    color: STATE_COLORS[p.state] ?? '#94a3b8',
  })), [alive])

  return (
    <div>
      <div style={styles.header}>
        <h1 style={styles.title}>Resource Meters</h1>
        <span style={styles.subtitle}>Token and step consumption per active process</span>
      </div>

      {alive.length === 0 ? (
        <div style={styles.empty}>No active processes.</div>
      ) : (
        <>
          {/* Per-process progress bars */}
          <section style={styles.section}>
            <h2 style={styles.sectionTitle}>Token Usage</h2>
            {tokenData.map(d => (
              <div key={d.name} style={styles.meterRow}>
                <div style={styles.meterLabel}>
                  <span style={styles.meterName}>{d.name}</span>
                  <span style={{ color: d.color }}>{d.tokens} / {d.limit}</span>
                </div>
                <div style={styles.meterTrack}>
                  <div style={{
                    ...styles.meterFill,
                    width: `${Math.min(d.pct, 100)}%`,
                    background: d.pct > 80 ? '#ef4444' : d.pct > 60 ? '#f59e0b' : d.color,
                  }} />
                </div>
                <span style={styles.meterPct}>{d.pct}%</span>
              </div>
            ))}
          </section>

          {/* Bar chart – Steps */}
          <section style={styles.section}>
            <h2 style={styles.sectionTitle}>Steps Executed</h2>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={stepData} margin={{ top: 10, right: 20, bottom: 5, left: 0 }}>
                <XAxis dataKey="name" stroke="#475569" tick={{ fontSize: 12, fill: '#94a3b8' }} />
                <YAxis stroke="#475569" tick={{ fontSize: 12, fill: '#94a3b8' }} />
                <Tooltip
                  contentStyle={{ background: '#1a1d27', border: '1px solid #2d3148', borderRadius: 8 }}
                  labelStyle={{ color: '#e2e8f0' }}
                  itemStyle={{ color: '#a5b4fc' }}
                />
                <Bar dataKey="steps" radius={[4, 4, 0, 0]}>
                  {stepData.map((d, i) => <Cell key={i} fill={d.color} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </section>

          {/* Global metrics */}
          {metrics && (
            <section style={styles.section}>
              <h2 style={styles.sectionTitle}>Global Metrics</h2>
              <div style={styles.globalGrid}>
                {Object.entries(metrics).map(([k, v]) => (
                  <div key={k} style={styles.globalCard}>
                    <div style={styles.globalValue}>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</div>
                    <div style={styles.globalKey}>{k}</div>
                  </div>
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  )
}

const styles = {
  header: { marginBottom: 20 },
  title: { fontSize: 22, fontWeight: 700, color: '#e2e8f0' },
  subtitle: { color: '#64748b', fontSize: 13 },
  empty: { color: '#475569', textAlign: 'center', padding: '60px 0' },
  section: { marginBottom: 30 },
  sectionTitle: { fontSize: 15, fontWeight: 600, color: '#94a3b8', marginBottom: 14, letterSpacing: 0.5 },
  meterRow: { display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 },
  meterLabel: { display: 'flex', justifyContent: 'space-between', width: 200, fontSize: 12 },
  meterName: { color: '#e2e8f0', fontWeight: 600 },
  meterTrack: { flex: 1, height: 10, background: '#1e293b', borderRadius: 5, overflow: 'hidden' },
  meterFill: { height: '100%', borderRadius: 5, transition: 'width 0.4s ease' },
  meterPct: { width: 40, textAlign: 'right', fontSize: 12, color: '#64748b' },
  globalGrid: { display: 'flex', flexWrap: 'wrap', gap: 12 },
  globalCard: {
    background: '#1a1d27',
    border: '1px solid #2d3148',
    borderRadius: 8,
    padding: '12px 18px',
    minWidth: 120,
  },
  globalValue: { fontSize: 20, fontWeight: 700, color: '#818cf8' },
  globalKey: { fontSize: 11, color: '#64748b', marginTop: 4 },
}
