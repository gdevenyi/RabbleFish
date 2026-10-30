import { useBackendSocket } from './useBackendSocket'

export function App() {
  const { status, version, lastHeartbeat } = useBackendSocket()
  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: 24 }}>
      <h1>Live Transcribe Translate</h1>
      <p>
        Backend: <strong data-testid="status">{status}</strong>
        {version && ` (version ${version})`}
      </p>
      <p>
        Last heartbeat: <span data-testid="heartbeat">{lastHeartbeat ? `#${lastHeartbeat.seq}` : '—'}</span>
      </p>
    </main>
  )
}
