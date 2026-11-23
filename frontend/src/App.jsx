import React, { useState, useEffect, useCallback, useRef } from 'react'
import { api } from './api.js'
import ProcessTable from './components/ProcessTable.jsx'
import EventLog from './components/EventLog.jsx'
import ResourceMeters from './components/ResourceMeters.jsx'
import IPCPanel from './components/IPCPanel.jsx'
import DeadlockGraph from './components/DeadlockGraph.jsx'
import SchedulerTimeline from './components/SchedulerTimeline.jsx'

const POLL_IDLE_MS    = 2000   // poll interval when demo is idle
const POLL_RUNNING_MS = 600    // faster poll when demo is live

const NAV = [
  { id: 'processes', label: '⚙️  Processes'  },
  { id: 'scheduler', label: '📅  Scheduler'  },
  { id: 'ipc',       label: '📨  IPC'        },
  { id: 'resources', label: '📊  Resources'  },
  { id: 'deadlock',  label: '🔒  Deadlock'   },
  { id: 'events',    label: '📋  Events'     },
]

const DEMO_STATUS_COLORS = {
  idle:    '#64748b',
  running: '#22c55e',
  done:    '#6366f1',
  error:   '#ef4444',
}

const DEMO_STATUS_LABELS = {
  idle:    '⬤  Idle — click ▶ Run Demo to start',
  running: '⬤  Demo Running…',
  done:    '⬤  Demo Complete',
  error:   '⬤  Demo Error',
}

