// The Timeline: one Column per Speaker, grouped by Source, time on the vertical axis
// (linear, with Silence folds), the Live edge at the bottom, and the Overview on the right.
import { type CSSProperties, Fragment, useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { Api } from '../api'
import { COLLAPSED_PX, type ColumnInput, layoutColumns, type PinState, togglePin } from './columns'
import { ColumnHeader, type HeaderColumn, hueStyle } from './ColumnHeader'
import { buildModel, formatDuration, formatTime, liveEdge, nameOf } from './model'
import { Overview } from './Overview'
import { segmentBoxHeight } from './segmentBox'
import { type AppState, type Merge, type Segment, type Speaker, warningHint, warningLabel } from './state'
import { buildTimeScale } from './timeScale'
import './timeline.css'

const HEAD = 92 // header height in px (source group title + Column headers)
const GUTTER = 56
const TAIL = 150 // space below the Live edge, for the Partial text
const SCALES = [4, 8, 12, 18, 26, 36] // px per second
const DEFAULT_SCALE = 3
const FINALIZING_S = 3
const MERGE_FADE_S = 6
const OVERSCAN_PX = 900
const FOLLOW_GAP_PX = 40 // the user left the Live edge when the gap is larger
const PARTIAL_MIN_W = 240

interface Col extends HeaderColumn {
  key: string
  kind: 'speaker' | 'merged' | 'pending'
  sourceKey: string
  x: number
  w: number
}

interface Group {
  key: string
  description: string
  x: number
  w: number
  cols: Col[]
}

export function Timeline({ state, clientNow, api, onError }: { state: AppState; clientNow: number; api: Api; onError: (e: unknown) => void }) {
  const model = useMemo(() => buildModel(state), [state])
  const now = liveEdge(state, clientNow)
  const running = state.session.state === 'started'

  const scrollRef = useRef<HTMLDivElement>(null)
  const expectedTop = useRef<number | null>(null)
  const pendingCenter = useRef<number | null>(null)
  const [scaleIdx, setScaleIdx] = useState(DEFAULT_SCALE)
  const [pins, setPins] = useState<Record<string, PinState>>({})
  const [follow, setFollow] = useState(true)
  const [port, setPort] = useState({ top: 0, height: 600, width: 900 })
  const [showTranslation, setShowTranslation] = useState(true)
  const [dismissed, dismiss] = useDismissedMerges(state.session.startedAt)

  // --- time axis ------------------------------------------------------------------
  const px = SCALES[scaleIdx]
  const spans = useMemo(
    () => [...model.segments.map((s) => ({ start: s.start, end: s.end })), ...Object.values(state.partials).map((p) => ({ start: p.since, end: p.audioTime }))],
    [model, state.partials],
  )
  const scale = useMemo(() => buildTimeScale(spans, now, { pxPerSec: px }), [spans, now, px])
  const bodyHeight = scale.height + TAIL

  // --- Columns --------------------------------------------------------------------
  const width = Math.max(200, port.width - GUTTER)
  const { groups, cols } = useMemo(() => {
    const recentMerges = state.merges.filter((m) => clientNow - m.receivedAt < MERGE_FADE_S)
    const inputs: ColumnInput[] = []
    const effPins: Record<string, PinState> = { ...pins }
    const draft: { key: string; description: string; cols: Omit<Col, 'x' | 'w' | 'wide' | 'pinned' | 'active'>[] }[] = []
    for (const g of model.groups) {
      const gcols: (typeof draft)[number]['cols'] = []
      // While a Source has Partial text, its most recent Speaker stays wide, so that the
      // Source group has room for the Partial text.
      let partialHolder: Speaker | undefined
      if (state.partials[g.key])
        for (const sp of g.speakers) if (!partialHolder || (model.lastSpokeAt.get(sp.id) ?? -1) > (model.lastSpokeAt.get(partialHolder.id) ?? -1)) partialHolder = sp
      for (const sp of g.speakers) {
        gcols.push({ key: sp.id, kind: 'speaker', sourceKey: g.key, sp })
        inputs.push({ id: sp.id, lastSpokeAt: model.lastSpokeAt.get(sp.id) ?? null, forceWide: sp === partialHolder })
      }
      for (const m of recentMerges) {
        const sp = state.speakers[m.from]
        if (!sp || sp.sourceKey !== g.key) continue
        const into = state.speakers[model.targets.get(m.from) ?? m.into]
        gcols.push({ key: `merged:${sp.id}`, kind: 'merged', sourceKey: g.key, sp, mergedInto: into })
        inputs.push({ id: `merged:${sp.id}`, lastSpokeAt: null })
        effPins[`merged:${sp.id}`] = 'collapsed'
      }
      // A merged Column fades out in its old place.
      gcols.sort((a, b) => a.sp.order - b.sp.order)
      if (g.speakers.length === 0) {
        // No Speaker yet: a provisional Column holds the Partial text of the Source.
        const sp: Speaker = { id: `pending:${g.key}`, sourceKey: g.key, label: 'No Speaker yet', displayName: null, order: -1 }
        gcols.push({ key: sp.id, kind: 'pending', sourceKey: g.key, sp })
        inputs.push({ id: sp.id, lastSpokeAt: null, forceWide: true })
      }
      draft.push({ key: g.key, description: g.description, cols: gcols })
    }
    const layout = new Map(layoutColumns(inputs, { now, width, pins: effPins }).map((l) => [l.id, l]))
    const wideCount = [...layout.values()].filter((l) => l.wide).length
    const collapsedCount = layout.size - wideCount
    const wideW = wideCount ? (width - collapsedCount * COLLAPSED_PX) / wideCount : 0
    let x = 0
    const groups: Group[] = draft.map((g) => {
      const gx = x
      const gcols = g.cols.map((c) => {
        const l = layout.get(c.key)!
        const w = l.wide ? wideW : COLLAPSED_PX
        const col: Col = { ...c, wide: l.wide, pinned: l.pinned, active: l.active, x, w }
        x += w
        return col
      })
      return { key: g.key, description: g.description, x: gx, w: x - gx, cols: gcols }
    })
    return { groups, cols: groups.flatMap((g) => g.cols) }
  }, [model, state.partials, state.merges, state.speakers, pins, clientNow, now, width])

  // --- scrolling and follow mode ---------------------------------------------------
  const programmaticScroll = (top: number) => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTop = top
    expectedTop.current = el.scrollTop
  }
  const measure = useCallback(() => {
    const el = scrollRef.current
    if (el) setPort({ top: el.scrollTop, height: el.clientHeight, width: el.clientWidth })
  }, [])

  useLayoutEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [measure])

  useLayoutEffect(() => {
    const el = scrollRef.current
    if (!el) return
    if (pendingCenter.current !== null && !follow) programmaticScroll(scale.y(pendingCenter.current) - (el.clientHeight - HEAD) / 2)
    pendingCenter.current = null
    if (follow && Math.abs(el.scrollTop - (el.scrollHeight - el.clientHeight)) > 1) programmaticScroll(el.scrollHeight - el.clientHeight)
    if (el.scrollTop !== port.top || el.clientHeight !== port.height || el.clientWidth !== port.width) measure()
  })

  const onScroll = () => {
    const el = scrollRef.current!
    measure()
    if (expectedTop.current !== null && Math.abs(el.scrollTop - expectedTop.current) < 2) return
    expectedTop.current = null
    const gap = el.scrollHeight - el.scrollTop - el.clientHeight
    if (gap >= FOLLOW_GAP_PX && follow) setFollow(false)
    // Follow again only when the user scrolled all the way down.
    if (gap < 2 && !follow) setFollow(true)
  }
  // The user moves up: stop following at once, so that the next tick does not pull back.
  const userIntent = () => {
    expectedTop.current = null
    if (follow) setFollow(false)
  }
  const scrollToTime = (t: number) => {
    const el = scrollRef.current
    if (!el) return
    programmaticScroll(scale.y(t) - (el.clientHeight - HEAD) / 2)
    setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < FOLLOW_GAP_PX)
    measure()
  }
  const jumpToLive = () => {
    setFollow(true)
    const el = scrollRef.current
    if (el) programmaticScroll(el.scrollHeight - el.clientHeight)
  }
  const zoom = (d: number) => {
    const next = Math.min(SCALES.length - 1, Math.max(0, scaleIdx + d))
    if (next === scaleIdx) return
    const el = scrollRef.current
    if (el) pendingCenter.current = scale.time(el.scrollTop + (el.clientHeight - HEAD) / 2)
    setScaleIdx(next)
  }

  // --- visible range ----------------------------------------------------------------
  const viewFrom = scale.time(port.top)
  const viewTo = scale.time(port.top + port.height - HEAD)
  const yMin = port.top - OVERSCAN_PX
  const yMax = port.top + port.height + OVERSCAN_PX
  const visible = (s: { start: number; end: number }) => scale.y(s.end) + 200 >= yMin && scale.y(s.start) <= yMax

  // --- gutter ticks -------------------------------------------------------------------
  const [minor, major] = px >= 18 ? [10, 30] : px >= 8 ? [30, 60] : [60, 300]
  const ticks: number[] = []
  for (let t = Math.max(0, Math.floor(viewFrom / minor) * minor - 10 * minor); t <= Math.min(now, viewTo + 10 * minor); t += minor) {
    if (!scale.folds.some((f) => t > f.start && t < f.end)) ticks.push(t)
  }

  const finalizingFrom = Math.min(now - FINALIZING_S, ...Object.values(state.partials).map((p) => p.since))
  const columnSpeakers = cols.filter((c) => c.kind === 'speaker')
  const sourceMode = (key: string) => state.sources.find((s) => s.key === key)?.mode

  const merges = state.merges.filter((m) => !dismissed.has(mergeKey(m)))
  const empty = groups.length === 0

  return (
    <div className="tl-root">
      <div className="tl-toolbar">
        <span className="tl-zoom" role="group" aria-label="Zoom">
          Zoom
          <button onClick={() => zoom(-1)} disabled={scaleIdx === 0} title="Zoom out (fewer px per second)" aria-label="Zoom out">
            −
          </button>
          <button onClick={() => zoom(1)} disabled={scaleIdx === SCALES.length - 1} title="Zoom in (more px per second)" aria-label="Zoom in">
            +
          </button>
          <small>{px} px/s</small>
        </span>
        <label>
          <input type="checkbox" checked={showTranslation} onChange={(e) => setShowTranslation(e.target.checked)} /> Translation
        </label>
        <span className={`tl-follow ${follow && running ? 'on' : ''}`} data-testid="follow-state">
          {!running ? '' : follow ? 'Following the Live edge' : 'Follow is off'}
        </span>
      </div>
      <div className="tl-main">
        <div
          className="tl-scroll"
          ref={scrollRef}
          onScroll={onScroll}
          onWheel={(e) => e.deltaY < 0 && userIntent()}
          onKeyDown={(e) => ['ArrowUp', 'PageUp', 'Home'].includes(e.key) && userIntent()}
          tabIndex={0}
          data-testid="timeline"
        >
          <div className="tl-head" style={{ height: HEAD }}>
            <div className="tl-gutter tl-gutter-head">time</div>
            <div className="tl-groups">
              {groups.map((g) => {
                const st = state.sourceStatus[g.key]
                const warning = st?.warning ?? null
                return (
                  <div key={g.key} className={`tl-group${warning ? ' tl-group-warn' : ''}`} style={{ width: g.w }} data-testid="source-group">
                    <div
                      className="tl-group-title"
                      title={`${g.description} (${g.key})${st?.message ? `: ${st.message}` : ''}${warning ? `\n${warningHint(warning)}` : ''}`}
                    >
                      {st && <span className={`tl-status tl-status-${st.state}`} aria-label={`Source status: ${st.state}`} />}
                      <span className="tl-group-name">{g.description}</span>
                      {warning && (
                        <span className="tl-warn" data-testid="column-warning" title={warningHint(warning)}>
                          {warningLabel(warning)}
                        </span>
                      )}
                    </div>
                    <div className="tl-group-row">
                      {g.cols.map((c) =>
                        c.kind === 'pending' ? (
                          <div key={c.key} className="tl-hcell tl-wide tl-pending-head" style={{ width: c.w }}>
                            <span className="tl-name">No Speaker yet</span>
                            {warning ? (
                              <small className="tl-sub tl-sub-warn" title={warningHint(warning)}>
                                {warning === 'muted' ? 'The Source is muted: no audio' : 'No sound from this Source'}
                              </small>
                            ) : (
                              <small className="tl-sub">Partial text of this Source shows here</small>
                            )}
                          </div>
                        ) : (
                          <ColumnHeader
                            key={c.key}
                            col={c}
                            width={c.w}
                            sp={c.sp}
                            api={api}
                            groups={model.groups}
                            onError={onError}
                            lastSpokeAt={model.lastSpokeAt.get(c.sp.id)}
                            onTogglePin={() => setPins((p) => togglePin(p, { id: c.sp.id, wide: c.wide, pinned: c.pinned, active: c.active }))}
                          />
                        ),
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          <div className="tl-body" style={{ height: bodyHeight }}>
            <div className="tl-gutter tl-axis">
              {ticks.map((t) => (
                <div key={t} className={t % major === 0 ? 'tl-tick tl-tick-major' : 'tl-tick'} style={{ top: scale.y(t) }}>
                  {t % major === 0 && formatTime(t)}
                </div>
              ))}
              {scale.folds.map((f) => (
                <div key={f.start} className="tl-fold-label" style={{ top: f.y, height: scale.y(f.end) - f.y }} title={`Silence fold: ${formatTime(f.start)}–${formatTime(f.end)}`}>
                  <span>{formatTime(f.start)}</span>
                  <span>{formatTime(f.end)}</span>
                </div>
              ))}
              {model.overlaps.bands.filter(visible).map((b) => (
                <div key={b.start} className="tl-gutter-overlap" style={{ top: scale.y(b.start), height: Math.max(3, scale.y(b.end) - scale.y(b.start)) }} />
              ))}
              {running && (
                <div className="tl-live-label" style={{ top: scale.y(now) }}>
                  {formatTime(now)}
                </div>
              )}
            </div>

            <div className="tl-cols" style={{ left: GUTTER }}>
              {cols.map((c) => (
                <div
                  key={c.key}
                  className={`tl-col ${c.wide ? 'tl-wide' : 'tl-collapsed'} tl-col-${c.kind}`}
                  style={{ ...hueStyle(c.sp), left: c.x, width: c.w }}
                  data-testid="column"
                  data-speaker={c.sp.id}
                  data-wide={c.wide}
                  onClick={c.kind === 'speaker' && !c.wide ? () => setPins((p) => togglePin(p, { id: c.sp.id, wide: c.wide, pinned: c.pinned, active: c.active })) : undefined}
                  title={c.kind === 'speaker' && !c.wide ? `${nameOf(c.sp)}: click to expand and pin` : undefined}
                />
              ))}

              {scale.folds.map((f) => (
                <div key={f.start} className="tl-fold" style={{ top: f.y, height: scale.y(f.end) - f.y }} data-testid="silence-fold">
                  Silence {formatDuration(f.silence)}
                </div>
              ))}

              {model.overlaps.bands.filter(visible).map((b) => (
                <div
                  key={b.start}
                  className="tl-overlap"
                  style={{ top: scale.y(b.start), height: Math.max(3, scale.y(b.end) - scale.y(b.start)) }}
                  title="Overlapping speech"
                  data-testid="overlap-band"
                />
              ))}

              {columnSpeakers.map((c) =>
                (model.bySpeaker.get(c.sp.id) ?? []).map((s, i, list) =>
                  !visible(s) ? null : c.wide ? (
                    <SegmentBox
                      key={s.id}
                      seg={s}
                      x={c.x}
                      w={c.w}
                      top={scale.y(s.start)}
                      height={scale.y(s.end) - scale.y(s.start)}
                      room={
                        i + 1 < list.length
                          ? scale.y(list[i + 1].start) - scale.y(s.start) - 2
                          : state.partials[c.sourceKey] // do not run under the Partial text
                            ? scale.y(now) + 4 - scale.y(s.start)
                            : Infinity
                      }
                      hue={hueStyle(c.sp)}
                      overlap={model.overlaps.ids.has(s.id)}
                      switchFrom={model.switches.has(s.id) ? previousLang(model.bySpeaker.get(c.sp.id)!, s) : null}
                      translation={showTranslation ? state.translations[s.id] : undefined}
                      mergedFrom={s.speakerId !== c.sp.id ? state.speakers[s.speakerId] : undefined}
                    />
                  ) : (
                    <div
                      key={s.id}
                      className="tl-mark"
                      style={{ ...hueStyle(c.sp), left: c.x + 9, width: c.w - 18, top: scale.y(s.start), height: Math.max(3, scale.y(s.end) - scale.y(s.start)) }}
                    />
                  ),
                ),
              )}

              {running && (
                <>
                  <div className="tl-finalizing" style={{ top: scale.y(finalizingFrom), height: scale.y(now) - scale.y(finalizingFrom) }} data-testid="finalizing">
                    finalizing…
                  </div>
                  <div className="tl-live" style={{ top: scale.y(now) }} data-testid="live-edge" />
                </>
              )}

              {groups.map((g) => {
                // Partial text sits just below the Live edge, across its Source group, like a
                // live caption: it has no Speaker yet, and it must not cover final Segments.
                // A dashed bracket on the left of the group marks the audio time that it covers.
                const p = state.partials[g.key]
                if (!p) return null
                const w = Math.min(width, Math.max(g.w - 6, PARTIAL_MIN_W))
                const x = Math.max(0, Math.min(g.x + 3, width - w))
                const from = scale.y(p.since)
                const diarized = sourceMode(g.key) !== 'single'
                return (
                  <Fragment key={g.key}>
                    <div className="tl-partial-span" style={{ left: g.x + 1, top: from, height: Math.max(4, scale.y(now) - from) }} />
                    <div
                      className="tl-partial"
                      style={{ left: x, width: w, top: scale.y(now) + 6 }}
                      data-testid="partial"
                      title={`Partial text of ${g.description}, ${formatTime(p.since)}–${formatTime(p.audioTime)}. It is not final${diarized ? ', and its Speaker is not known yet' : ''}.`}
                    >
                      <div className="tl-meta">
                        <span className="tl-partial-tag">Partial</span>
                        <span>
                          {g.description}
                          {diarized ? ' · Speaker not known yet' : ''} · since {formatTime(p.since)}
                        </span>
                      </div>
                      <div className="tl-partial-text">
                        <span>{p.text}</span>
                      </div>
                    </div>
                  </Fragment>
                )
              })}
            </div>
          </div>
          {empty && (
            <div className="tl-empty">
              {running ? 'Waiting for speech…' : 'No Session yet. Select the Sources, then push Start.'}
            </div>
          )}
        </div>

        {merges.length > 0 && (
          <div className="tl-notices" style={{ top: HEAD + 8 }}>
            {merges.map((m) => (
              <MergeNotice
                key={mergeKey(m)}
                merge={m}
                state={state}
                count={model.segments.filter((s) => s.speakerId === m.from).length}
                onShow={(t) => scrollToTime(t)}
                onDismiss={() => dismiss(mergeKey(m))}
              />
            ))}
          </div>
        )}

        {!follow && (
          <button className="tl-jump" onClick={jumpToLive} data-testid="jump-to-live">
            ↓ Jump to live ({formatTime(now)})
          </button>
        )}
      </div>
      <Overview
        speakers={columnSpeakers.map((c) => c.sp)}
        bySpeaker={model.bySpeaker}
        wide={new Set(columnSpeakers.filter((c) => c.wide).map((c) => c.sp.id))}
        end={now}
        view={{ from: viewFrom, to: viewTo }}
        following={follow}
        headHeight={HEAD}
        onSeek={scrollToTime}
      />
    </div>
  )
}

function previousLang(segs: Segment[], s: Segment): string | null {
  const i = segs.indexOf(s)
  for (let j = i - 1; j >= 0; j--) if (segs[j].lang) return segs[j].lang
  return null
}

function SegmentBox({
  seg,
  x,
  w,
  top,
  height,
  room,
  hue,
  overlap,
  switchFrom,
  translation,
  mergedFrom,
}: {
  seg: Segment
  x: number
  w: number
  top: number
  /** Height of the speech in px (linear time). */
  height: number
  /** Space down to the next Segment of the Column, in px. The box grows to fit its text up to there. */
  room: number
  hue: CSSProperties
  overlap: boolean
  switchFrom: string | null
  translation: { text: string; targetLang: string } | undefined
  mergedFrom: Speaker | undefined
}) {
  const { min, max, thin } = segmentBoxHeight(height, room)
  return (
    <div
      className={`tl-seg ${switchFrom ? 'tl-switch' : ''} ${overlap ? 'tl-seg-overlap' : ''} ${thin ? 'tl-seg-thin' : ''}`}
      style={{ ...hue, left: x + 3, width: w - 6, top, minHeight: min, maxHeight: max }}
      title={`${formatTime(seg.start)}–${formatTime(seg.end)}${seg.lang ? ` · ${seg.lang}` : ' · language not detected'}\n${seg.text}${translation ? `\n→ ${translation.text}` : ''}`}
      data-testid="segment"
      tabIndex={-1}
    >
      <div className="tl-meta">
        <span className="tl-time">{formatTime(seg.start)}</span>
        {seg.lang && <span className="tl-lang" data-testid="lang-tag">{seg.lang}</span>}
        {switchFrom && (
          <span className="tl-switch-badge" data-testid="language-switch">
            Language switch {switchFrom.toUpperCase()} → {seg.lang!.toUpperCase()}
          </span>
        )}
        {mergedFrom && <span className="tl-from" title={`This Segment was in the Column of ${nameOf(mergedFrom)} before a Merge`}>from {nameOf(mergedFrom)}</span>}
      </div>
      <div className="tl-text">{seg.text}</div>
      {translation && (
        <div className="tl-tr" data-testid="translation">
          <span className="tl-lang">{translation.targetLang}</span> {translation.text}
        </div>
      )}
    </div>
  )
}

function mergeKey(m: Merge) {
  return `${m.from}>${m.into}`
}

function MergeNotice({ merge, state, count, onShow, onDismiss }: { merge: Merge; state: AppState; count: number; onShow: (t: number) => void; onDismiss: () => void }) {
  const from = nameOf(state.speakers[merge.from])
  const into = nameOf(state.speakers[merge.into])
  const first = state.segmentOrder.map((id) => state.segments[id]).find((s) => s.speakerId === merge.from)
  return (
    <div className="tl-notice" role="status" data-testid="merge-notice">
      <b>Merge:</b> {from} joined {into}. {count === 1 ? 'Its Segment is' : `Its ${count} Segments are`} now in the Column of {into}, and the Column of {from} closed.
      {first && <button onClick={() => onShow(first.start)}>Show {formatTime(first.start)}</button>}
      <button onClick={onDismiss} aria-label="Dismiss">
        Dismiss
      </button>
    </div>
  )
}

/** Dismissed Merge notices, kept per Session in localStorage so that a reload does not show them again. */
function useDismissedMerges(startedAt: number | null): [Set<string>, (key: string) => void] {
  const storageKey = `rabblefish.dismissedMerges.${startedAt ?? 'none'}`
  const [version, setVersion] = useState(0)
  const set = useMemo(() => {
    void version // read again after each dismiss
    try {
      return new Set<string>(JSON.parse(localStorage.getItem(storageKey) ?? '[]'))
    } catch {
      return new Set<string>()
    }
  }, [storageKey, version])
  const dismiss = (key: string) => {
    localStorage.setItem(storageKey, JSON.stringify([...set, key]))
    setVersion((n) => n + 1)
  }
  return [set, dismiss]
}
