// Commands from the UI to the backend (REST). The UI changes its state only from the
// /ws events that the backend broadcasts after a command, never from the HTTP response.
import type { SourceMode } from './contract'

export interface Api {
  /** `targetLanguage` is the Target language of the Session, for example "en". */
  startSession(targetLanguage: string): Promise<void>
  stopSession(): Promise<void>
  /** `null` removes the Display name. */
  renameSpeaker(id: string, displayName: string | null): Promise<void>
  mergeSpeakers(fromId: string, intoId: string): Promise<void>
  updateSource(key: string, change: { selected?: boolean; mode?: SourceMode }): Promise<void>
}

async function send(method: string, url: string, body?: unknown) {
  const r = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!r.ok) {
    let detail = ''
    try {
      detail = (await r.json()).detail ?? ''
    } catch {
      // The body is not JSON.
    }
    throw new Error(`${method} ${url}: HTTP ${r.status}${detail ? ` (${detail})` : ''}`)
  }
}

export const httpApi: Api = {
  startSession: (targetLanguage) => send('POST', '/api/session/start', { target_language: targetLanguage }),
  stopSession: () => send('POST', '/api/session/stop'),
  renameSpeaker: (id, displayName) => send('PATCH', `/api/speakers/${encodeURIComponent(id)}`, { display_name: displayName }),
  mergeSpeakers: (fromId, intoId) => send('POST', '/api/speakers/merge', { from_speaker_id: fromId, into_speaker_id: intoId }),
  updateSource: (key, change) => send('PATCH', `/api/sources/${encodeURIComponent(key)}`, change),
}
