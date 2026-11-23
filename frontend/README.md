# Agent-OS React Dashboard

Real-time visualization of Agent-OS internals.

## Setup (one time)

```bash
cd frontend
npm install
```

## Run

Open **two terminals**:

**Terminal 1 — Backend (Agent-OS API)**
```bash
cd "C:\Users\RUTIKA\Desktop\LY\EDAI\Agent OS\agent-os"
python run.py server
```

**Terminal 2 — Frontend (React)**
```bash
cd "C:\Users\RUTIKA\Desktop\LY\EDAI\Agent OS\agent-os\frontend"
npm run dev
```

Then open **http://localhost:3000** in your browser.

To see data, run the demo in a third terminal:
```bash
cd "C:\Users\RUTIKA\Desktop\LY\EDAI\Agent OS\agent-os"
python examples/generic/demo.py
```

## Panels

| Panel | What it shows |
|-------|--------------|
| ⚙️ Processes | Live process table with state, priority, steps, tokens, actions |
| 📅 Scheduler | Gantt-style timeline of state transitions per tick |
| 📨 IPC | Message flows between agents + send a message manually |
| 📊 Resources | Token/step usage bars + global metrics |
| 🔒 Deadlock | Deadlock alerts, lock ownership, wait-for explanation |
| 📋 Events | Full filterable event log |

## Tech Stack
- React 18 + Vite
- Recharts (bar charts)
- Lucide React (icons)
- Polling every 1.5s via REST API