export default function App() {
  const [tab,        setTab]        = useState('processes')
  const [processes,  setProcesses]  = useState([])
  const [events,     setEvents]     = useState([])
  const [metrics,    setMetrics]    = useState(null)
  const [health,     setHealth]     = useState(null)
  const [demoStatus, setDemoStatus] = useState('idle')
  const [error,      setError]      = useState(null)
  const [lastTick,   setLastTick]   = useState(null)
  const [demoMsg,    setDemoMsg]    = useState(null)
  const pollRef = useRef(null)

  const refresh = useCallback(async () => {
    try {
      const [procs, evts, met, hlt] = await Promise.all([
        api.getProcesses().catch(() => []),
        api.getEvents('?limit=500').catch(() => []),
        api.getMetrics().catch(() => null),
        api.getHealth().catch(() => null),
      ])
      setProcesses(Array.isArray(procs) ? procs : [])
      setEvents(Array.isArray(evts) ? evts : [])
      setMetrics(met)
      setHealth(hlt)
      if (met?.demo_status) setDemoStatus(met.demo_status)
      setError(null)
      setLastTick(new Date().toLocaleTimeString())
    } catch (e) {
      setError(e.message)
    }
  }, [])

  // Adaptive polling: fast when running, slow otherwise
  const startPolling = useCallback((fast = false) => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(refresh, fast ? POLL_RUNNING_MS : POLL_IDLE_MS)
  }, [refresh])

  useEffect(() => {
    refresh()
    startPolling(false)
    return () => clearInterval(pollRef.current)
  }, [refresh, startPolling])

  // Speed up polling while demo is running
  useEffect(() => {
    if (demoStatus === 'running') {
      startPolling(true)
    } else {
      startPolling(false)
    }
  }, [demoStatus, startPolling])

  async function handleRunDemo() {
    setDemoMsg(null)
    try {
      const r = await api.runDemo()
      setDemoStatus('running')
      setDemoMsg({ ok: true, text: r.message })
      startPolling(true)
    } catch (e) {
      setDemoMsg({ ok: false, text: e.message })
    }
  }

  async function handleResetDemo() {
    setDemoMsg(null)
    try {
      const r = await api.resetDemo()
      setDemoStatus('idle')
      setDemoMsg({ ok: true, text: r.message })
      await refresh()
    } catch (e) {
      setDemoMsg({ ok: false, text: e.message })
    }
  }

  const activeCount    = processes.filter(p => ['READY','RUNNING','WAITING','BLOCKED'].includes(p.state)).length
  const doneCount      = processes.filter(p => ['COMPLETED','TERMINATED','CANCELLED'].includes(p.state)).length
  const totalTokens    = processes.reduce((s, p) => s + (p.resource_usage?.total_tokens ?? 0), 0)
  const failedCount    = processes.filter(p => p.state === 'FAILED').length
  const restartedCount = processes.filter(p => (p.restart_count ?? 0) > 0).length

  return (
    <div style={s.root}>
      {/* ── Sidebar ── */}
      <aside style={s.sidebar}>
        <div style={s.logo}>
          <span style={s.logoIcon}>🖥️</span>
          <span style={s.logoText}>Agent-OS</span>
        </div>

        {/* Kernel status */}
        <div style={s.statusRow}>
          <span style={{ ...s.dot, background: health ? '#22c55e' : '#ef4444' }} />
          <span style={s.statusText}>{health ? 'Kernel Online' : 'Offline'}</span>
        </div>

        {/* Demo status */}
        <div style={{ ...s.demoStatus, color: DEMO_STATUS_COLORS[demoStatus] ?? '#64748b' }}>
          {DEMO_STATUS_LABELS[demoStatus] ?? demoStatus}
        </div>

        {/* Demo controls */}
        <div style={s.demoControls}>
          <button
            style={{
              ...s.demoBtn,
              background: demoStatus === 'running' ? '#052e16' : '#14532d',
              borderColor: demoStatus === 'running' ? '#166534' : '#16a34a',
              opacity: demoStatus === 'running' ? 0.6 : 1,
              cursor: demoStatus === 'running' ? 'wait' : 'pointer',
            }}
            onClick={handleRunDemo}
            disabled={demoStatus === 'running'}
          >
            {demoStatus === 'running' ? '⏳ Running…' : '▶  Run Demo'}
          </button>
          <button
            style={{ ...s.demoBtn, background: '#1e293b', borderColor: '#334155', color: '#94a3b8', marginTop: 6 }}
            onClick={handleResetDemo}
            disabled={demoStatus === 'running'}
          >
            ↺  Reset
          </button>
        </div>

        {demoMsg && (
          <div style={{ ...s.demoMsg, color: demoMsg.ok ? '#86efac' : '#fca5a5' }}>
            {demoMsg.text}
          </div>
        )}

        {/* Nav */}
        <nav style={s.nav}>
          {NAV.map(n => (
            <button
              key={n.id}
              style={{ ...s.navBtn, ...(tab === n.id ? s.navBtnActive : {}) }}
              onClick={() => setTab(n.id)}
            >
              {n.label}
            </button>
          ))}
        </nav>

        {/* Footer stats */}
        <div style={s.footer}>
          {[
            ['Processes',  processes.length],
            ['Active',     activeCount],
            ['Done',       doneCount],
            ['Events',     events.length],
            ['Tokens',     totalTokens.toLocaleString()],
            ['Restarts',   restartedCount],
          ].map(([label, val]) => (
            <div key={label} style={s.metaRow}>
              <span>{label}</span>
              <span style={s.badge}>{val}</span>
            </div>
          ))}
          {lastTick && <div style={s.tick}>Synced {lastTick}</div>}
          <button style={s.refreshBtn} onClick={refresh}>↺ Refresh</button>
        </div>
      </aside>

      {/* ── Main ── */}
      <main style={s.main}>
        {error && (
          <div style={s.errorBanner}>
            ⚠️ Cannot reach Agent-OS API — run <code>python run.py server</code> on port 8000. ({error})
          </div>
        )}

        {/* Demo running ticker */}
        {demoStatus === 'running' && (
          <div style={s.runningBanner}>
            <span style={s.pulse}>●</span>
            &nbsp; Demo pipeline running — agents are being scheduled, IPC messages flowing, resources consumed…
            &nbsp; <span style={{ color: '#86efac' }}>{processes.length} processes</span>
            &nbsp;|&nbsp;
            <span style={{ color: '#a5b4fc' }}>{events.length} events</span>
            &nbsp;|&nbsp;
            <span style={{ color: '#fcd34d' }}>{totalTokens.toLocaleString()} tokens</span>
          </div>
        )}

        {demoStatus === 'done' && processes.length > 0 && (
          <div style={s.doneBanner}>
            ✅ Pipeline complete — {processes.length} processes ran,&nbsp;
            {totalTokens.toLocaleString()} tokens consumed,&nbsp;
            {restartedCount} agent(s) restarted by Supervisor,&nbsp;
            {events.length} events logged.
            Explore all tabs to see the results.
          </div>
        )}

        {tab === 'processes' && <ProcessTable processes={processes} onRefresh={refresh} />}
        {tab === 'scheduler' && <SchedulerTimeline events={events} processes={processes} />}
        {tab === 'ipc'       && <IPCPanel events={events} processes={processes} />}
        {tab === 'resources' && <ResourceMeters processes={processes} metrics={metrics} />}
        {tab === 'deadlock'  && <DeadlockGraph events={events} processes={processes} />}
        {tab === 'events'    && <EventLog events={events} />}
      </main>
    </div>
  )
}

