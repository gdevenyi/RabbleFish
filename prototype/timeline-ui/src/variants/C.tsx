// PROTOTYPE: throwaway. Variant C: focus columns + overview.
// All columns always fit the width (no horizontal scroll). Speakers that spoke in the
// last 3 min of session time (or that the user pinned) get wide columns; the others
// collapse to a 36 px strip. A minimap of the whole session sits on the right.
import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { Actions, Segment, SessionView, Speaker } from '../types'
import { RenameableName } from '../chrome'
import { fmt, hasCodeSwitch, isLanguageSwitch, moveOf, nameOf, SPEAKERS } from '../session'
import './C.css'

export const name = 'focus columns + overview'

const HEAD = 96 // header height in px (keep in sync with C.css)
const ACTIVE_WINDOW = 180 // seconds of session time
const PENDING = 3 // finalize delay: the zone just before "now" is not filled yet
const SCALES = [6, 10, 16, 24, 34] // px per second

function hue(id: string): number {
  const i = SPEAKERS.findIndex((s) => s.id === id)
  return id === 'mic-0' ? 212 : (i * 47 + 10) % 360
}

interface Col {
  sp: Speaker
  wide: boolean
  ghost: boolean // speaker that just merged away; shown for the 6 s correction window
  pinned: boolean
  active: boolean
}

