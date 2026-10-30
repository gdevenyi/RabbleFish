import { SourcesPanel } from './SourcesPanel'
import { useBackendSocket } from './useBackendSocket'

export function App() {
  const { status, version, lastHeartbeat, sources } = useBackendSocket()
  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: 24, maxWidth: 900 }}>
      <h1>Live Transcribe Translate</h1>
      <p>
        Backend: <strong data-testid="status">{status}</strong>
        {version && ` (version ${version})`} · last heartbeat:{' '}
        <span data-testid="heartbeat">{lastHeartbeat ? `#${lastHeartbeat.seq}` : '—'}</span>
      </p>
      <SourcesPanel sources={sources} />
    </main>
  )
}
