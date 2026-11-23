/** The parts of WebSocket used here, so tests can stand in for it. */
export interface EventSocket {
  onopen: (() => void) | null
  onmessage: ((msg: { data: string }) => void) | null
  onclose: (() => void) | null
  close(): void
}

const FIRST_RETRY_MS = 500
const LAST_RETRY_MS = 10_000

/**
 * Keep a connection for engine events open until the returned function is called. It can drop while
 * the engine lives on (the computer slept, say); it's then opened again, waiting longer after each
 * failure. `onReconnect` runs once it's back, to pick up what was missed.
 */
export function keepConnected(open: () => EventSocket, onEvent: (event: string, data: unknown) => void, onReconnect: () => void): () => void {
  let socket: EventSocket | null = null
  let timer: ReturnType<typeof setTimeout> | undefined
  let closed = false
  let lost = false
  let wait = FIRST_RETRY_MS

  const connect = (): void => {
    const ws = open()
    socket = ws
    ws.onopen = () => {
      wait = FIRST_RETRY_MS
      if (lost) onReconnect()
      lost = false
    }
    ws.onmessage = (msg) => {
      let parsed: { event: string; data: unknown }
      try {
        parsed = JSON.parse(msg.data)
      } catch {
        return // Ignore malformed frames.
      }
      onEvent(parsed.event, parsed.data)
    }
    ws.onclose = () => {
      if (closed) return
      lost = true
      timer = setTimeout(connect, wait)
      wait = Math.min(wait * 2, LAST_RETRY_MS)
    }
  }
  connect()
  return () => {
    closed = true
    clearTimeout(timer)
    socket?.close()
  }
}