export function Variant({ view, actions }: { view: SessionView; actions: Actions }) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const expectedTop = useRef<number | null>(null)
  const [scaleIdx, setScaleIdx] = useState(2)
  const scale = SCALES[scaleIdx]
  const [override, setOverride] = useState<Record<string, boolean>>({}) // true = pinned wide, false = forced narrow
  const [port, setPort] = useState({ top: 0, height: 600 })
  const pendingCenter = useRef<number | null>(null)

  const clock = view.clock
  const total = Math.max(clock, 1)
  const bodyH = (clock + 2) * scale

  // --- derived data ------------------------------------------------------------
  const lastEnd = useMemo(() => {
    const m: Record<string, number> = {}
    for (const s of view.segments) m[s.speakerId] = Math.max(m[s.speakerId] ?? 0, s.end)
    return m
  }, [view.segments])

  const bySpeaker = useMemo(() => {
    const m: Record<string, Segment[]> = {}
    for (const s of view.segments) (m[s.speakerId] ??= []).push(s)
    return m
  }, [view.segments])

  const overlaps = useMemo(() => {
    const out: { start: number; end: number; ids: string[] }[] = []
    const segs = view.segments
    for (let i = 0; i < segs.length; i++) {
      for (let j = i + 1; j < segs.length && segs[j].start < segs[i].end; j++) {
        if (segs[j].speakerId === segs[i].speakerId) continue
        out.push({ start: segs[j].start, end: Math.min(segs[i].end, segs[j].end), ids: [segs[i].id, segs[j].id] })
      }
    }
    return out
  }, [view.segments])
  const overlapIds = useMemo(() => new Set(overlaps.flatMap((o) => o.ids)), [overlaps])

  const visibleIds = new Set(view.speakers.map((s) => s.id))
  // Corrections grouped by from -> to. A "merge" is when the old speaker has no column now.
  const corrections = useMemo(() => {
    const m = new Map<string, { from: string; to: string; ids: string[]; at: number }>()
    for (const mv of view.recentMoves) {
      const k = `${mv.fromSpeakerId}>${mv.toSpeakerId}`
      const c = m.get(k) ?? { from: mv.fromSpeakerId, to: mv.toSpeakerId, ids: [], at: mv.at }
      c.ids.push(mv.segmentId)
      m.set(k, c)
    }
    return [...m.values()]
  }, [view.recentMoves])
  const mergedAway = new Set(corrections.filter((c) => !visibleIds.has(c.from)).map((c) => c.from))

  const cols: Col[] = SPEAKERS.filter((s) => visibleIds.has(s.id) || mergedAway.has(s.id)).map((sp) => {
    const ghost = !visibleIds.has(sp.id)
    const active = clock - (lastEnd[sp.id] ?? -1e9) <= ACTIVE_WINDOW
    const ov = override[sp.id]
    return { sp, ghost, active, pinned: ov === true, wide: ghost || (ov ?? active) }
  })
  const groups = view.sources
    .map((src) => ({ src, cols: cols.filter((c) => c.sp.sourceId === src.id) }))
    .filter((g) => g.cols.length > 0)
  const groupStyle = (gc: Col[]) => {
    const wide = gc.filter((c) => c.wide).length
    const narrow = gc.length - wide
    return { flex: `${wide} 0 ${narrow * 36}px` }
  }

  // --- scrolling ---------------------------------------------------------------
  const programmaticScroll = (top: number) => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTop = top
    expectedTop.current = el.scrollTop
    setPort({ top: el.scrollTop, height: el.clientHeight })
  }
  const atLiveEdge = (el: HTMLDivElement) => el.scrollHeight - el.scrollTop - el.clientHeight < 30

  useLayoutEffect(() => {
    const el = scrollRef.current
    if (!el) return
    if (pendingCenter.current != null) {
      const t = pendingCenter.current
      pendingCenter.current = null
      if (!view.follow) programmaticScroll(t * scale - (el.clientHeight - HEAD) / 2)
    }
    if (view.follow) programmaticScroll(el.scrollHeight)
    else setPort({ top: el.scrollTop, height: el.clientHeight })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clock, view.follow, scale])

  const onScroll = () => {
    const el = scrollRef.current!
    setPort({ top: el.scrollTop, height: el.clientHeight })
    if (expectedTop.current != null && Math.abs(el.scrollTop - expectedTop.current) < 2) return
    expectedTop.current = null
    const gap = el.scrollHeight - el.scrollTop - el.clientHeight
    if (gap >= 30 && view.follow) actions.setFollow(false)
    // Re-follow only when the user scrolled all the way down (small trackpad moves must not snap back).
    if (gap < 2 && !view.follow) actions.setFollow(true)
  }
  // Explicit user intent: stop following at once, so the next tick does not fight the user.
  const userIntent = () => {
    expectedTop.current = null
    if (view.follow) actions.setFollow(false)
  }

  const scrollToTime = (t: number) => {
    const el = scrollRef.current
    if (!el) return
    programmaticScroll(t * scale - (el.clientHeight - HEAD) / 2)
    actions.setFollow(atLiveEdge(el))
  }
  const jumpToLive = () => {
    actions.setFollow(true)
    const el = scrollRef.current
    if (el) programmaticScroll(el.scrollHeight)
  }
  const zoom = (d: number) => {
    const el = scrollRef.current
    const next = Math.min(SCALES.length - 1, Math.max(0, scaleIdx + d))
    if (next === scaleIdx) return
    if (el) pendingCenter.current = (el.scrollTop + (el.clientHeight - HEAD) / 2) / scale
    setScaleIdx(next)
  }

  const t0 = port.top / scale
  const t1 = (port.top + port.height - HEAD) / scale

  // --- time gutter ---------------------------------------------------------------
  const step = scale >= 16 ? 10 : scale >= 10 ? 30 : 60
  const labelEvery = scale >= 16 ? 30 : 60
  const ticks: number[] = []
  for (let t = 0; t <= clock; t += step) ticks.push(t)

  // --- overview --------------------------------------------------------------------
  const ovCols = cols.filter((c) => !c.ghost)
  const ovRef = useRef<HTMLDivElement>(null)
  const ovPointer = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.type === 'pointermove' && !(e.buttons & 1)) return
    const box = ovRef.current!.getBoundingClientRect()
    const frac = Math.min(1, Math.max(0, (e.clientY - box.top) / box.height))
    if (e.type === 'pointerdown') e.currentTarget.setPointerCapture(e.pointerId)
    scrollToTime(frac * total)
  }

  const togglePin = (c: Col) =>
    setOverride((o) => {
      const n = { ...o }
      if (c.wide && c.pinned) delete n[c.sp.id]
      else if (c.wide) n[c.sp.id] = false
      else n[c.sp.id] = true
      return n
    })

  return (
    <div className="vC-root">
      <div className="vC-main">
        <div
          className="vC-scroll"
          ref={scrollRef}
          onScroll={onScroll}
          onWheel={(e) => e.deltaY < 0 && userIntent()}
          onKeyDown={(e) => ['ArrowUp', 'PageUp', 'Home'].includes(e.key) && userIntent()}
          onPointerDown={(e) => e.target === e.currentTarget && userIntent()}
          tabIndex={0}
        >
          {/* sticky header: source groups, then one cell per column */}
          <div className="vC-head" style={{ height: HEAD }}>
            <div className="vC-gutter vC-zoom">
              <span>zoom</span>
              <button onClick={() => zoom(1)} title="Zoom in (more px per second)">+</button>
              <button onClick={() => zoom(-1)} title="Zoom out">−</button>
              <small>{scale}px/s</small>
            </div>
            <div className="vC-cols">
              {groups.map((g) => (
                <div key={g.src.id} className={`vC-group vC-src-${g.src.id}`} style={groupStyle(g.cols)}>
                  <div className="vC-group-title" title={`${g.src.name} (${g.src.mode === 'diarize' ? 'several speakers' : 'one speaker'})`}>
                    {g.src.name}
                  </div>
                  <div className="vC-group-row">
                    {g.cols.map((c) => (
                      <ColHeader key={c.sp.id} c={c} view={view} actions={actions} lastEnd={lastEnd[c.sp.id]} corrections={corrections} onToggle={() => togglePin(c)} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="vC-body" style={{ height: bodyH }}>
            <div className="vC-gutter vC-axis">
              {ticks.map((t) => (
                <div key={t} className={t % labelEvery === 0 ? 'vC-tick vC-tick-major' : 'vC-tick'} style={{ top: t * scale }}>
                  {t % labelEvery === 0 && fmt(t)}
                </div>
              ))}
              {overlaps.map((o, i) => (
                <div key={i} className="vC-gutter-ov" style={{ top: o.start * scale, height: Math.max(4, (o.end - o.start) * scale) }} title="Overlapping speech" />
              ))}
              <div className="vC-live-label" style={{ top: clock * scale }}>
                ● {fmt(clock)}
              </div>
            </div>
            <div className="vC-cols vC-cols-body">
              {overlaps.map((o, i) => (
                <div key={i} className="vC-overlap" style={{ top: o.start * scale, height: Math.max(4, (o.end - o.start) * scale) }} />
              ))}
              <div className="vC-pending" style={{ top: (clock - PENDING) * scale, height: PENDING * scale }}>
                finalizing…
              </div>
              <div className="vC-live" style={{ top: clock * scale }} />
              {groups.map((g) => (
                <div key={g.src.id} className="vC-group" style={groupStyle(g.cols)}>
                  {g.cols.map((c) => (
                    <div
                      key={c.sp.id}
                      className={`vC-col ${c.wide ? 'vC-wide' : 'vC-narrow'} ${c.ghost ? 'vC-ghostcol' : ''}`}
                      style={{ '--h': hue(c.sp.id) } as React.CSSProperties}
                      onClick={c.wide ? undefined : () => togglePin(c)}
                      title={c.wide ? undefined : `${nameOf(view, c.sp.id)}: click to expand and pin`}
                    >
                      {c.wide
                        ? (bySpeaker[c.sp.id] ?? []).map((s) => <SegBox key={s.id} s={s} view={view} scale={scale} overlap={overlapIds.has(s.id)} />)
                        : (bySpeaker[c.sp.id] ?? []).map((s) => (
                            <div key={s.id} className="vC-mark" style={{ top: s.start * scale, height: Math.max(3, (s.end - s.start) * scale) }} />
                          ))}
                      {/* ghosts of segments that just moved away from this column */}
                      {view.recentMoves
                        .filter((m) => m.fromSpeakerId === c.sp.id)
                        .map((m) => {
                          const s = view.segments.find((x) => x.id === m.segmentId)
                          if (!s) return null
                          return (
                            <div key={`${m.segmentId}@${m.at}`} className="vC-ghost" style={{ top: s.start * scale, minHeight: Math.max(18, (s.end - s.start) * scale) }}>
                              {c.wide ? <>moved to {nameOf(view, m.toSpeakerId)} →</> : '→'}
                            </div>
                          )
                        })}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* correction notes */}
        <div className="vC-toasts" style={{ top: HEAD + 8 }}>
          {corrections.map((c) => {
            const merged = mergedAway.has(c.from)
            const first = view.segments.find((s) => s.id === c.ids[0])
            return (
              <div key={`${c.from}>${c.to}@${c.at}`} className="vC-toast">
                <b>Correction:</b>{' '}
                {merged ? (
                  <>
                    {nameOf(view, c.from)} was the same voice as {nameOf(view, c.to)}; its {c.ids.length} segments merged into {nameOf(view, c.to)}. The column {nameOf(view, c.from)} closes.
                  </>
                ) : (
                  <>
                    {c.ids.length === 1 ? '1 segment' : `${c.ids.length} segments`} moved from {nameOf(view, c.from)} to {nameOf(view, c.to)}.
                  </>
                )}
                {first && !merged && (
                  <button onClick={() => scrollToTime(first.start)}>show {fmt(first.start)}</button>
                )}
              </div>
            )
          })}
        </div>

        {!view.follow && (
          <button className="vC-jump" onClick={jumpToLive}>
            ↓ Jump to live ({fmt(clock)})
          </button>
        )}
      </div>

      {/* overview / minimap of the whole session */}
      <div className="vC-ov">
        <div className="vC-ov-head" style={{ height: HEAD }}>
          <b>Overview</b>
          <small>00:00 – {fmt(clock)}</small>
          <div className="vC-ov-names">
            {ovCols.map((c) => (
              <span key={c.sp.id} style={{ '--h': hue(c.sp.id) } as React.CSSProperties} title={nameOf(view, c.sp.id)}>
                {nameOf(view, c.sp.id).slice(0, 2)}
              </span>
            ))}
          </div>
        </div>
        <div className="vC-ov-map" ref={ovRef} onPointerDown={ovPointer} onPointerMove={ovPointer}>
          {[...Array(Math.floor(total / 300) + 1).keys()].map((i) => (
            <div key={i} className="vC-ov-tick" style={{ top: `${((i * 300) / total) * 100}%` }}>
              {fmt(i * 300)}
            </div>
          ))}
          <div className="vC-ov-strips">
            {ovCols.map((c) => (
              <div key={c.sp.id} className={`vC-ov-strip ${c.wide ? 'vC-ov-wide' : ''}`} style={{ '--h': hue(c.sp.id) } as React.CSSProperties}>
                {(bySpeaker[c.sp.id] ?? []).map((s) => (
                  <div key={s.id} style={{ top: `${(s.start / total) * 100}%`, height: `max(1px, ${((s.end - s.start) / total) * 100}%)` }} />
                ))}
              </div>
            ))}
          </div>
          <div
            className={`vC-ov-port ${view.follow ? 'vC-ov-port-live' : ''}`}
            style={{ top: `${(Math.max(0, t0) / total) * 100}%`, height: `max(6px, ${((Math.min(total, t1) - Math.max(0, t0)) / total) * 100}%)` }}
          />
        </div>
      </div>
    </div>
  )
}

function ColHeader({
  c,
  view,
  actions,
  lastEnd,
  corrections,
  onToggle,
}: {
  c: Col
  view: SessionView
  actions: Actions
  lastEnd: number | undefined
  corrections: { from: string; to: string; ids: string[] }[]
  onToggle: () => void
}) {
  const label = c.sp.label
  const src = view.sources.find((s) => s.id === c.sp.sourceId)?.name ?? ''
  const style = { '--h': hue(c.sp.id) } as React.CSSProperties
  const incoming = corrections.filter((x) => x.to === c.sp.id)
  if (c.ghost) {
    const into = corrections.find((x) => x.from === c.sp.id)
    return (
      <div className="vC-hcell vC-wide vC-ghostcol" style={style}>
        <s>{nameOf(view, c.sp.id)}</s>
        <small>merged into {into ? nameOf(view, into.to) : '?'} → column closes</small>
      </div>
    )
  }
  if (!c.wide)
    return (
      <div className="vC-hcell vC-narrow" style={style} onClick={onToggle} title={`${nameOf(view, c.sp.id)} (${label}, ${src}). Last spoke ${lastEnd != null ? fmt(lastEnd) : '—'}. Click to expand and pin.`}>
        <span className="vC-vname">{nameOf(view, c.sp.id)}</span>
        {incoming.length > 0 && <span className="vC-dot" />}
      </div>
    )
  return (
    <div className={`vC-hcell vC-wide ${incoming.length ? 'vC-flash' : ''}`} style={style}>
      <RenameableName view={view} actions={actions} speakerId={c.sp.id} className="vC-name" />
      <small className="vC-sub">
        {view.displayNames[c.sp.id] ? '' : `${label} · `}
        {src}
      </small>
      <small className="vC-sub">
        {c.pinned ? 'pinned' : c.active ? 'active' : 'idle'} · last {lastEnd != null ? fmt(lastEnd) : '—'}
      </small>
      {incoming.map((x) => (
        <small key={x.from} className="vC-incoming">
          +{x.ids.length} from {nameOf(view, x.from)}
        </small>
      ))}
      <button className="vC-pin" onClick={onToggle} title={c.pinned ? 'Unpin (collapse when idle)' : 'Collapse to a strip'}>
        {c.pinned ? 'unpin' : '–'}
      </button>
    </div>
  )
}

function SegBox({ s, view, scale, overlap }: { s: Segment; view: SessionView; scale: number; overlap: boolean }) {
  const move = moveOf(view, s.id)
  const sw = isLanguageSwitch(view, s)
  const cs = hasCodeSwitch(s)
  const h = Math.max(18, (s.end - s.start) * scale)
  return (
    <div
      className={`vC-seg ${sw ? 'vC-switch' : ''} ${move ? 'vC-moved' : ''} ${overlap ? 'vC-ovl' : ''}`}
      style={{ top: s.start * scale, height: h, '--hpx': `${h}px` } as React.CSSProperties}
      title={`${fmt(s.start)}–${fmt(s.end)} · ${s.lang}`}
    >
      <div className="vC-meta">
        <span className="vC-time">{fmt(s.start)}</span>
        <span className="vC-lang">{s.lang}</span>
        {sw && <span className="vC-swbadge">language switch → {s.lang.toUpperCase()}</span>}
        {move && <span className="vC-movebadge">moved from {nameOf(view, move.fromSpeakerId)}</span>}
      </div>
      <div className="vC-text">
        {cs
          ? s.runs.map((r, i) => (
              <span key={i}>
                <span className={`vC-run-lang vC-l-${r.lang}`}>{r.lang}</span>
                {r.text}{' '}
              </span>
            ))
          : s.runs.map((r) => r.text).join(' ')}
      </div>
      {view.showTranslation && s.translation && <div className="vC-tr">{s.translation}</div>}
    </div>
  )
}
