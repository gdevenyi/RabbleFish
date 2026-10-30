// Derived data for the Timeline: Columns after Merges, Segments per Speaker, Language
// switches, overlaps and the Live edge. Pure functions of the app state.
import { findOverlaps, type Overlaps } from './overlap'
import { languageSwitches } from './language'
import { type AppState, mergeTargets, resolveSpeaker, type Segment, sortedSegments, type Speaker } from './state'

export interface SourceGroup {
  key: string
  description: string
  speakers: Speaker[]
}

export interface TimelineModel {
  segments: Segment[]
  /** Merged Speaker id to the Speaker that holds its Segments now. */
  targets: Map<string, string>
  speakerOf: (s: Segment) => string
  /** Speakers that have a Column (not merged away), grouped by Source. */
  groups: SourceGroup[]
  bySpeaker: Map<string, Segment[]>
  lastSpokeAt: Map<string, number>
  switches: Set<string>
  overlaps: Overlaps
}

export function sourceDescription(state: AppState, key: string): string {
  return state.sources.find((s) => s.key === key)?.description ?? key
}

export function buildModel(state: AppState): TimelineModel {
  const segments = sortedSegments(state)
  const targets = mergeTargets(state.merges)
  const speakerOf = (s: Segment) => resolveSpeaker(targets, s.speakerId)

  const bySpeaker = new Map<string, Segment[]>()
  const lastSpokeAt = new Map<string, number>()
  for (const s of segments) {
    const sp = speakerOf(s)
    let list = bySpeaker.get(sp)
    if (!list) bySpeaker.set(sp, (list = []))
    list.push(s)
    lastSpokeAt.set(sp, Math.max(lastSpokeAt.get(sp) ?? 0, s.end))
  }

  // Source order: the order of the Sources list, then any other Source in the data.
  const keys: string[] = []
  const add = (k: string) => keys.includes(k) || keys.push(k)
  for (const s of state.sources) if (s.selected) add(s.key)
  for (const k of Object.keys(state.sourceStatus)) add(k)
  for (const sp of Object.values(state.speakers)) add(sp.sourceKey)
  for (const k of Object.keys(state.partials)) add(k)

  const live = Object.values(state.speakers)
    .filter((sp) => !targets.has(sp.id))
    .sort((a, b) => a.order - b.order)
  const groups = keys
    .map((key) => ({ key, description: sourceDescription(state, key), speakers: live.filter((sp) => sp.sourceKey === key) }))
    // A selected Source with no Speaker yet shows only when the Session has data for it.
    .filter((g) => g.speakers.length > 0 || state.partials[g.key] || state.sourceStatus[g.key])

  return {
    segments,
    targets,
    speakerOf,
    groups,
    bySpeaker,
    lastSpokeAt,
    switches: languageSwitches(segments, speakerOf),
    overlaps: findOverlaps(segments, speakerOf),
  }
}

/** The name to show for a Speaker: the Display name, else the generated label. */
export function nameOf(sp: Speaker | undefined): string {
  if (!sp) return '?'
  return sp.displayName || sp.label
}

/**
 * Session time of the Live edge.
 * @param clientNow Client clock, unix seconds.
 */
export function liveEdge(state: AppState, clientNow: number): number {
  let dataEnd = 0
  const last = state.segmentOrder.length
  // Segments are sorted by start; look at the last ones for the maximum end.
  for (let i = Math.max(0, last - 50); i < last; i++) dataEnd = Math.max(dataEnd, state.segments[state.segmentOrder[i]].end)
  for (const p of Object.values(state.partials)) dataEnd = Math.max(dataEnd, p.audioTime)
  if (state.session.state === 'started' && state.session.startedAt !== null) {
    return Math.max(dataEnd, clientNow + state.clockOffset - state.session.startedAt)
  }
  return dataEnd
}

/** "mm:ss", or "h:mm:ss" after one hour. */
export function formatTime(t: number): string {
  const s = Math.max(0, Math.floor(t))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = String(s % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${String(m).padStart(2, '0')}:${ss}`
}

/** "45 s", "2 min 05 s". */
export function formatDuration(sec: number): string {
  const s = Math.round(sec)
  const m = Math.floor(s / 60)
  return m ? `${m} min ${String(s % 60).padStart(2, '0')} s` : `${s} s`
}
