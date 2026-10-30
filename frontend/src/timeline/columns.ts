// Which Columns are wide and which are Collapsed columns.
// - A Speaker who spoke in the last `activeWindow` seconds, or that the user pinned, is wide.
// - The user can also collapse a Column by hand.
// - All Columns must fit the width (no horizontal scroll): when too many are wide, the
//   Speakers that spoke least recently collapse first, and pinned Columns collapse last.
// - When no Column is wide, the Speaker who spoke last is wide, so there is always text to read.

export type PinState = 'wide' | 'collapsed'

export interface ColumnInput {
  id: string
  /** Session time when the Speaker last spoke, or null if never. */
  lastSpokeAt: number | null
  /** True when the Speaker must be wide, for example to hold Partial text. */
  forceWide?: boolean
}

export interface ColumnLayout {
  id: string
  wide: boolean
  pinned: boolean
  /** True when the Speaker spoke in the active window. */
  active: boolean
}

export interface ColumnOptions {
  now: number
  /** Width available for all Columns, in px. */
  width: number
  pins: Record<string, PinState>
  activeWindow?: number
  wideMin?: number
  collapsedWidth?: number
}

export const ACTIVE_WINDOW_S = 120
export const WIDE_MIN_PX = 200
export const COLLAPSED_PX = 34

export function layoutColumns(cols: ColumnInput[], opts: ColumnOptions): ColumnLayout[] {
  const { now, width, pins, activeWindow = ACTIVE_WINDOW_S, wideMin = WIDE_MIN_PX, collapsedWidth = COLLAPSED_PX } = opts
  const out = cols.map((c) => {
    const active = c.lastSpokeAt !== null && now - c.lastSpokeAt <= activeWindow
    const pin = pins[c.id]
    const wide = pin === 'wide' || !!c.forceWide || (pin !== 'collapsed' && active)
    return { id: c.id, wide, pinned: pin === 'wide', active }
  })
  const last = (i: number) => cols[i].lastSpokeAt ?? -Infinity

  // Width cap: W * wideMin + (n - W) * collapsedWidth <= width.
  const n = cols.length
  const maxWide = Math.max(1, Math.floor((width - n * collapsedWidth) / Math.max(1, wideMin - collapsedWidth)))
  const wideIdx = out.map((c, i) => (c.wide ? i : -1)).filter((i) => i >= 0)
  if (wideIdx.length > maxWide) {
    // Keep first: forced, then pinned, then the most recent.
    const rank = (i: number) => (cols[i].forceWide ? 2 : 0) + (out[i].pinned ? 1 : 0)
    wideIdx.sort((a, b) => rank(b) - rank(a) || last(b) - last(a))
    for (const i of wideIdx.slice(maxWide)) out[i].wide = false
  }
  if (n > 0 && !out.some((c) => c.wide)) {
    let best = -1
    for (let i = 0; i < n; i++) {
      if (pins[cols[i].id] === 'collapsed') continue
      if (best < 0 || last(i) > last(best)) best = i
    }
    if (best >= 0) out[best].wide = true
  }
  return out
}

/** The pin state after the user clicks the pin control of a Column. */
export function togglePin(pins: Record<string, PinState>, col: ColumnLayout): Record<string, PinState> {
  const next = { ...pins }
  if (!col.wide) next[col.id] = 'wide'
  else if (col.pinned) delete next[col.id]
  else next[col.id] = 'collapsed'
  return next
}
