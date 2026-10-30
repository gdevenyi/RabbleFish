import { useEffect, useState } from 'react'
import { type Api, httpApi } from './api'
import type { ServerEvent } from './contract'
import type { ReceivedEvent } from './timeline/state'

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'demo'

const RECONNECT_DELAY_MS = 1000

/** Dev-only demo mode: `?demo` replays recorded events and does not open the backend socket. */
export const DEMO = import.meta.env.DEV && new URLSearchParams(location.search).has('demo')

/**
 * Connects to the backend WebSocket on the same origin, reconnects after a drop, and
 * sends the events to `onEvents` in one batch per animation frame (a snapshot can hold
 * thousands of events). In demo mode the events come from the demo player.
 */
export function useBackendSocket(onEvents: (batch: ReceivedEvent[]) => void): { status: ConnectionStatus; api: Api } {
  const [status, setStatus] = useState<ConnectionStatus>(DEMO ? 'demo' : 'connecting')
  const [api, setApi] = useState<Api>(httpApi)

  useEffect(() => {
    let queue: ReceivedEvent[] = []
    let frame = 0
    const flush = () => {
      frame = 0
      const batch = queue
      queue = []
      onEvents(batch)
    }
    const push = (event: ServerEvent) => {
      queue.push({ event, at: Date.now() / 1000 })
      if (!frame) frame = requestAnimationFrame(flush)
    }
    let stop = () => {}
    let closed = false

    if (import.meta.env.DEV && DEMO) {
      import('./demo/player').then(({ startDemo }) => {
        if (closed) return
        const params = new URLSearchParams(location.search)
        const demo = startDemo(push, { speed: Number(params.get('speed')) || 1, history: Number(params.get('history') ?? 230) })
        setApi(demo.api)
        stop = demo.stop
      })
    } else {
      let ws: WebSocket | undefined
      let retry: ReturnType<typeof setTimeout> | undefined
      const connect = () => {
        const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
        ws = new WebSocket(`${scheme}://${location.host}/ws`)
        setStatus('connecting')
        ws.onopen = () => setStatus('connected')
        ws.onmessage = (ev) => push(JSON.parse(ev.data) as ServerEvent)
        ws.onclose = () => {
          setStatus('disconnected')
          if (!closed) retry = setTimeout(connect, RECONNECT_DELAY_MS)
        }
      }
      connect()
      stop = () => {
        clearTimeout(retry)
        ws?.close()
      }
    }
    return () => {
      closed = true
      cancelAnimationFrame(frame)
      stop()
    }
  }, [onEvents])

  return { status, api }
}
