// PROTOTYPE: throwaway. Controls, state panel and variant switcher. These are not
// part of the design under test; they only drive the fake session.
import { useEffect, useState } from 'react'
import type { Actions, SessionView } from './types'
import { fmt, nameOf, SPEAKERS } from './session'

export function Controls({ view, actions }: { view: SessionView; actions: Actions }) {
  return (
    <div className="proto-controls">
      <strong>PROTOTYPE</strong>
      <span>clock {fmt(view.clock)}</span>
      <button onClick={actions.togglePlay}>{view.playing ? 'Pause' : 'Play'}</button>
      {[1, 4, 16].map((s) => (
        <button key={s} className={view.speed === s ? 'on' : ''} onClick={() => actions.setSpeed(s)}>
          {s}x
        </button>
      ))}
      <button onClick={actions.jumpToNextEvent}>Next event ⏭</button>
      <label>
        <input type="checkbox" checked={view.showTranslation} onChange={actions.toggleTranslation} /> translation
      </label>
      <span className="proto-last">{view.lastEvent}</span>
    </div>
  )
}

export function StatePanel({ view }: { view: SessionView }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="proto-state">
      <button onClick={() => setOpen((o) => !o)}>{open ? 'Hide state' : 'Show state'}</button>
      {open && (
        <pre>
          {[
            `clock: ${fmt(view.clock)}  speed: ${view.speed}x  ${view.playing ? 'playing' : 'paused'}`,
            `follow (auto-scroll): ${view.follow}`,
            `translation: ${view.showTranslation ? 'on' : 'off'} → ${view.targetLang}`,
            `visible segments: ${view.segments.length}`,
            `columns: ${view.speakers.length}`,
            ...SPEAKERS.map((s) => `  ${s.id.padEnd(7)} ${s.label.padEnd(10)} → ${nameOf(view, s.id)}${view.speakers.some((v) => v.id === s.id) ? '' : '  (no column)'}`),
            `recent moves: ${view.recentMoves.map((m) => `${m.segmentId}:${m.fromSpeakerId}→${m.toSpeakerId}`).join(', ') || 'none'}`,
            `last event: ${view.lastEvent}`,
          ].join('\n')}
        </pre>
      )}
    </div>
  )
}

function typing(): boolean {
  const el = document.activeElement as HTMLElement | null
  return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)
}

export function Switcher({ keys, names, current }: { keys: string[]; names: Record<string, string>; current: string }) {
  const go = (delta: number) => {
    const i = (keys.indexOf(current) + delta + keys.length) % keys.length
    const url = new URL(window.location.href)
    url.searchParams.set('variant', keys[i])
    window.history.replaceState(null, '', url)
    window.dispatchEvent(new Event('variantchange'))
  }
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (typing()) return
      if (e.key === 'ArrowLeft') go(-1)
      if (e.key === 'ArrowRight') go(1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })
  if (import.meta.env.PROD) return null
  return (
    <div className="proto-switcher">
      <button onClick={() => go(-1)}>←</button>
      <span>
        {current} ({names[current]})
      </span>
      <button onClick={() => go(1)}>→</button>
    </div>
  )
}

// Click the name to rename. Enter or blur saves; Escape cancels; empty restores the label.
export function RenameableName({ view, actions, speakerId, className }: { view: SessionView; actions: Actions; speakerId: string; className?: string }) {
  const [editing, setEditing] = useState(false)
  const name = nameOf(view, speakerId)
  const label = SPEAKERS.find((s) => s.id === speakerId)?.label
  if (editing)
    return (
      <input
        className={className}
        autoFocus
        defaultValue={view.displayNames[speakerId] ?? ''}
        placeholder={label}
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
    <span className={className} title={`${label} — click to rename`} style={{ cursor: 'text' }} onClick={() => setEditing(true)}>
      {name}
      {view.displayNames[speakerId] && <small style={{ opacity: 0.6 }}> ({label})</small>} ✎
    </span>
  )
}
