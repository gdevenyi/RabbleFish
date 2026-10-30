// The app state that the /ws events build, and the pure reducer for it.
// The reducer is idempotent: the snapshot on connect can repeat events that the UI
// already has, and the result is the same.
import type { ServerEvent, SourceInfo, Word } from '../contract'

export interface Speaker {
  id: string
  sourceKey: string
  /** Generated label, for example "Speaker 2". */
  label: string
  displayName: string | null
  /** Order of first appearance, for a stable Column order. */
  order: number
}

export interface Segment {
  id: string
  sourceKey: string
  /** The Speaker in the event. Use `resolveSpeaker` to apply Merges. */
  speakerId: string
  start: number
  end: number
  text: string
  words: Word[]
  lang: string | null
}

export interface Translation {
  text: string
  targetLang: string
}

export interface Merge {
  from: string
  into: string
  /** Client time (unix seconds) when the UI received the Merge. */
  receivedAt: number
}

export interface PartialText {
  sourceKey: string
  text: string
  /** Session time of the newest audio in the Partial text. */
  audioTime: number
  /** Estimate of the Session time where the Partial text starts. */
  since: number
}

export interface SourceStatus {
  state: 'connecting' | 'live' | 'error'
  message: string | null
}

export interface SessionInfo {
  state: 'idle' | 'started' | 'stopped'
  /** Unix seconds, on the server clock. */
  startedAt: number | null
}

export interface AppState {
  version: string | null
  /** Server clock minus client clock, in seconds, from the last heartbeat. */
  clockOffset: number
  sources: SourceInfo[]
  session: SessionInfo
  sourceStatus: Record<string, SourceStatus>
  speakers: Record<string, Speaker>
  segments: Record<string, Segment>
  /** Segment ids, sorted by start time (then id). */
  segmentOrder: string[]
  translations: Record<string, Translation>
  merges: Merge[]
  partials: Record<string, PartialText>
}

/** One event with the client time (unix seconds) when it arrived. */
export interface ReceivedEvent {
  event: ServerEvent
  at: number
}

/** How far before the first audio of a Partial text its speech probably starts. */
const PARTIAL_LEAD_S = 1.5

const emptyTranscript = {
  session: { state: 'idle', startedAt: null } as SessionInfo,
  sourceStatus: {},
  speakers: {},
  segments: {},
  segmentOrder: [],
  translations: {},
  merges: [],
  partials: {},
} satisfies Partial<AppState>

export function initialState(): AppState {
  return { version: null, clockOffset: 0, sources: [], ...emptyTranscript }
}

/** Applies events in order. The state is copied once for the whole batch. */
export function reduceAll(state: AppState, batch: ReceivedEvent[]): AppState {
  if (batch.length === 0) return state
  const s: AppState = {
    ...state,
    sourceStatus: { ...state.sourceStatus },
    speakers: { ...state.speakers },
    segments: { ...state.segments },
    segmentOrder: [...state.segmentOrder],
    translations: { ...state.translations },
    merges: [...state.merges],
    partials: { ...state.partials },
  }
  for (const r of batch) apply(s, r)
  return s
}

export function reduce(state: AppState, r: ReceivedEvent): AppState {
  return reduceAll(state, [r])
}

function resetTranscript(s: AppState) {
  Object.assign(s, structuredClone(emptyTranscript))
}

function nextOrder(s: AppState) {
  let n = 0
  for (const sp of Object.values(s.speakers)) n = Math.max(n, sp.order + 1)
  return n
}

function compareSegments(a: Segment, b: Segment) {
  return a.start - b.start || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)
}

function insertSorted(s: AppState, seg: Segment) {
  const order = s.segmentOrder
  let lo = 0
  let hi = order.length
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (compareSegments(s.segments[order[mid]], seg) < 0) lo = mid + 1
    else hi = mid
  }
  order.splice(lo, 0, seg.id)
}

