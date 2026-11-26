import React, { useState } from 'react'

const OUTCOME = {
  PASS:  { color: '#22c55e', bg: '#052e16', label: 'PASS' },
  FAIL:  { color: '#ef4444', bg: '#450a0a', label: 'FAIL' },
  KNOWN: { color: '#f59e0b', bg: '#451a03', label: 'KNOWN BUG' },
  XPASS: { color: '#f59e0b', bg: '#451a03', label: 'BUG FIXED?' },
}

export default function Scorecard({ report }) {
  const [open, setOpen] = useState(null)

  if (!report || report.status === 'idle') {
    return (
      <div style={s.empty}>
        🛰 Click <b>▶ Run Demo</b> to launch the Orbital Research Lab: 9 missions, each on its own
        native <code>agent_os.Kernel</code>, ~110 agents and 62 scenarios covering every Agent-OS
        capability and edge case. Results stream in here mission by mission.
      </div>
    )
  }
  if (report.status === 'error') {
    return <div style={{ ...s.empty, color: '#fca5a5' }}>Demo error: {report.error}</div>
  }

  const rows = report.scenarios ?? []
  const counts = report.counts ?? {}
  const byMission = rows.reduce((m, r) => {
    (m[r.mission] = m[r.mission] || { title: r.mission_title, rows: [] }).rows.push(r)
    return m
  }, {})

  return (
    <div>
      <div style={s.header}>
        <h2 style={s.h2}>🛰 Orbital Research Lab — scorecard</h2>
        <div style={s.sub}>
          {report.status === 'running'
            ? <>Running <b style={{ color: '#86efac' }}>{report.current_mission}</b> — </>
            : <>Finished in {report.elapsed_s}s — </>}
          {(report.missions_done ?? []).length}/{report.missions_total} missions,&nbsp;
          {rows.length}/{report.scenarios_total} scenarios verified
        </div>
        <div style={s.counts}>
          {['PASS', 'FAIL', 'KNOWN'].map(k => (
            <span key={k} style={{ ...s.count, color: OUTCOME[k].color, background: OUTCOME[k].bg }}>
              {counts[k] ?? 0} {OUTCOME[k].label.toLowerCase()}
            </span>
          ))}
        </div>
      </div>

      {Object.entries(byMission).map(([mid, m]) => {
        const passed = m.rows.filter(r => r.outcome === 'PASS').length
        return (
          <div key={mid} style={s.mission}>
            <div style={s.missionTitle}>
              {mid} · {m.title}
              <span style={{ color: passed === m.rows.length ? '#22c55e' : '#f59e0b', marginLeft: 10 }}>
                {passed}/{m.rows.length}
              </span>
            </div>
            {m.rows.map(r => {
              const o = OUTCOME[r.outcome] ?? OUTCOME.FAIL
              const isOpen = open === r.id
              return (
                <div key={r.id}>
                  <div style={s.row} onClick={() => setOpen(isOpen ? null : r.id)}>
                    <span style={{ ...s.pill, color: o.color, background: o.bg }}>{o.label}</span>
                    <span style={s.id}>{r.id}</span>
                    <span style={s.area}>{r.area}</span>
                    <span style={s.title}>{r.title}</span>
                    <span style={s.caret}>{isOpen ? '▾' : '▸'}</span>
                  </div>
                  {isOpen && (
                    <div style={s.checks}>
                      {r.checks.map((c, i) => (
                        <div key={i} style={s.check}>
                          <span style={{ color: c.ok ? '#22c55e' : '#ef4444' }}>{c.ok ? '✓' : '✗'}</span>
                          &nbsp;{c.desc}
                          {c.evidence && <span style={s.evidence}> — {c.evidence}</span>}
                        </div>
                      ))}
                      {r.known_bug && <div style={{ ...s.check, color: '#fbbf24' }}>↳ {r.known_bug}</div>}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )
      })}
    </div>
  )
}

const s = {
  empty: { color: '#94a3b8', fontSize: 14, lineHeight: 1.6, padding: 24, background: '#1a1d27',
           border: '1px solid #2d3148', borderRadius: 10, maxWidth: 720 },
  header: { marginBottom: 16 },
  h2: { margin: '0 0 6px', fontSize: 18, color: '#c7d2fe' },
  sub: { fontSize: 13, color: '#94a3b8', marginBottom: 10 },
  counts: { display: 'flex', gap: 8, flexWrap: 'wrap' },
  count: { borderRadius: 12, padding: '3px 12px', fontSize: 12, fontWeight: 700 },
  mission: { background: '#1a1d27', border: '1px solid #2d3148', borderRadius: 10, marginBottom: 12,
             overflow: 'hidden' },
  missionTitle: { padding: '10px 14px', fontWeight: 700, fontSize: 13, color: '#a5b4fc',
                  borderBottom: '1px solid #2d3148' },
  row: { display: 'flex', alignItems: 'center', gap: 10, padding: '7px 14px', fontSize: 13,
         cursor: 'pointer', borderBottom: '1px solid #20243a' },
  pill: { borderRadius: 10, padding: '1px 8px', fontSize: 10, fontWeight: 800, minWidth: 64, textAlign: 'center' },
  id: { fontFamily: 'monospace', color: '#64748b', width: 34 },
  area: { color: '#818cf8', fontSize: 11, width: 78 },
  title: { flex: 1, color: '#e2e8f0' },
  caret: { color: '#64748b' },
  checks: { padding: '6px 14px 10px 130px', background: '#141722' },
  check: { fontSize: 12, color: '#cbd5e1', padding: '2px 0', lineHeight: 1.5 },
  evidence: { color: '#64748b', fontFamily: 'monospace', fontSize: 11 },
}
