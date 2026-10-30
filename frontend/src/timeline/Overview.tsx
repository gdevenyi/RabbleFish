import { useRef } from 'react'
import { hueStyle } from './ColumnHeader'
import { formatTime, nameOf } from './model'
import type { Segment, Speaker } from './state'

const TICK_STEPS = [30, 60, 120, 300, 600, 900, 1800, 3600]

/**
 * The Overview: the whole Session on a linear time axis, one lane per Speaker, and a
 * rectangle for the part of the Timeline in view. Click or drag to move the Timeline.
 */
export function Overview({
  speakers,
  bySpeaker,
  wide,
  end,
  view,
  following,
  headHeight,
  onSeek,
}: {
  speakers: Speaker[]
  bySpeaker: Map<string, Segment[]>
  wide: Set<string>
  end: number
  /** Session times at the top and the bottom of the visible Timeline. */
  view: { from: number; to: number }
  following: boolean
  headHeight: number
  onSeek: (t: number) => void
}) {
  const mapRef = useRef<HTMLDivElement>(null)
  const total = Math.max(end, 1)
  const step = TICK_STEPS.find((s) => total / s <= 8) ?? 7200
  const ticks: number[] = []
  for (let t = 0; t <= total; t += step) ticks.push(t)
  const pct = (t: number) => `${(Math.min(total, Math.max(0, t)) / total) * 100}%`

  const pointer = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.type === 'pointermove' && !(e.buttons & 1)) return
    if (e.type === 'pointerdown') e.currentTarget.setPointerCapture(e.pointerId)
    const box = mapRef.current!.getBoundingClientRect()
    onSeek((Math.min(1, Math.max(0, (e.clientY - box.top) / box.height)) * total))
  }

  return (
    <aside className="tl-ov" aria-label="Overview" data-testid="overview">
      <div className="tl-ov-head" style={{ height: headHeight }}>
        <b>Overview</b>
        <small>
          00:00 – {formatTime(end)}
        </small>
        <div className="tl-ov-names">
          {speakers.map((sp) => (
            <span key={sp.id} style={hueStyle(sp)} title={nameOf(sp)}>
              {nameOf(sp).replace(/^Speaker /, 'S').slice(0, 3)}
            </span>
          ))}
        </div>
      </div>
      <div className="tl-ov-map" ref={mapRef} onPointerDown={pointer} onPointerMove={pointer} title="Click or drag to move the Timeline">
        {ticks.map((t) => (
          <div key={t} className="tl-ov-tick" style={{ top: pct(t) }}>
            {formatTime(t)}
          </div>
        ))}
        <div className="tl-ov-lanes">
          {speakers.map((sp) => (
            <div key={sp.id} className={`tl-ov-lane ${wide.has(sp.id) ? 'tl-ov-wide' : ''}`} style={hueStyle(sp)}>
              {(bySpeaker.get(sp.id) ?? []).map((s) => (
                <div key={s.id} style={{ top: pct(s.start), height: `max(1px, ${((s.end - s.start) / total) * 100}%)` }} />
              ))}
            </div>
          ))}
        </div>
        <div
          className={`tl-ov-port ${following ? 'tl-ov-port-live' : ''}`}
          data-testid="overview-viewport"
          style={{ top: pct(view.from), height: `max(6px, calc(${pct(view.to)} - ${pct(view.from)}))` }}
        />
      </div>
    </aside>
  )
}
