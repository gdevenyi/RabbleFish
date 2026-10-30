// Language switch: a change in the detected language between Segments of the same
// Speaker. Segments with no language (`lang: null`) do not start or end a switch.
// The input uses the Speaker after Merges, so a Merge computes the switches again.
import type { Segment } from './state'

/**
 * Returns the ids of the Segments that start a Language switch.
 * @param segments Segments sorted by start time.
 * @param speakerOf The Speaker of a Segment after Merges.
 */
export function languageSwitches(segments: Segment[], speakerOf: (s: Segment) => string): Set<string> {
  const last = new Map<string, string>()
  const out = new Set<string>()
  for (const s of segments) {
    if (!s.lang) continue
    const sp = speakerOf(s)
    const prev = last.get(sp)
    if (prev && prev !== s.lang) out.add(s.id)
    last.set(sp, s.lang)
  }
  return out
}
