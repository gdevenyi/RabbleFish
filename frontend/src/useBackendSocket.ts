import { useEffect, useState } from 'react'

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected'

type ServerMessage =
  | { type: 'hello'; version: string }
  | { type: 'heartbeat'; seq: number; server_time: number }

const RECONNECT_DELAY_MS = 1000

// Connects to the backend WebSocket on the same origin and reconnects after a drop.
export function useBackendSocket() {
  const [status, setStatus] = useState<ConnectionStatus>('connecting')
  const [version, setVersion] = useState<string>()
  const [lastHeartbeat, setLastHeartbeat] = useState<{ seq: number; serverTime: number }>()

  useEffect(() => {
    let ws: WebSocket | undefined
    let retry: ReturnType<typeof setTimeout> | undefined
    let closed = false

    const connect = () => {
      const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${scheme}://${location.host}/ws`)
      setStatus('connecting')
      ws.onopen = () => setStatus('connected')
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data) as ServerMessage
        if (msg.type === 'hello') setVersion(msg.version)
        if (msg.type === 'heartbeat') setLastHeartbeat({ seq: msg.seq, serverTime: msg.server_time })
      }
      ws.onclose = () => {
        setStatus('disconnected')
        if (!closed) retry = setTimeout(connect, RECONNECT_DELAY_MS)
      }
    }
    connect()
    return () => {
      closed = true
      clearTimeout(retry)
      ws?.close()
    }
  }, [])

  return { status, version, lastHeartbeat }
}
