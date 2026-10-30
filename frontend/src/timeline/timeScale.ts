// The vertical axis of the Timeline: linear time (seconds × zoom) inside speech, and a
// Silence fold of fixed height in place of each silence of all Speakers that is longer
// than `foldAfter` seconds. A few seconds stay linear on each side of a fold.

export interface Span {
  start: number
  end: number
}

export interface Fold {
  /** Session time where the fold starts and ends. */
  start: number
  end: number
  /** The full silence (the fold plus the linear margins). */
  silence: number
  /** Top of the fold in px. */
  y: number
}

export interface TimeScaleOptions {
  /** Pixels per second of linear time. */
  pxPerSec: number
  /** A silence longer than this (seconds) folds. */
  foldAfter?: number
  /** Seconds that stay linear before and after a fold. */
  margin?: number
  /** Height of a fold in px. */
  foldPx?: number
}

export interface TimeScale {
  folds: Fold[]
  pxPerSec: number
  /** Session time of the Live edge. */
  end: number
  /** y (px) of the Live edge. */
  height: number
  y(t: number): number
  time(y: number): number
}

export const FOLD_AFTER_S = 20

/**
 * @param spans Time ranges with speech (Segments and Partial text), in any order.
 * @param end The Live edge (session time). Trailing silence before it also folds.
 */
export function buildTimeScale(spans: Span[], end: number, opts: TimeScaleOptions): TimeScale {
  const { pxPerSec, foldAfter = FOLD_AFTER_S, margin = 3, foldPx = 26 } = opts
  // Join the speech into sorted, separate ranges.
  const sorted = spans.filter((s) => s.end >= s.start).sort((a, b) => a.start - b.start)
  const joined: Span[] = []
  for (const s of sorted) {
    const last = joined[joined.length - 1]
    if (last && s.start <= last.end) last.end = Math.max(last.end, s.end)
    else joined.push({ start: s.start, end: s.end })
  }
  // Silences: before the first speech, between speech ranges, and up to the Live edge.
  const silences: Span[] = []
  let cursor = 0
  for (const s of joined) {
    if (s.start > cursor) silences.push({ start: cursor, end: s.start })
    cursor = Math.max(cursor, s.end)
  }
  if (end > cursor) silences.push({ start: cursor, end })

  const folds: Fold[] = []
  let removed = 0 // px removed by the folds so far
  for (const g of silences) {
    const len = g.end - g.start
    if (len <= foldAfter) continue
    const start = g.start + margin
    const stop = g.end - margin
    folds.push({ start, end: stop, silence: len, y: start * pxPerSec - removed })
    removed += (stop - start) * pxPerSec - foldPx
  }

  const y = (t: number): number => {
    let shift = 0
    for (const f of folds) {
      if (t <= f.start) break
      if (t < f.end) return f.y + ((t - f.start) / (f.end - f.start)) * foldPx
      shift += (f.end - f.start) * pxPerSec - foldPx
    }
    return t * pxPerSec - shift
  }
  const time = (py: number): number => {
    let shift = 0
    for (const f of folds) {
      if (py <= f.y) break
      if (py < f.y + foldPx) return f.start + ((py - f.y) / foldPx) * (f.end - f.start)
      shift += (f.end - f.start) * pxPerSec - foldPx
    }
    return (py + shift) / pxPerSec
  }
  return { folds, pxPerSec, end, height: y(end), y, time }
}
