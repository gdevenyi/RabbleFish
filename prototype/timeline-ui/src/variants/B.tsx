// PROTOTYPE: throwaway. Variant B, "Compressed turns".
// The vertical axis is ORDER, not scale. Each row holds the segments that start at
// one moment; segments with overlapping time ranges share one row. Silences longer
// than FOLD_SEC fold into one thin gap row.
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import type { Actions, Lang, Segment, SessionView } from '../types'
import { RenameableName } from '../chrome'
import { fmt, hasCodeSwitch, moveOf, nameOf, SOURCES, SPEAKERS } from '../session'
import './B.css'

export const name = 'Compressed turns'

const FOLD_SEC = 20
const GUTTER = 64
const COL_MIN = 160

interface Row {
  start: number
  end: number
  segs: Segment[]
}

// Group segments (sorted by start) into rows. A segment that starts before the
// current row ends overlaps it and joins the row.
function buildRows(segs: Segment[]): Row[] {
  const rows: Row[] = []
  for (const s of segs) {
    const last = rows[rows.length - 1]
    if (last && s.start < last.end) {
      last.segs.push(s)
      last.end = Math.max(last.end, s.end)
    } else rows.push({ start: s.start, end: s.end, segs: [s] })
  }
  return rows
}

function dur(sec: number): string {
  const s = Math.round(sec)
  const m = Math.floor(s / 60)
  return m ? `${m} min ${s % 60} s` : `${s} s`
}

function labelOf(id: string): string {
  return SPEAKERS.find((s) => s.id === id)?.label ?? id
}

interface Merge {
  from: string
  to: string
  at: number
  count: number
}

