import { useState, useEffect, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import styles from './IncidentDetailPage.module.css'

interface TimelineEvent {
  id: string
  sequence: number
  event_type: string
  actor: string
  payload: Record<string, unknown>
  timestamp: string
}

interface IncidentDetail {
  id: string
  status: string
  severity: string
  alert_name: string
  description: string
  created_at: string
  updated_at: string
  resolved_at: string | null
  version: number
}

const EVENT_LABELS: Record<string, string> = {
  'incident.created': '事故创建',
  'incident.status_changed': '状态变更',
  'evidence.collected': '证据收集',
  'hypothesis.generated': '假设生成',
  'plan.proposed': '方案提出',
  'approval.requested': '审批请求',
  'approval.decided': '审批决定',
  'action.started': '动作执行',
  'action.completed': '动作完成',
  'recovery.verified': '恢复验证',
  'incident.escalated': '升级人工',
  'error.occurred': '发生错误',
}

export function IncidentDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [incident, setIncident] = useState<IncidentDetail | null>(null)
  const [timeline, setTimeline] = useState<TimelineEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    if (!id) return
    try {
      const [incRes, tlRes] = await Promise.all([
        fetch(`/api/incidents/${id}`),
        fetch(`/api/incidents/${id}/timeline`),
      ])
      if (!incRes.ok) throw new Error(`HTTP ${incRes.status}`)
      const incData = await incRes.json()
      setIncident(incData)

      if (tlRes.ok) {
        const tlData = await tlRes.json()
        setTimeline(tlData.events || [])
      }
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { fetchData() }, [fetchData])

  if (loading) return <div className={styles.loading}>加载中...</div>
  if (error) return <div className={styles.error}>⚠️ {error}</div>
  if (!incident) return <div className={styles.error}>事故不存在</div>

  return (
    <div>
      <Link to="/" className={styles.back}>← 返回面板</Link>

      <div className={styles.header}>
        <h1 className={styles.title}>{incident.alert_name}</h1>
        <div className={styles.meta}>
          <span className={styles.statusBadge}>{incident.status}</span>
          <span className={styles.severity}>{incident.severity}</span>
          <span>ID: {incident.id.slice(0, 8)}...</span>
          <span>版本: {incident.version}</span>
        </div>
      </div>

      <div className={styles.card}>
        <h2 className={styles.cardTitle}>描述</h2>
        <p>{incident.description}</p>
      </div>

      <div className={styles.card}>
        <h2 className={styles.cardTitle}>时间线</h2>
        {timeline.length === 0 ? (
          <p className={styles.empty}>暂无事件</p>
        ) : (
          <div className={styles.timeline}>
            {timeline.map(event => (
              <div key={event.id} className={styles.timelineItem}>
                <div className={styles.timelineDot} />
                <div className={styles.timelineContent}>
                  <div className={styles.timelineHeader}>
                    <span className={styles.timelineType}>
                      {EVENT_LABELS[event.event_type] || event.event_type}
                    </span>
                    <span className={styles.timelineActor}>{event.actor}</span>
                    <span className={styles.timelineTime}>
                      {new Date(event.timestamp).toLocaleTimeString('zh-CN')}
                    </span>
                  </div>
                  {Object.keys(event.payload).length > 0 && (
                    <pre className={styles.timelinePayload}>
                      {JSON.stringify(event.payload, null, 2)}
                    </pre>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
