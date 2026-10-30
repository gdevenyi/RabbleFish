// A past Session in the Timeline: its state comes from the replayed snapshot that
// `GET /api/sessions/{id}` returns, through the same reducer as the live /ws events.
import type { Api, SessionsApi } from './api'
import type { PastSession, ServerEvent, SourceInfo } from './contract'
import type { ReceivedEvent } from './timeline/state'

/**
 * The events that build the state of a past Session from an empty state. `hello` clears
 * the transcript, and the current Sources (not selected) give the Source descriptions.
 */
export function pastSessionEvents(past: PastSession, sources: SourceInfo[], at: number): ReceivedEvent[] {
  const events: ServerEvent[] = [
    { type: 'hello', version: 'past' },
    { type: 'sources', sources: sources.map((s) => ({ ...s, selected: false })) },
    ...past.events,
  ]
  return events.map((event) => ({ event, at }))
}

/**
 * The Api for the Timeline of a past Session: rename and merge go to the past Session's
 * log, and `apply` adds the event that the backend appended. The other commands fail.
 */
export function pastSessionApi(sessions: SessionsApi, id: string, apply: (e: ServerEvent) => void): Api {
  const readOnly = async () => {
    throw new Error('A past Session is read-only. Go back to the live view first.')
  }
  return {
    startSession: readOnly,
    stopSession: readOnly,
    updateSource: readOnly,
    async renameSpeaker(speakerId, displayName) {
      apply(await sessions.renameSpeaker(id, speakerId, displayName))
    },
    async mergeSpeakers(fromId, intoId) {
      apply(await sessions.mergeSpeakers(id, fromId, intoId))
    },
  }
}

/** The local date and time of a Session start, for example "2026-10-30 14:05". */
export function formatStart(startedAt: number | null): string {
  if (startedAt === null) return '?'
  const d = new Date(startedAt * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
