import { type CSSProperties, useState } from 'react'
import type { Api } from '../api'
import { formatTime, nameOf, type SourceGroup } from './model'
import { Popover } from './Popover'
import type { Speaker } from './state'

export function speakerHue(sp: Speaker): number {
  return Math.round((sp.order * 137.5 + 205) % 360)
}

/** A short name for a narrow Collapsed column: "Speaker 3" becomes "Spk 3". */
export function shortName(sp: Speaker): string {
  return nameOf(sp).replace(/^Speaker (?=\d)/, 'Spk ')
}

export const hueStyle = (sp: Speaker) => ({ '--h': speakerHue(sp) }) as CSSProperties

interface Common {
  sp: Speaker
  api: Api
  groups: SourceGroup[]
  onError: (e: unknown) => void
}

/** Edits the Display name. An empty name removes it, and the generated label shows again. */
function NameEditor({ sp, api, onError, onDone, autoFocus }: Pick<Common, 'sp' | 'api' | 'onError'> & { onDone: () => void; autoFocus?: boolean }) {
  const [value, setValue] = useState(sp.displayName ?? '')
  const save = () => {
    const next = value.trim() || null
    if (next !== sp.displayName) api.renameSpeaker(sp.id, next).catch(onError)
    onDone()
  }
  return (
    <input
      className="tl-name-input"
      aria-label={`Display name of ${sp.label}`}
      placeholder={sp.label}
      value={value}
      autoFocus={autoFocus}
      onChange={(e) => setValue(e.target.value)}
      onBlur={save}
      onKeyDown={(e) => {
        if (e.key === 'Enter') save()
        if (e.key === 'Escape') onDone()
      }}
    />
  )
}

/** Merges this Speaker into another Speaker (POST /api/speakers/merge). There is no undo. */
function MergeForm({ sp, api, groups, onError, onDone }: Common & { onDone: () => void }) {
  const [into, setInto] = useState('')
  const options = groups.map((g) => ({ g, speakers: g.speakers.filter((o) => o.id !== sp.id) })).filter((x) => x.speakers.length > 0)
  const target = options.flatMap((o) => o.speakers).find((o) => o.id === into)
  return (
    <form
      className="tl-merge-form"
      onSubmit={(e) => {
        e.preventDefault()
        if (!target) return
        api.mergeSpeakers(sp.id, target.id).catch(onError)
        onDone()
      }}
    >
      <label>
        Merge <b>{nameOf(sp)}</b> into
        <select value={into} onChange={(e) => setInto(e.target.value)} aria-label="Merge into Speaker">
          <option value="">Select a Speaker…</option>
          {options.map(({ g, speakers }) => (
            <optgroup key={g.key} label={g.description}>
              {speakers.map((o) => (
                <option key={o.id} value={o.id}>
                  {nameOf(o)}
                  {o.displayName ? ` (${o.label})` : ''}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>
      {target && (
        <p className="tl-merge-warn">
          The Segments of {nameOf(sp)} go to the Column of {nameOf(target)}, and the Column of {nameOf(sp)} closes. You cannot undo a Merge.
        </p>
      )}
      <div className="tl-row">
        <button type="submit" disabled={!target} className="tl-danger">
          Merge
        </button>
        <button type="button" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  )
}

export interface HeaderColumn {
  sp: Speaker
  wide: boolean
  pinned: boolean
  active: boolean
  /** Set for a Speaker that a Merge removed a moment ago (the Column fades out). */
  mergedInto?: Speaker
}

export function ColumnHeader({
  col,
  width,
  lastSpokeAt,
  onTogglePin,
  ...common
}: Common & { col: HeaderColumn; width: number; lastSpokeAt: number | undefined; onTogglePin: () => void }) {
  const { sp } = col
  const [editing, setEditing] = useState(false)
  const [menu, setMenu] = useState<{ anchor: HTMLElement; mode: 'menu' | 'merge' } | null>(null)
  const closeMenu = () => setMenu(null)
  const last = lastSpokeAt !== undefined ? formatTime(lastSpokeAt) : '—'
  const style = { ...hueStyle(sp), width }

  if (col.mergedInto)
    return (
      <div className="tl-hcell tl-collapsed tl-merged" style={style} data-testid="column-header" title={`${nameOf(sp)} merged into ${nameOf(col.mergedInto)}`}>
        <span className="tl-vname">
          <s>{shortName(sp)}</s>
        </span>
      </div>
    )

  const popover = menu && (
    <Popover anchor={menu.anchor} onClose={closeMenu} label={`Column ${nameOf(sp)}`}>
      {menu.mode === 'menu' ? (
        <div className="tl-menu">
          <div className="tl-menu-title">
            {nameOf(sp)} <small>({sp.label})</small>
          </div>
          <label>
            Display name
            <NameEditor sp={sp} api={common.api} onError={common.onError} onDone={() => {}} autoFocus />
          </label>
          <small>Last spoke {last}</small>
          <div className="tl-row">
            <button onClick={() => (onTogglePin(), closeMenu())}>Expand and pin</button>
            <button onClick={() => setMenu({ anchor: menu.anchor, mode: 'merge' })}>Merge…</button>
          </div>
        </div>
      ) : (
        <MergeForm {...common} onDone={closeMenu} />
      )}
    </Popover>
  )

  if (!col.wide)
    return (
      <div
        className="tl-hcell tl-collapsed"
        style={style}
        data-testid="column-header"
        data-speaker={sp.id}
        onClick={onTogglePin}
        title={`${nameOf(sp)} (${sp.label}). Last spoke ${last}. Click to expand and pin.`}
      >
        <span className="tl-vname">{shortName(sp)}</span>
        <button
          className="tl-more"
          aria-label={`Rename or merge ${nameOf(sp)}`}
          title="Rename or merge"
          onClick={(e) => {
            e.stopPropagation()
            setMenu({ anchor: e.currentTarget, mode: 'menu' })
          }}
        >
          ⋯
        </button>
        {popover}
      </div>
    )

  return (
    <div className={`tl-hcell tl-wide ${col.active ? 'tl-active' : ''}`} style={style} data-testid="column-header" data-speaker={sp.id}>
      {editing ? (
        <NameEditor sp={sp} api={common.api} onError={common.onError} onDone={() => setEditing(false)} autoFocus />
      ) : (
        <button className="tl-name" onClick={() => setEditing(true)} title="Click to set the Display name">
          {nameOf(sp)}
        </button>
      )}
      <small className="tl-sub">
        {sp.displayName ? <span className="tl-label">{sp.label}</span> : null}
        {col.pinned ? 'pinned' : col.active ? 'active' : 'idle'} · last {last}
      </small>
      <div className="tl-hbuttons">
        <button onClick={onTogglePin} title={col.pinned ? 'Unpin: collapse the Column when the Speaker is idle' : 'Collapse the Column'}>
          {col.pinned ? 'Unpin' : 'Collapse'}
        </button>
        <button onClick={(e) => setMenu({ anchor: e.currentTarget, mode: 'merge' })} title="Merge this Speaker into another Speaker">
          Merge…
        </button>
      </div>
      {popover}
    </div>
  )
}