function lastEndOfSource(s: AppState, sourceKey: string): number {
  let end = 0
  // The newest Segments are at the end of the order, so stop early.
  for (let i = s.segmentOrder.length - 1, seen = 0; i >= 0 && seen < 50; i--) {
    const seg = s.segments[s.segmentOrder[i]]
    if (seg.sourceKey !== sourceKey) continue
    seen++
    end = Math.max(end, seg.end)
  }
  return end
}

function apply(s: AppState, { event: e, at }: ReceivedEvent) {
  switch (e.type) {
    case 'hello':
      // A new connection: the snapshot that follows sends the whole Session again.
      s.version = e.version
      resetTranscript(s)
      return
    case 'heartbeat':
      s.clockOffset = e.server_time - at
      return
    case 'sources':
      s.sources = e.sources
      return
    case 'session':
      if (e.state === 'started' && e.started_at !== s.session.startedAt && s.session.startedAt !== null) resetTranscript(s)
      s.session = { state: e.state, startedAt: e.started_at ?? s.session.startedAt }
      if (e.state === 'stopped') s.partials = {}
      return
    case 'source_status':
      s.sourceStatus[e.source_key] = { state: e.state, message: e.message ?? null }
      return
    case 'speaker': {
      const old = s.speakers[e.id]
      s.speakers[e.id] = {
        id: e.id,
        sourceKey: e.source_key,
        label: e.label,
        displayName: e.display_name || null,
        order: old?.order ?? nextOrder(s),
      }
      return
    }
    case 'partial': {
      if (!e.text.trim()) {
        delete s.partials[e.source_key]
        return
      }
      const old = s.partials[e.source_key]
      const since = old ? old.since : Math.max(lastEndOfSource(s, e.source_key), e.audio_time - PARTIAL_LEAD_S)
      s.partials[e.source_key] = { sourceKey: e.source_key, text: e.text, audioTime: e.audio_time, since }
      return
    }
    case 'segment': {
      const seg: Segment = {
        id: e.id,
        sourceKey: e.source_key,
        speakerId: e.speaker_id,
        start: e.start,
        end: Math.max(e.start, e.end),
        text: e.text,
        words: e.words ?? [],
        lang: e.lang || null,
      }
      if (s.segments[seg.id]) s.segmentOrder = s.segmentOrder.filter((id) => id !== seg.id)
      s.segments[seg.id] = seg
      insertSorted(s, seg)
      delete s.partials[e.source_key]
      // The contract sends `speaker` first, but do not lose a Segment if the order differs.
      if (!s.speakers[e.speaker_id])
        s.speakers[e.speaker_id] = {
          id: e.speaker_id,
          sourceKey: e.source_key,
          label: e.speaker_id,
          displayName: null,
          order: nextOrder(s),
        }
      return
    }
    case 'translation':
      s.translations[e.segment_id] = { text: e.text, targetLang: e.target_lang }
      return
    case 'merge':
      if (e.from_speaker_id === e.into_speaker_id) return
      if (s.merges.some((m) => m.from === e.from_speaker_id && m.into === e.into_speaker_id)) return
      // A Merge that closes a loop would hide both Columns: ignore it.
      if (resolveSpeaker(mergeTargets(s.merges), e.into_speaker_id) === e.from_speaker_id) return
      s.merges.push({ from: e.from_speaker_id, into: e.into_speaker_id, receivedAt: at })
      return
  }
}

/** Map from a merged Speaker to the Speaker that now holds its Segments (chains resolved). */
export function mergeTargets(merges: Merge[]): Map<string, string> {
  const direct = new Map<string, string>()
  for (const m of merges) direct.set(m.from, m.into)
  const out = new Map<string, string>()
  for (const from of direct.keys()) {
    let id = from
    const seen = new Set<string>([id])
    while (direct.has(id)) {
      const next = direct.get(id)!
      if (seen.has(next)) break // a cycle: stop at the last new Speaker
      seen.add(next)
      id = next
    }
    if (id !== from) out.set(from, id)
  }
  return out
}

export function resolveSpeaker(targets: Map<string, string>, id: string): string {
  return targets.get(id) ?? id
}

export function sortedSegments(s: AppState): Segment[] {
  return s.segmentOrder.map((id) => s.segments[id])
}
