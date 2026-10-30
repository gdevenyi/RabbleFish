// PROTOTYPE: throwaway. Variant A, "Linear time grid": y = seconds × scale.
// Segments are absolutely positioned boxes in fixed-width columns. Silence is empty space.
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import type { Actions, Move, Segment, SessionView } from '../types'
import { fmt, hasCodeSwitch, nameOf, SOURCES, SPEAKERS } from '../session'
import './A.css'

export const name = 'Linear time grid'

const COL_W = 260
const RULER_W = 64
const SCALES = [3, 4, 6, 8, 10, 12, 16, 20, 28, 40] // px per second
const BOTTOM_PAD = 110 // space below the live line (switcher sits there)
const FINALIZE_DELAY = 3
const MOVE_WINDOW = 6

interface Col {
  id: string
  sourceId: string
  x: number
  w: number
  ghost: boolean // column of a speaker that just merged away
  mergedInto?: string
}

function labelOf(id: string): string {
  return SPEAKERS.find((s) => s.id === id)?.label ?? id
}

function NameEditor({ view, actions, speakerId }: { view: SessionView; actions: Actions; speakerId: string }) {
  const [editing, setEditing] = useState(false)
  if (editing)
    return (
      <input
        className="vA-name-input"
        autoFocus
        defaultValue={view.displayNames[speakerId] ?? ''}
        placeholder={labelOf(speakerId)}
        onBlur={(e) => {
          actions.rename(speakerId, e.currentTarget.value)
          setEditing(false)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') e.currentTarget.blur()
          if (e.key === 'Escape') setEditing(false)
        }}
      />
    )
  return (
    <button className="vA-name" title="Click to set the display name" onClick={() => setEditing(true)}>
      {nameOf(view, speakerId)} <span className="vA-pencil">✎</span>
    </button>
  )
}

