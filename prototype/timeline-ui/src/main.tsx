// PROTOTYPE: throwaway. Variants of the timeline, switchable with ?variant=.
import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { useSession } from './session'
import { Controls, StatePanel, Switcher } from './chrome'
import * as A from './variants/A'
import * as B from './variants/B'
import * as C from './variants/C'
import './proto.css'

const VARIANTS = { A, B, C }
type Key = keyof typeof VARIANTS
const KEYS = Object.keys(VARIANTS) as Key[]
const NAMES = Object.fromEntries(KEYS.map((k) => [k, VARIANTS[k].name])) as Record<string, string>

function currentKey(): Key {
  const v = new URLSearchParams(window.location.search).get('variant') as Key | null
  return v && v in VARIANTS ? v : 'A'
}

function App() {
  const { view, actions } = useSession()
  const [key, setKey] = useState<Key>(currentKey)
  useEffect(() => {
    const on = () => setKey(currentKey())
    window.addEventListener('variantchange', on)
    return () => window.removeEventListener('variantchange', on)
  }, [])
  const Variant = VARIANTS[key].Variant
  return (
    <div className="proto-app">
      <Controls view={view} actions={actions} />
      <div className="proto-stage">
        <Variant key={key} view={view} actions={actions} />
      </div>
      <StatePanel view={view} />
      <Switcher keys={KEYS} names={NAMES} current={key} />
    </div>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
