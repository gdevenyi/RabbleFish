// The height of a Segment box in its Column. The box starts at the time of its Segment,
// and it must stop before the next Segment. Thus the room always wins over the minimum height.

const MIN_SEG_PX = 22
const THIN_SEG_PX = 14 // a box below this height has no space for text: it shows as a bar

export interface SegmentBoxHeight {
  min: number
  /** Undefined when nothing is below the box. */
  max: number | undefined
  thin: boolean
}

/**
 * @param height Height of the speech in px (linear time).
 * @param room Space down to the next Segment of the Column, in px. It is Infinity if there is no limit.
 */
export function segmentBoxHeight(height: number, room: number): SegmentBoxHeight {
  const cap = Math.max(0, room)
  const min = Math.min(Math.max(MIN_SEG_PX, height), cap)
  return { min, max: Number.isFinite(cap) ? cap : undefined, thin: cap < THIN_SEG_PX }
}
