import { useEffect, useRef } from 'react'
import { WS_BASE_URL } from './client'

export function useChatSocket(token, onMessage) {
  const socketRef = useRef(null)
  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage

  useEffect(() => {
    if (!token) return undefined
    let cancelled = false
    let connectTimer
    let reconnectTimer

    const connect = () => {
      if (cancelled) return
      const ws = new WebSocket(`${WS_BASE_URL}?token=${token}`)
      socketRef.current = ws
      ws.onmessage = (event) => {
        try { onMessageRef.current?.(JSON.parse(event.data)) } catch { /* ignore malformed frame */ }
      }
      ws.onclose = () => {
        if (socketRef.current === ws) socketRef.current = null
        if (!cancelled) reconnectTimer = setTimeout(connect, 2000)
      }
    }
    // React Strict Mode mounts, cleans up, then mounts effects again in development. Deferring
    // by one task lets that trial cleanup cancel the connection before a socket is constructed.
    connectTimer = setTimeout(connect, 0)

    return () => {
      cancelled = true
      clearTimeout(connectTimer)
      clearTimeout(reconnectTimer)
      const ws = socketRef.current
      socketRef.current = null
      if (!ws) return
      if (ws.readyState === WebSocket.CONNECTING) {
        ws.addEventListener('open', () => ws.close(), { once: true })
      } else if (ws.readyState === WebSocket.OPEN) {
        ws.close()
      }
    }
  }, [token])

  const sendJson = (obj) => {
    const ws = socketRef.current
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj))
  }

  return { sendJson }
}
