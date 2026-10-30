import { useCallback, useEffect, useReducer, useState } from 'react'
import './app.css'
import { DEFAULT_TARGET_LANGUAGE, TARGET_LANGUAGES } from './languages'
import { SourcesPanel } from './SourcesPanel'
import { formatTime, liveEdge, sourceDescription } from './timeline/model'
import { initialState, type ReceivedEvent, reduceAll } from './timeline/state'
import { Timeline } from './timeline/Timeline'
import { useBackendSocket } from './useBackendSocket'

const CLOCK_TICK_MS = 250

export function App() {
  const [state, dispatch] = useReducer(reduceAll, undefined, initialState)
  const onEvents = useCallback((batch: ReceivedEvent[]) => dispatch(batch), [])
  const { status, api } = useBackendSocket(onEvents)
  const [clientNow, setClientNow] = useState(() => Date.now() / 1000)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [sourcesOpen, setSourcesOpen] = useState(true)
  const [targetLang, setTargetLang] = useState(DEFAULT_TARGET_LANGUAGE)

  const running = state.session.state === 'started'
  useEffect(() => {
    const id = setInterval(() => setClientNow(Date.now() / 1000), CLOCK_TICK_MS)
    return () => clearInterval(id)
  }, [])
  // Close the Sources panel when a Session starts, to give the Timeline the room.
  useEffect(() => setSourcesOpen(!running), [running])

  const onError = useCallback((e: unknown) => setError(e instanceof Error ? e.message : String(e)), [])
  const command = (fn: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    fn()
      .catch(onError)
      .finally(() => setBusy(false))
  }
  const online = status === 'connected' || status === 'demo'
  const anySelected = state.sources.some((s) => s.selected)

  return (
    <div className="app">
      <header className="app-bar">
        <h1>Live Transcribe Translate</h1>
        <span className={`conn conn-${status}`} title={state.version ? `Backend version ${state.version}` : undefined}>
          Backend: <strong data-testid="status">{status}</strong>
        </span>
        <span className="session" data-testid="session-state">
          Session: <strong>{state.session.state}</strong>
          {running && ` · ${formatTime(liveEdge(state, clientNow))}`}
        </span>
        <label className="target-lang" title="The Target language of the translation. You cannot change it while a Session runs.">
          Translate to{' '}
          <select
            aria-label="Target language"
            data-testid="target-language"
            value={running && state.session.targetLang ? state.session.targetLang : targetLang}
            onChange={(e) => setTargetLang(e.target.value)}
            disabled={running}
          >
            {TARGET_LANGUAGES.map((l) => (
              <option key={l.code} value={l.code}>
                {l.name} ({l.code})
              </option>
            ))}
          </select>
        </label>
        <button
          className="start"
          onClick={() => command(() => api.startSession(targetLang))}
          disabled={!online || running || busy || !anySelected}
          title={anySelected ? 'Start a Session with the selected Sources' : 'Select at least one Source first'}
        >
          Start
        </button>
        <button className="stop" onClick={() => command(api.stopSession)} disabled={!online || !running || busy}>
          Stop
        </button>
        <span className="source-status">
          {Object.entries(state.sourceStatus).map(([key, st]) => (
            <span key={key} className={`chip chip-${st.state}`} title={st.message ?? key} data-testid="source-status">
              {sourceDescription(state, key)}: {st.state}
              {st.message && st.state !== 'live' ? ` (${st.message})` : ''}
            </span>
          ))}
          {state.translationStatus && (
            <span
              className={`chip chip-${state.translationStatus.state === 'ready' ? 'live' : 'error'}`}
              title={state.translationStatus.message ?? `Translation to ${state.translationStatus.targetLang}`}
              data-testid="translation-status"
            >
              Translation: {state.translationStatus.state}
              {state.translationStatus.message ? ` (${state.translationStatus.message})` : ''}
            </span>
          )}
        </span>
        <button className="sources-toggle" onClick={() => setSourcesOpen((o) => !o)} aria-expanded={sourcesOpen}>
          Sources {sourcesOpen ? '▴' : '▾'}
        </button>
      </header>
      {error && (
        <div className="error" role="alert">
          {error} <button onClick={() => setError(null)}>Dismiss</button>
        </div>
      )}
      {sourcesOpen && <SourcesPanel sources={state.sources} api={api} disabled={running} onError={onError} />}
      <Timeline state={state} clientNow={clientNow} api={api} onError={onError} />
    </div>
  )
}
