// Overlap: times where Segments of different Speakers (after Merges) overlap.
import type { Segment } from './state'

export interface Band {
  start: number
  end: number
}

export interface Overlaps {
  /** Joined time ranges with overlapping speech, sorted. */
  bands: Band[]
  /** Ids of the Segments that overlap a Segment of another Speaker. */
  ids: Set<string>
}

/**
 * @param segments Segments sorted by start time.
 * @param speakerOf The Speaker of a Segment after Merges.
 */
export function findOverlaps(segments: Segment[], speakerOf: (s: Segment) => string): Overlaps {
  const raw: Band[] = []
  const ids = new Set<string>()
  let active: Segment[] = []
  for (const s of segments) {
    active = active.filter((a) => a.end > s.start)
    const sp = speakerOf(s)
    for (const a of active) {
      if (speakerOf(a) === sp) continue
      raw.push({ start: s.start, end: Math.min(a.end, s.end) })
      ids.add(a.id)
      ids.add(s.id)
    }
    if (s.end > s.start) active.push(s)
  }
  raw.sort((a, b) => a.start - b.start)
  const bands: Band[] = []
  for (const b of raw) {
    const last = bands[bands.length - 1]
    if (last && b.start <= last.end) last.end = Math.max(last.end, b.end)
    else bands.push({ ...b })
  }
  return { bands, ids }
}