export function Variant({ view, actions }: { view: SessionView; actions: Actions }) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const programmatic = useRef(false)
  const [merges, setMerges] = useState<Merge[]>([])

  const colOf = new Map(view.speakers.map((s, i) => [s.id, i + 2]))
  const ncols = view.speakers.length
  const gridStyle = { gridTemplateColumns: `${GUTTER}px repeat(${ncols}, minmax(${COL_MIN}px, 1fr))` }

  // Source groups for the header (speakers are already ordered by source).
  const groups: { sourceId: string; count: number }[] = []
  for (const sp of view.speakers) {
    const g = groups[groups.length - 1]
    if (g && g.sourceId === sp.sourceId) g.count++
    else groups.push({ sourceId: sp.sourceId, count: 1 })
  }

  // Language switch per segment, in one pass (same rule as isLanguageSwitch).
  const switched = new Set<string>()
  const lastLang = new Map<string, Lang>()
  for (const s of view.segments) {
    const prev = lastLang.get(s.speakerId)
    if (prev && prev !== s.lang) switched.add(s.id)
    lastLang.set(s.speakerId, s.lang)
  }

  // Whole-speaker merges: moves whose old column is gone. Keep them after the 6 s window.
  const visible = new Set(view.speakers.map((s) => s.id))
  useEffect(() => {
    const found = new Map<string, Merge>()
    for (const m of view.recentMoves) {
      if (visible.has(m.fromSpeakerId)) continue
      const k = `${m.fromSpeakerId}>${m.toSpeakerId}@${m.at}`
      const cur = found.get(k)
      if (cur) cur.count++
      else found.set(k, { from: m.fromSpeakerId, to: m.toSpeakerId, at: m.at, count: 1 })
    }
    if (!found.size) return
    setMerges((old) => {
      const keys = new Set(old.map((m) => `${m.from}>${m.to}@${m.at}`))
      const add = [...found.entries()].filter(([k]) => !keys.has(k)).map(([, v]) => v)
      return add.length ? [...old, ...add] : old
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view.recentMoves])

  // Columns that just received segments (header flash).
  const received = new Map<string, number>()
  for (const m of view.recentMoves) received.set(m.toSpeakerId, (received.get(m.toSpeakerId) ?? 0) + 1)

  // Auto-follow: keep the live edge in view.
  useLayoutEffect(() => {
    const el = scrollRef.current
    if (!el || !view.follow) return
    const target = el.scrollHeight - el.clientHeight
    if (Math.abs(el.scrollTop - target) > 1) {
      programmatic.current = true
      el.scrollTop = target
    }
  })

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    if (programmatic.current) {
      programmatic.current = false
      return
    }
    const fromBottom = el.scrollHeight - el.clientHeight - el.scrollTop
    if (view.follow && fromBottom > 40) actions.setFollow(false)
    else if (!view.follow && fromBottom < 4) actions.setFollow(true)
  }

  const jumpToLive = () => {
    const el = scrollRef.current
    if (el) {
      programmatic.current = true
      el.scrollTop = el.scrollHeight
    }
    actions.setFollow(true)
  }

  const rows = buildRows(view.segments)
  const body: ReactNode[] = []
  let prevEnd = 0
  for (const row of rows) {
    const gap = row.start - prevEnd
    if (gap > FOLD_SEC)
      body.push(
        <div key={`gap-${row.segs[0].id}`} className="vB-row vB-gaprow" style={gridStyle}>
          <div className="vB-gutter vB-gutter-gap">{fmt(prevEnd)}</div>
          <div className="vB-gap" style={{ gridColumn: `2 / span ${ncols}` }}>
            — {dur(gap)} silence —
          </div>
        </div>,
      )
    const overlap = row.segs.length > 1
    const cells = new Map<string, ReactNode[]>()
    const put = (sp: string, n: ReactNode) => {
      if (!cells.has(sp)) cells.set(sp, [])
      cells.get(sp)!.push(n)
    }
    for (const s of row.segs) {
      put(s.speakerId, <SegmentCard key={s.id} view={view} seg={s} overlap={overlap} switched={switched.has(s.id)} />)
      const mv = moveOf(view, s.id)
      if (mv && visible.has(mv.fromSpeakerId))
        put(
          mv.fromSpeakerId,
          <div key={`ghost-${s.id}`} className="vB-ghost">
            moved to <b>{nameOf(view, mv.toSpeakerId)}</b> →
          </div>,
        )
    }
    body.push(
      <div key={row.segs[0].id} className={`vB-row${overlap ? ' vB-overlaprow' : ''}${gap > 6 && gap <= FOLD_SEC ? ' vB-pause' : ''}`} style={gridStyle}>
        <div className="vB-gutter">
          {fmt(row.start)}
          {overlap && <span className="vB-bracket">overlap</span>}
        </div>
        {[...cells.entries()].map(([sp, nodes]) =>
          colOf.has(sp) ? (
            <div key={sp} className="vB-cell" style={{ gridColumn: colOf.get(sp) }}>
              {nodes}
            </div>
          ) : null,
        )}
      </div>,
    )
    prevEnd = Math.max(prevEnd, row.end)
  }
  const silenceNow = view.clock - prevEnd
  if (silenceNow > FOLD_SEC)
    body.push(
      <div key="gap-live" className="vB-row vB-gaprow" style={gridStyle}>
        <div className="vB-gutter vB-gutter-gap">{fmt(prevEnd)}</div>
        <div className="vB-gap" style={{ gridColumn: `2 / span ${ncols}` }}>
          — {dur(silenceNow)} silence so far —
        </div>
      </div>,
    )

  return (
    <div className="vB-root">
      <div className="vB-proposal">
        <b>Proposal:</b> time is compressed: silence is folded. Rows follow the order of speech, not a time scale. Speech that overlaps shares one row.
      </div>
      {merges.length > 0 && (
        <div className="vB-merges">
          {merges.map((m) => (
            <div key={`${m.from}-${m.at}`} className="vB-merge">
              <span>
                {fmt(m.at)} correction: <b>{nameOf(view, m.from)}</b>
                {view.displayNames[m.from] ? ` (${labelOf(m.from)})` : ''} was the same voice as <b>{nameOf(view, m.to)}</b>. Its {m.count} segments moved there and its column was removed.
              </span>
              <button onClick={() => setMerges((ms) => ms.filter((x) => x !== m))}>×</button>
            </div>
          ))}
        </div>
      )}
      <div className="vB-scroll" ref={scrollRef} onScroll={onScroll}>
        <div className="vB-table" style={{ minWidth: GUTTER + ncols * COL_MIN }}>
          <div className="vB-head">
            <div className="vB-row vB-sources" style={gridStyle}>
              <div className="vB-gutter vB-corner" />
              {groups.map((g) => (
                <div key={g.sourceId} className={`vB-source vB-src-${g.sourceId}`} style={{ gridColumn: `span ${g.count}` }}>
                  {SOURCES.find((s) => s.id === g.sourceId)?.name ?? g.sourceId}
                </div>
              ))}
            </div>
            <div className="vB-row vB-names" style={gridStyle}>
              <div className="vB-gutter vB-corner">time</div>
              {view.speakers.map((sp) => (
                <div key={sp.id} className={`vB-name vB-src-${sp.sourceId}${received.has(sp.id) ? ' vB-name-flash' : ''}`}>
                  <RenameableName view={view} actions={actions} speakerId={sp.id} className="vB-rename" />
                  <div className="vB-label">
                    {sp.label}
                    {received.has(sp.id) && <span className="vB-recv"> +{received.get(sp.id)} moved here</span>}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="vB-body">
            {body}
            <div className="vB-live" style={gridStyle}>
              <div className="vB-gutter vB-gutter-live">{fmt(view.clock)}</div>
              <div className="vB-liveline" style={{ gridColumn: `2 / span ${ncols}` }}>
                <span>● live — new segments appear about 3 s after they end</span>
              </div>
            </div>
          </div>
        </div>
      </div>
      {!view.follow && (
        <button className="vB-jump" onClick={jumpToLive}>
          ↓ Jump to live ({fmt(view.clock)})
        </button>
      )}
    </div>
  )
}

function SegmentCard({ view, seg, overlap, switched }: { view: SessionView; seg: Segment; overlap: boolean; switched: boolean }) {
  const mv = moveOf(view, seg.id)
  const code = hasCodeSwitch(seg)
  const wasOther = seg.originalSpeakerId !== seg.speakerId
  const cls = ['vB-seg', `vB-lang-${seg.lang}`, switched && 'vB-switch', mv && 'vB-moved', overlap && 'vB-overlap'].filter(Boolean).join(' ')
  return (
    <div className={cls}>
      <div className="vB-meta">
        {overlap && (
          <span className="vB-range">
            {fmt(seg.start)}–{fmt(seg.end)}
          </span>
        )}
        {switched && <span className="vB-switchtag">language switch → {seg.lang.toUpperCase()}</span>}
        {mv ? (
          <span className="vB-movetag">moved here from {nameOf(view, mv.fromSpeakerId)}</span>
        ) : (
          wasOther && <span className="vB-wastag">was {labelOf(seg.originalSpeakerId)}</span>
        )}
        <span className="vB-lang">{seg.lang}</span>
      </div>
      <div className="vB-text">
        {code
          ? seg.runs.map((r, i) => (
              <span key={i} className={`vB-run vB-run-${r.lang}`}>
                <sup>{r.lang}</sup>
                {r.text}{' '}
              </span>
            ))
          : seg.runs.map((r) => r.text).join(' ')}
      </div>
      {view.showTranslation && seg.translation && <div className="vB-tr">{seg.translation}</div>}
    </div>
  )
}
