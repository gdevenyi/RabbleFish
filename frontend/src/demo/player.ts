// DEV ONLY. Plays the scripted Session as if it came from the backend on /ws:
// hello, sources, then a snapshot of the first `history` seconds in one burst, then the
// rest in real time (times `speed`). The demo Api answers the REST commands with the
// events that the backend would broadcast.
import type { Api } from '../api'
import type { ServerEvent, SourceInfo } from '../contract'
import { buildScenario, DEMO_SOURCES, type TimedEvent } from './scenario'

export interface DemoOptions {
  /** Session time already passed when the demo starts (sent as the snapshot). */
  history: number
  /** Speed of the Session clock. */
  speed: number
}

const TICK_MS = 100

export function startDemo(emit: (e: ServerEvent) => void, opts: DemoOptions): { api: Api; stop: () => void } {
  let sources: SourceInfo[] = DEMO_SOURCES.map((s) => ({ ...s }))
  let timer: ReturnType<typeof setInterval> | undefined
  let events: TimedEvent[] = []
  let next = 0
  let startedAt = 0 // unix seconds on the "server" clock
  let wallStart = 0
  let sessionStart = 0 // session time at wallStart
  let seq = 0
  const sessionTime = () => sessionStart + ((Date.now() / 1000 - wallStart) * opts.speed)

  const tick = () => {
    const now = sessionTime()
    while (next < events.length && events[next].t <= now) emit(events[next++].event)
    // Heartbeats carry the server clock. A demo speed above 1 moves that clock faster.
    emit({ type: 'heartbeat', seq: ++seq, server_time: startedAt + now })
  }

  const start = (history: number) => {
    events = buildScenario()
    next = 0
    wallStart = Date.now() / 1000
    sessionStart = history
    startedAt = wallStart - history
    emit({ type: 'session', state: 'started', started_at: startedAt })
    tick() // the snapshot: everything up to `history`
    timer = setInterval(tick, TICK_MS)
  }

  const stopSession = () => {
    clearInterval(timer)
    timer = undefined
    emit({ type: 'session', state: 'stopped', started_at: startedAt })
  }

  emit({ type: 'hello', version: 'demo' })
  emit({ type: 'sources', sources })
  start(opts.history)

  const api: Api = {
    async startSession() {
      if (timer) throw new Error('A Session already runs')
      start(0)
    },
    async stopSession() {
      stopSession()
    },
    async renameSpeaker(id, displayName) {
      const sp = [...events.slice(0, next)].reverse().find((e) => e.event.type === 'speaker' && e.event.id === id)
      if (!sp || sp.event.type !== 'speaker') throw new Error(`unknown speaker: ${id}`)
      sp.event = { ...sp.event, display_name: displayName }
      emit(sp.event)
    },
    async mergeSpeakers(fromId, intoId) {
      emit({ type: 'merge', from_speaker_id: fromId, into_speaker_id: intoId })
    },
    async updateSource(key, change) {
      if (timer) throw new Error('The Sources cannot change while a Session runs')
      sources = sources.map((s) => (s.key === key ? { ...s, ...change } : s))
      emit({ type: 'sources', sources })
    },
  }
  return { api, stop: () => clearInterval(timer) }
}
