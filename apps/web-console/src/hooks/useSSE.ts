import { useEffect, useRef } from 'react'

export interface SSEMessage {
  type: 'status' | 'timeline_event'
  status?: string
  event?: {
    id: string
    sequence: number
    event_type: string
    actor: string
    payload: Record<string, unknown>
    timestamp: string
  }
}

/**
 * SSE Hook — 订阅事故实时更新流。
 *
 * 用法：
 *   useSSE(incidentId, (msg) => {
 *     if (msg.type === 'timeline_event') { ... }
 *     if (msg.type === 'status') { ... }
 *   })
 */
export function useSSE(
  incidentId: string | undefined,
  onMessage: (msg: SSEMessage) => void,
  enabled: boolean = true,
) {
  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage

  useEffect(() => {
    if (!incidentId || !enabled) return

    const controller = new AbortController()
    const url = `/api/incidents/${incidentId}/stream`

    const connect = async () => {
      try {
        const response = await fetch(url, { signal: controller.signal })

        if (!response.ok || !response.body) return

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          if (controller.signal.aborted) break
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const data: SSEMessage = JSON.parse(line.slice(6))
                onMessageRef.current(data)
              } catch {
                // 跳过无法解析的消息
              }
            }
          }
        }
      } catch {
        // 连接断开时静默失败（浏览器 AbortError 等）
      }
    }

    connect()

    return () => {
      controller.abort()
    }
  }, [incidentId, enabled])
}
