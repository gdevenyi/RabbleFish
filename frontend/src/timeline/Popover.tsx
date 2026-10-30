import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

/**
 * A small panel in fixed position next to an anchor element, so that a narrow
 * Collapsed column does not clip it. Escape or a click outside closes it.
 */
export function Popover({ anchor, onClose, children, label }: { anchor: HTMLElement; onClose: () => void; children: ReactNode; label: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ left: 0, top: 0 })

  useLayoutEffect(() => {
    const a = anchor.getBoundingClientRect()
    const w = ref.current?.offsetWidth ?? 260
    const h = ref.current?.offsetHeight ?? 160
    setPos({
      left: Math.max(8, Math.min(a.left, window.innerWidth - w - 8)),
      top: Math.max(8, Math.min(a.bottom + 4, window.innerHeight - h - 8)),
    })
  }, [anchor])

  useEffect(() => {
    const down = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node) && !anchor.contains(e.target as Node)) onClose()
    }
    const key = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('pointerdown', down)
    document.addEventListener('keydown', key)
    return () => {
      document.removeEventListener('pointerdown', down)
      document.removeEventListener('keydown', key)
    }
  }, [anchor, onClose])

  // A portal, so that no parent clips it. React events still bubble to the parent
  // component, so stop them here (a Collapsed column expands on click).
  return createPortal(
    <div ref={ref} className="tl-popover" role="dialog" aria-label={label} style={pos} onClick={(e) => e.stopPropagation()}>
      {children}
    </div>,
    document.body,
  )
}
