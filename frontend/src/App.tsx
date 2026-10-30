import { useCallback, useEffect, useMemo, useReducer, useState } from 'react'
import './app.css'
import { httpSessionsApi } from './api'
import type { ServerEvent } from './contract'
import { DEFAULT_TARGET_LANGUAGE, TARGET_LANGUAGES } from './languages'
import { PastSessions } from './PastSessions'
import { formatStart, pastSessionApi, pastSessionEvents } from './pastSession'
import { SourcesPanel } from './SourcesPanel'
import { formatTime, liveEdge, sourceDescription } from './timeline/model'
import { initialState, type ReceivedEvent, reduceAll, warningHint, warningLabel } from './timeline/state'
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
  const [saveAudio, setSaveAudio] = useState(true)
  // Past Sessions: the list panel, and the past Session open in the Timeline (if any).
  const [pastOpen, setPastOpen] = useState(false)
  const [pastRefresh, setPastRefresh] = useState(0)
  const [pastId, setPastId] = useState<string | null>(null)
  const [pastState, pastDispatch] = useReducer(reduceAll, undefined, initialState)

  const running = state.session.state === 'started'
  useEffect(() => {
    const id = setInterval(() => setClientNow(Date.now() / 1000), CLOCK_TICK_MS)
    return () => clearInterval(id)
  }, [])
  // Close the Sources panel when a Session starts, to give the Timeline the room.
  useEffect(() => setSourcesOpen(!running), [running])
  // A stopped Session is a new past Session.
  useEffect(() => setPastRefresh((n) => n + 1), [state.session.state])

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

  const openPast = (id: string) => {
    setError(null)
    httpSessionsApi
      .open(id)
      .then((past) => {
        // Time 0: the saved Merges are old, so the Timeline shows no "recent Merge" notice.
        pastDispatch(pastSessionEvents(past, state.sources, 0))
        setPastId(id)
        setPastOpen(false)
      })
      .catch(onError)
  }
  const backToLive = () => {
    setPastId(null)
    setPastRefresh((n) => n + 1) // the list shows the renames and merges
  }
  const pastApi = useMemo(
    () =>
      pastId === null
        ? null
        : pastSessionApi(httpSessionsApi, pastId, (event: ServerEvent) => pastDispatch([{ event, at: Date.now() / 1000 }])),
    [pastId],
  )

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
        <label className="save-audio" title="Save the captured audio of each Source as raw PCM16, 16 kHz mono (about 115 MB per hour per Source).">
          <input type="checkbox" data-testid="save-audio" checked={saveAudio} onChange={(e) => setSaveAudio(e.target.checked)} disabled={running} /> Save
          audio
        </label>
        <button
          className="start"
          onClick={() => command(() => api.startSession(targetLang, saveAudio))}
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
            <span
              key={key}
              className={`chip chip-${st.state}${st.warning ? ' chip-warn' : ''}`}
              title={st.warning ? warningHint(st.warning) : (st.message ?? key)}
              data-testid="source-status"
            >
              {sourceDescription(state, key)}: {st.state}
              {st.message && st.state !== 'live' ? ` (${st.message})` : ''}
              {st.warning && (
                <b className="warn-badge" data-testid="source-warning">
                  {warningLabel(st.warning)}
                </b>
              )}
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
        <button className="past-toggle" onClick={() => setPastOpen((o) => !o)} aria-expanded={pastOpen} disabled={status === 'demo'}>
          Past sessions {pastOpen ? '▴' : '▾'}
        </button>
        <button className="sources-toggle" onClick={() => setSourcesOpen((o) => !o)} aria-expanded={sourcesOpen}>
          Sources {sourcesOpen ? '▴' : '▾'}
        </button>
      </header>
      {error && (
        <div className="error" role="alert">
          {error} <button onClick={() => setError(null)}>Dismiss</button>
        </div>
      )}
      {pastOpen && (
        <PastSessions
          sessions={httpSessionsApi}
          openId={pastId}
          refresh={pastRefresh}
          onOpen={openPast}
          onDeleted={(id) => id === pastId && setPastId(null)}
          onError={onError}
        />
      )}
      {sourcesOpen && pastId === null && <SourcesPanel sources={state.sources} api={api} disabled={running} onError={onError} />}
      {pastId !== null && pastApi !== null ? (
        <>
          <div className="past-banner" data-testid="past-banner">
            <span>
              Past session <strong>{formatStart(pastState.session.startedAt)}</strong>
              {pastState.session.state === 'interrupted' && <span className="chip chip-error">interrupted</span>} · read-only (you can still rename and merge
              Speakers)
              {running && ' · a live Session runs'}
            </span>
            <button className="back-live" onClick={backToLive}>
              ← Back to live
            </button>
          </div>
          <Timeline key={pastId} state={pastState} clientNow={clientNow} api={pastApi} onError={onError} />
        </>
      ) : (
        <Timeline state={state} clientNow={clientNow} api={api} onError={onError} />
      )}
    </div>
  )
}