const s = {
  root: { display: 'flex', minHeight: '100vh', background: '#0f1117', color: '#e2e8f0' },
  sidebar: {
    width: 230,
    background: '#1a1d27',
    borderRight: '1px solid #2d3148',
    display: 'flex',
    flexDirection: 'column',
    padding: '20px 0',
    flexShrink: 0,
  },
  logo: {
    display: 'flex', alignItems: 'center', gap: 10,
    padding: '0 20px 16px', borderBottom: '1px solid #2d3148',
  },
  logoIcon: { fontSize: 22 },
  logoText: { fontSize: 17, fontWeight: 700, color: '#818cf8' },
  statusRow: {
    display: 'flex', alignItems: 'center', gap: 8, padding: '12px 20px 4px',
  },
  dot: { width: 8, height: 8, borderRadius: '50%', display: 'inline-block', flexShrink: 0 },
  statusText: { fontSize: 12, color: '#94a3b8' },
  demoStatus: {
    fontSize: 11, padding: '4px 20px 10px', fontWeight: 600, letterSpacing: 0.3,
  },
  demoControls: { padding: '0 12px 8px' },
  demoBtn: {
    width: '100%', border: '1px solid', borderRadius: 7,
    color: '#86efac', padding: '9px', fontWeight: 700, fontSize: 13,
  },
  demoMsg: { padding: '0 16px 10px', fontSize: 11, fontFamily: 'monospace', lineHeight: 1.4 },
  nav: {
    display: 'flex', flexDirection: 'column', gap: 2,
    padding: '8px 10px', flex: 1,
  },
  navBtn: {
    background: 'none', border: 'none', color: '#94a3b8',
    textAlign: 'left', padding: '9px 14px', borderRadius: 8,
    cursor: 'pointer', fontSize: 13, fontWeight: 500,
  },
  navBtnActive: { background: '#312e81', color: '#a5b4fc' },
  footer: {
    padding: '14px 20px', borderTop: '1px solid #2d3148',
    fontSize: 12, color: '#64748b',
  },
  metaRow: {
    display: 'flex', justifyContent: 'space-between', marginBottom: 5,
  },
  badge: {
    background: '#1e293b', color: '#a5b4fc',
    borderRadius: 10, padding: '1px 8px', fontSize: 11,
  },
  tick: { color: '#374151', fontSize: 11, marginTop: 6, marginBottom: 8 },
  refreshBtn: {
    width: '100%', background: '#1e293b', border: '1px solid #334155',
    color: '#94a3b8', padding: '7px', borderRadius: 6, cursor: 'pointer', fontSize: 12,
  },
  main: { flex: 1, overflow: 'auto', padding: 24 },
  errorBanner: {
    background: '#450a0a', border: '1px solid #7f1d1d', color: '#fca5a5',
    padding: '10px 16px', borderRadius: 8, marginBottom: 16, fontSize: 13,
  },
  runningBanner: {
    background: '#052e16', border: '1px solid #166534', color: '#86efac',
    padding: '10px 16px', borderRadius: 8, marginBottom: 16, fontSize: 13,
    display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 4,
  },
  doneBanner: {
    background: '#1e1b4b', border: '1px solid #4338ca', color: '#c7d2fe',
    padding: '10px 16px', borderRadius: 8, marginBottom: 16, fontSize: 13,
  },
  pulse: {
    color: '#22c55e',
    animation: 'pulse 1s infinite',
    fontSize: 16,
  },
}
