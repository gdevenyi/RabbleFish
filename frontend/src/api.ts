// Commands from the UI to the backend (REST). The UI changes its state only from the
// /ws events that the backend broadcasts after a command, never from the HTTP response.
import type { MergeEvent, PastSession, PastSessionSummary, SourceMode, SpeakerEvent } from './contract'

export interface Api {
  /**
   * `targetLanguage` is the Target language of the Session, for example "en".
   * `saveAudio` saves the captured audio of the Session (on by default).
   */
  startSession(targetLanguage: string, saveAudio?: boolean): Promise<void>
  stopSession(): Promise<void>
  /** `null` removes the Display name. */
  renameSpeaker(id: string, displayName: string | null): Promise<void>
  mergeSpeakers(fromId: string, intoId: string): Promise<void>
  updateSource(key: string, change: { selected?: boolean; mode?: SourceMode }): Promise<void>
}

async function send(method: string, url: string, body?: unknown): Promise<Response> {
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
  return r
}

const done = async (r: Promise<Response>) => {
  await r
}
const json = async <T>(r: Promise<Response>) => (await (await r).json()) as T

export const httpApi: Api = {
  startSession: (targetLanguage, saveAudio = true) => done(send('POST', '/api/session/start', { target_language: targetLanguage, save_audio: saveAudio })),
  stopSession: () => done(send('POST', '/api/session/stop')),
  renameSpeaker: (id, displayName) => done(send('PATCH', `/api/speakers/${encodeURIComponent(id)}`, { display_name: displayName })),
  mergeSpeakers: (fromId, intoId) => done(send('POST', '/api/speakers/merge', { from_speaker_id: fromId, into_speaker_id: intoId })),
  updateSource: (key, change) => done(send('PATCH', `/api/sources/${encodeURIComponent(key)}`, change)),
}

/**
 * Past Sessions (the saved event logs). A past Session is read-only, but its Speakers can
 * still be renamed and merged: these return the event that the backend appended to the log.
 */
export interface SessionsApi {
  list(): Promise<PastSessionSummary[]>
  open(id: string): Promise<PastSession>
  renameSpeaker(id: string, speakerId: string, displayName: string | null): Promise<SpeakerEvent>
  mergeSpeakers(id: string, fromId: string, intoId: string): Promise<MergeEvent>
  remove(id: string): Promise<void>
}

const sessionUrl = (id: string) => `/api/sessions/${encodeURIComponent(id)}`

export const httpSessionsApi: SessionsApi = {
  list: () => json(send('GET', '/api/sessions')),
  open: (id) => json(send('GET', sessionUrl(id))),
  renameSpeaker: (id, speakerId, displayName) =>
    json(send('PATCH', `${sessionUrl(id)}/speakers/${encodeURIComponent(speakerId)}`, { display_name: displayName })),
  mergeSpeakers: (id, fromId, intoId) => json(send('POST', `${sessionUrl(id)}/speakers/merge`, { from_speaker_id: fromId, into_speaker_id: intoId })),
  remove: (id) => done(send('DELETE', sessionUrl(id))),
}
