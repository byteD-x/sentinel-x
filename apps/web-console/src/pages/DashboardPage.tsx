import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import styles from './DashboardPage.module.css'

interface Incident {
  id: string
  status: string
  severity: string
  alert_name: string
  description: string
  created_at: string
  updated_at: string
  resolved_at: string | null
}

const STATUS_LABELS: Record<string, string> = {
  DETECTED: '已发现',
  TRIAGING: '分诊中',
  DIAGNOSING: '调查中',
  PLAN_PROPOSED: '已提出方案',
  AWAITING_APPROVAL: '等待审批',
  EXECUTING: '执行中',
  VERIFYING: '验证中',
  RESOLVED: '已恢复',
  ESCALATED: '已升级',
  FAILED: '失败',
}

const STATUS_CLASS: Record<string, string> = {
  DETECTED: styles.statusDetected,
  TRIAGING: styles.statusActive,
  DIAGNOSING: styles.statusActive,
  PLAN_PROPOSED: styles.statusActive,
  AWAITING_APPROVAL: styles.statusPending,
  EXECUTING: styles.statusActive,
  VERIFYING: styles.statusActive,
  RESOLVED: styles.statusResolved,
  ESCALATED: styles.statusEscalated,
  FAILED: styles.statusFailed,
}

const SEVERITY_CLASS: Record<string, string> = {
  critical: styles.sevCritical,
  warning: styles.sevWarning,
  info: styles.sevInfo,
}

export function DashboardPage() {
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [seeded, setSeeded] = useState(false)

  const fetchIncidents = useCallback(async () => {
    try {
      const res = await fetch('/api/incidents')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setIncidents(data.items || [])
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchIncidents()
  }, [fetchIncidents])

  const handleSeed = async () => {
    try {
      const res = await fetch('/api/demo/seed', { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setSeeded(true)
      await fetchIncidents()
    } catch (e) {
      setError(e instanceof Error ? e.message : '注入演示数据失败')
    }
  }

  const activeCount = incidents.filter(i => !['RESOLVED', 'ESCALATED', 'FAILED'].includes(i.status)).length
  const resolvedCount = incidents.filter(i => i.status === 'RESOLVED').length

  return (
    <div>
      <div className={styles.pageHeader}>
        <div>
          <h1 className={styles.title}>事故面板</h1>
          <p className={styles.subtitle}>
            {activeCount > 0 ? `${activeCount} 个活跃事故` : '无活跃事故'}
            {resolvedCount > 0 && ` · ${resolvedCount} 个已恢复`}
          </p>
        </div>
        <div className={styles.actions}>
          {!seeded && (
            <button className={styles.btnSecondary} onClick={handleSeed}>
              注入演示数据
            </button>
          )}
          <button className={styles.btnPrimary} onClick={fetchIncidents}>
            刷新
          </button>
        </div>
      </div>

      {error && (
        <div className={styles.errorBanner}>
          ⚠️ {error} — 请确保 Control API 已启动（python -m sentinel_x_control_api.app）
        </div>
      )}

      {loading ? (
        <div className={styles.empty}>加载中...</div>
      ) : incidents.length === 0 ? (
        <div className={styles.empty}>
          <p>暂无事故记录</p>
          <p className={styles.emptyHint}>
            点击「注入演示数据」创建示例事故，或启动演练场景
          </p>
        </div>
      ) : (
        <div className={styles.table}>
          <div className={styles.tableHeader}>
            <span className={styles.colStatus}>状态</span>
            <span className={styles.colSeverity}>级别</span>
            <span className={styles.colName}>告警名称</span>
            <span className={styles.colDesc}>描述</span>
            <span className={styles.colTime}>创建时间</span>
          </div>
          {incidents.map(inc => (
            <Link key={inc.id} to={`/incidents/${inc.id}`} className={styles.tableRow}>
              <span className={styles.colStatus}>
                <span className={`${styles.statusBadge} ${STATUS_CLASS[inc.status] || ''}`}>
                  {STATUS_LABELS[inc.status] || inc.status}
                </span>
              </span>
              <span className={styles.colSeverity}>
                <span className={`${styles.sevBadge} ${SEVERITY_CLASS[inc.severity] || ''}`}>
                  {inc.severity}
                </span>
              </span>
              <span className={styles.colName}>{inc.alert_name}</span>
              <span className={styles.colDesc}>{inc.description}</span>
              <span className={styles.colTime}>
                {new Date(inc.created_at).toLocaleTimeString('zh-CN')}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
