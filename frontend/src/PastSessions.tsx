import { useEffect, useState } from 'react'
import type { SessionsApi } from './api'
import type { PastSessionSummary } from './contract'
import { formatStart } from './pastSession'
import { formatDuration } from './timeline/model'

/** The list of past Sessions: open one, or delete it (with its audio) after a confirmation. */
export function PastSessions({
  sessions,
  openId,
  refresh,
  onOpen,
  onDeleted,
  onError,
}: {
  sessions: SessionsApi
  /** The past Session that is open now, if any. */
  openId: string | null
  /** Change it to load the list again. */
  refresh: number
  onOpen: (id: string) => void
  onDeleted: (id: string) => void
  onError: (e: unknown) => void
}) {
  const [list, setList] = useState<PastSessionSummary[] | null>(null)
  const [confirm, setConfirm] = useState<string | null>(null)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let live = true
    sessions
      .list()
      .then((l) => live && setList(l))
      .catch((e) => live && onError(e))
    return () => {
      live = false
    }
  }, [sessions, refresh, reload, onError])

  const remove = (id: string) => {
    setConfirm(null)
    sessions
      .remove(id)
      .then(() => {
        onDeleted(id)
        setReload((n) => n + 1)
      })
      .catch(onError)
  }

  return (
    <section aria-label="Past sessions" className="past-sessions">
      {list === null && <p>Loading…</p>}
      {list?.length === 0 && <p>No past sessions.</p>}
      {list && list.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Length</th>
              <th>Speakers</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {list.map((s) => (
              <tr key={s.id} data-testid="past-session" className={s.id === openId ? 'open' : undefined}>
                <td>
                  {formatStart(s.started_at)}
                  {s.interrupted && (
                    <span className="chip chip-error" title="The app ended without a stop. The session is kept as it was.">
                      interrupted
                    </span>
                  )}
                </td>
                <td>{formatDuration(s.length)}</td>
                <td className="past-speakers">{s.speakers.map((sp) => sp.display_name || sp.label).join(', ') || '—'}</td>
                <td className="past-actions">
                  {confirm === s.id ? (
                    <>
                      Delete this session and its audio?{' '}
                      <button className="danger" onClick={() => remove(s.id)}>
                        Delete
                      </button>
                      <button onClick={() => setConfirm(null)}>Cancel</button>
                    </>
                  ) : (
                    <>
                      <button onClick={() => onOpen(s.id)} disabled={s.id === openId}>
                        Open
                      </button>
                      <button onClick={() => setConfirm(s.id)}>Delete…</button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