export function Variant({ view, actions }: { view: SessionView; actions: Actions }) {
  const [scaleIdx, setScaleIdx] = useState(5)
  const scale = SCALES[scaleIdx]
  const scrollRef = useRef<HTMLDivElement>(null)
  const headerRef = useRef<HTMLDivElement>(null)
  const expectedTop = useRef<number | null>(null)
  const prevScale = useRef(scale)
  // Speakers that merged into another speaker while this variant was open.
  const [merged, setMerged] = useState<Record<string, string>>({})

  const visibleIds = useMemo(() => new Set(view.speakers.map((s) => s.id)), [view.speakers])

  useEffect(() => {
    const add: Record<string, string> = {}
    for (const m of view.recentMoves) if (!visibleIds.has(m.fromSpeakerId) && !merged[m.fromSpeakerId]) add[m.fromSpeakerId] = m.toSpeakerId
    if (Object.keys(add).length) setMerged((p) => ({ ...p, ...add }))
  }, [view.recentMoves, visibleIds, merged])

  // --- derived data --------------------------------------------------------
  const segById = useMemo(() => new Map(view.segments.map((s) => [s.id, s])), [view.segments])

  const { prevLang, nextStart, bySpeaker } = useMemo(() => {
    const prevLang = new Map<string, string>()
    const nextStart = new Map<string, number>()
    const bySpeaker = new Map<string, Segment[]>()
    const last = new Map<string, Segment>()
    for (const s of view.segments) {
      const p = last.get(s.speakerId)
      if (p) {
        if (p.lang !== s.lang) prevLang.set(s.id, p.lang)
        nextStart.set(p.id, s.start)
      }
      last.set(s.speakerId, s)
      if (!bySpeaker.has(s.speakerId)) bySpeaker.set(s.speakerId, [])
      bySpeaker.get(s.speakerId)!.push(s)
    }
    return { prevLang, nextStart, bySpeaker }
  }, [view.segments])

  const overlaps = useMemo(() => {
    const raw: [number, number][] = []
    const segs = view.segments
    for (let i = 0; i < segs.length; i++)
      for (let j = i + 1; j < segs.length && segs[j].start < segs[i].end; j++)
        if (segs[j].speakerId !== segs[i].speakerId) raw.push([segs[j].start, Math.min(segs[i].end, segs[j].end)])
    raw.sort((a, b) => a[0] - b[0])
    const out: [number, number][] = []
    for (const r of raw) {
      const l = out[out.length - 1]
      if (l && r[0] <= l[1]) l[1] = Math.max(l[1], r[1])
      else out.push([r[0], r[1]])
    }
    return out
  }, [view.segments])

  // Columns: live speakers plus a ghost column for a speaker that just merged away.
  const ghostIds = new Map<string, Move>()
  for (const m of view.recentMoves) if (!visibleIds.has(m.fromSpeakerId)) ghostIds.set(m.fromSpeakerId, m)
  const cols: Col[] = []
  let x = 0
  for (const sp of SPEAKERS) {
    const live = visibleIds.has(sp.id)
    const gm = ghostIds.get(sp.id)
    if (!live && !gm) continue
    let w = COL_W
    if (gm) {
      const age = view.clock - gm.at
      w = age < 4 ? COL_W : Math.max(0, COL_W * (1 - (age - 4) / 2))
      if (w < 2) continue
    }
    cols.push({ id: sp.id, sourceId: sp.sourceId, x, w, ghost: !live, mergedInto: gm?.toSpeakerId })
    x += w
  }
  const colsW = Math.max(x, 1)
  const groups = SOURCES.map((src) => ({ src, cols: cols.filter((c) => c.sourceId === src.id) })).filter((g) => g.cols.length)

  const bodyH = view.clock * scale + BOTTOM_PAD
  const liveY = view.clock * scale

  // --- scrolling -----------------------------------------------------------
  const setTop = (el: HTMLDivElement, top: number) => {
    el.scrollTop = top
    expectedTop.current = el.scrollTop
  }

  // Keep the time at the viewport centre when zooming (unless following).
  useLayoutEffect(() => {
    const el = scrollRef.current
    if (!el || prevScale.current === scale) return
    const hh = headerRef.current?.offsetHeight ?? 0
    const viewH = el.clientHeight - hh
    const t = (el.scrollTop + viewH / 2) / prevScale.current
    prevScale.current = scale
    if (!view.follow) setTop(el, t * scale - viewH / 2)
  }, [scale, view.follow])

  // Auto-follow: keep the live edge at the bottom of the view.
  useLayoutEffect(() => {
    const el = scrollRef.current
    if (!el || !view.follow) return
    setTop(el, el.scrollHeight)
  }, [view.follow, view.clock, scale, view.segments.length, view.showTranslation])

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    if (expectedTop.current !== null && Math.abs(el.scrollTop - expectedTop.current) < 1) return // ours, or horizontal only
    expectedTop.current = el.scrollTop
    const fromBottom = el.scrollHeight - el.clientHeight - el.scrollTop
    if (view.follow && fromBottom > 30) actions.setFollow(false)
    else if (!view.follow && fromBottom < 4) actions.setFollow(true)
  }

  const jumpToLive = () => {
    actions.setFollow(true)
    const el = scrollRef.current
    if (el) setTop(el, el.scrollHeight)
  }

  // --- ruler -----------------------------------------------------------------
  const minorStep = scale >= 8 ? 10 : 30
  const ticks: { t: number; major: boolean }[] = []
  for (let t = 0; t <= view.clock; t += minorStep) ticks.push({ t, major: t % 60 === 0 })

  return (
    <div className="vA-root">
      <div className="vA-toolbar">
        <span className="vA-zoom">
          Zoom
          <button disabled={scaleIdx === 0} onClick={() => setScaleIdx((i) => Math.max(0, i - 1))}>
            −
          </button>
          <span className="vA-zoomval">{scale} px/s</span>
          <button disabled={scaleIdx === SCALES.length - 1} onClick={() => setScaleIdx((i) => Math.min(SCALES.length - 1, i + 1))}>
            +
          </button>
        </span>
        <span className={view.follow ? 'vA-follow on' : 'vA-follow'}>{view.follow ? '● Following live' : '❚❚ Not following'}</span>
        <span className="vA-legend">
          <span className="vA-legend-band" /> overlapping speech
          <span className="vA-switch">EN→FR</span> language switch
          <span className="vA-legend-moved" /> diarization correction
        </span>
      </div>

      <div className="vA-scroll" ref={scrollRef} onScroll={onScroll} onWheel={(e) => e.deltaY < 0 && view.follow && actions.setFollow(false)}>
        <div className="vA-content" style={{ width: RULER_W + colsW }}>
          <div className="vA-header" ref={headerRef} style={{ width: RULER_W + colsW }}>
            <div className="vA-corner" style={{ width: RULER_W }}>
              time
            </div>
            {groups.map(({ src, cols: gc }) => (
              <div key={src.id} className={`vA-group vA-src-${src.id}`} style={{ width: gc.reduce((a, c) => a + c.w, 0) }}>
                <div className="vA-group-name">
                  <span style={{ left: RULER_W + 6 }}>
                    {src.name} <small>{src.mode === 'diarize' ? '· diarized' : '· one speaker'}</small>
                  </span>
                </div>
                <div className="vA-names">
                  {gc.map((c) => (
                    <div key={c.id} className={c.ghost ? 'vA-head vA-head-ghost' : 'vA-head'} style={{ width: c.w }}>
                      {c.ghost ? (
                        <>
                          <span className="vA-name vA-struck">{nameOf(view, c.id)}</span>
                          <span className="vA-merged-note">merged into {nameOf(view, c.mergedInto!)} →</span>
                        </>
                      ) : (
                        <>
                          <NameEditor view={view} actions={actions} speakerId={c.id} />
                          <span className="vA-label">
                            {labelOf(c.id)}
                            {Object.entries(merged)
                              .filter(([, to]) => to === c.id)
                              .map(([from]) => ` · incl. ${labelOf(from)}`)
                              .join('')}
                          </span>
                        </>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div className="vA-body" style={{ height: bodyH, width: RULER_W + colsW }}>
            <div className="vA-ruler" style={{ width: RULER_W, height: bodyH }}>
              {ticks.map(({ t, major }) => (
                <div key={t} className={major ? 'vA-tick vA-major' : 'vA-tick'} style={{ top: t * scale }}>
                  {(major || scale >= 16) && <span>{fmt(t)}</span>}
                </div>
              ))}
              {overlaps.map(([a, b]) => (
                <div key={a} className="vA-ruler-ov" style={{ top: a * scale, height: Math.max(2, (b - a) * scale) }} />
              ))}
              <div className="vA-ruler-live" style={{ top: liveY }}>
                {fmt(view.clock)}
              </div>
            </div>

            <div
              className="vA-cols"
              style={{ width: colsW, height: bodyH, backgroundImage: `repeating-linear-gradient(to bottom, #dfe3ea 0 1px, transparent 1px ${60 * scale}px)` }}
            >
              {cols.map((c) => (
                <div key={c.id} className={`vA-col vA-src-${c.sourceId}${c.ghost ? ' vA-col-ghost' : ''}`} style={{ left: c.x, width: c.w }}>
                  {!c.ghost &&
                    (bySpeaker.get(c.id) ?? []).map((s) => (
                      <SegBox key={s.id} view={view} seg={s} scale={scale} prevLang={prevLang.get(s.id)} next={nextStart.get(s.id)} />
                    ))}
                  {view.recentMoves
                    .filter((m) => m.fromSpeakerId === c.id)
                    .map((m) => {
                      const s = segById.get(m.segmentId)
                      if (!s) return null
                      const age = view.clock - m.at
                      return (
                        <div
                          key={`g-${m.segmentId}`}
                          className="vA-ghost"
                          style={{ top: s.start * scale, minHeight: Math.max(18, (s.end - s.start) * scale), opacity: Math.max(0.15, 1 - age / MOVE_WINDOW) }}
                        >
                          {fmt(s.start)} moved to <b>{nameOf(view, m.toSpeakerId)}</b> →
                        </div>
                      )
                    })}
                </div>
              ))}
              {overlaps.map(([a, b]) => (
                <div key={a} className="vA-band" style={{ top: a * scale, height: Math.max(2, (b - a) * scale) }} />
              ))}
              <div className="vA-pending" style={{ top: (view.clock - FINALIZE_DELAY) * scale, height: FINALIZE_DELAY * scale }}>
                <span>finalizing…</span>
              </div>
              <div className="vA-live" style={{ top: liveY }} />
            </div>
          </div>
        </div>
      </div>

      {!view.follow && (
        <button className="vA-jump" onClick={jumpToLive}>
          ↓ Jump to live ({fmt(view.clock)})
        </button>
      )}
    </div>
  )
}

function SegBox({ view, seg, scale, prevLang, next }: { view: SessionView; seg: Segment; scale: number; prevLang?: string; next?: number }) {
  const dur = seg.end - seg.start
  const durH = Math.max(3, dur * scale)
  const minH = Math.max(18, durH - 2)
  // The box may grow past its duration to fit its text, but not past the next segment of the same speaker.
  const maxH = next === undefined ? undefined : Math.max(minH, (next - seg.start) * scale - 3)
  const move = view.recentMoves.find((m) => m.segmentId === seg.id && m.toSpeakerId === seg.speakerId)
  const age = move ? view.clock - move.at : 0
  const style = {
    top: seg.start * scale,
    minHeight: minH,
    '--vA-maxh': maxH === undefined ? 'none' : `${maxH}px`,
    ...(move ? { '--vA-flash': String(Math.max(0, 1 - age / MOVE_WINDOW)) } : {}),
  } as CSSProperties
  const code = hasCodeSwitch(seg)
  return (
    <>
      <div className="vA-dur" style={{ top: seg.start * scale, height: durH }} title={`${fmt(seg.start)}–${fmt(seg.end)}`} />
      <div className={`vA-seg${move ? ' vA-moved' : ''}${prevLang ? ' vA-switched' : ''}`} style={style}>
        <div className="vA-seg-head">
          <span className="vA-t">{fmt(seg.start)}</span>
          <span className="vA-d">{dur.toFixed(1)} s</span>
          {prevLang && (
            <span className="vA-switch" title="Language switch">
              {prevLang.toUpperCase()}→{seg.lang.toUpperCase()}
            </span>
          )}
          <span className="vA-lang">{code ? 'mixed' : seg.lang}</span>
        </div>
        {move && <div className="vA-movenote">↪ moved here from {nameOf(view, move.fromSpeakerId)}</div>}
        <div className="vA-text">
          {code
            ? seg.runs.map((r, i) => (
                <span key={i} className={`vA-run vA-run-${r.lang}`}>
                  <span className="vA-runlang">{r.lang}</span>
                  {r.text}{' '}
                </span>
              ))
            : seg.runs.map((r) => r.text).join(' ')}
        </div>
        {view.showTranslation && seg.translation && <div className="vA-tr">{seg.translation}</div>}
      </div>
    </>
  )
}

