import { useEffect, useRef, useState } from 'react'
import { apiFetch } from '../lib/api'

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

export type SSEConnectionStatus = 'idle' | 'connected' | 'reconnecting' | 'stale' | 'offline'

/** 事故实时流：断线重连、保存序号，并在重连前补读时间线缺口。 */
export function useSSE(
  incidentId: string | undefined,
  onMessage: (msg: SSEMessage) => void,
  enabled = true,
) {
  const onMessageRef = useRef(onMessage)
  const [connectionStatus, setConnectionStatus] = useState<SSEConnectionStatus>(enabled ? 'reconnecting' : 'idle')

  useEffect(() => {
    onMessageRef.current = onMessage
  }, [onMessage])

  useEffect(() => {
    if (!incidentId || !enabled) {
      setConnectionStatus('idle')
      return
    }

    const controller = new AbortController()
    let retryTimer: number | undefined
    let retryDelay = 500
    let lastSequence = 0
    let lastEventId = ''
    let stopped = false

    const backfill = async () => {
      try {
        const response = await apiFetch(`/api/incidents/${incidentId}/timeline?after_sequence=${lastSequence}`)
        const data = await response.json() as { events?: SSEMessage['event'][] }
        for (const event of data.events || []) {
          if (event) {
            lastSequence = Math.max(lastSequence, event.sequence)
            lastEventId = String(event.sequence)
            onMessageRef.current({ type: 'timeline_event', event })
          }
        }
      } catch {
        // 下一次连接继续尝试补读，界面显示 stale/offline。
      }
    }

    const scheduleReconnect = () => {
      if (stopped || controller.signal.aborted) return
      setConnectionStatus('reconnecting')
      retryTimer = window.setTimeout(connect, retryDelay)
      retryDelay = Math.min(retryDelay * 2, 8000)
    }

    const connect = async () => {
      if (stopped || controller.signal.aborted) return
      if (lastSequence > 0) await backfill()
      setConnectionStatus(lastSequence > 0 ? 'stale' : 'reconnecting')
      try {
        const headers = new Headers({ Accept: 'text/event-stream' })
        if (lastEventId) headers.set('Last-Event-ID', lastEventId)
        const response = await apiFetch(`/api/incidents/${incidentId}/stream`, { headers, signal: controller.signal })
        if (!response.body) throw new Error('SSE body missing')
        setConnectionStatus('connected')
        retryDelay = 500
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        while (!controller.signal.aborted) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue
            try {
              const data = JSON.parse(line.slice(6)) as SSEMessage
              if (data.event) {
                lastSequence = Math.max(lastSequence, data.event.sequence)
                lastEventId = String(data.event.sequence)
              }
              onMessageRef.current(data)
            } catch {
              // 忽略单条损坏事件，保持连接继续处理后续消息。
            }
          }
        }
        if (!controller.signal.aborted) scheduleReconnect()
      } catch {
        if (!controller.signal.aborted) {
          setConnectionStatus(lastSequence > 0 ? 'offline' : 'reconnecting')
          scheduleReconnect()
        }
      }
    }

    connect()
    return () => {
      stopped = true
      controller.abort()
      if (retryTimer) window.clearTimeout(retryTimer)
    }
  }, [incidentId, enabled])

  return connectionStatus
}
