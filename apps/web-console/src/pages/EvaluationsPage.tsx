import { useEffect, useState } from 'react'
import { BarChart3, CheckCircle2, CircleAlert, FileText, RefreshCw } from 'lucide-react'
import { apiFetch, ApiError } from '../lib/api'
import styles from './EvaluationsPage.module.css'

interface HealthData {
  profile?: string
  actions_enabled?: boolean
}

export function EvaluationsPage() {
  const [health, setHealth] = useState<HealthData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    try {
      const response = await apiFetch('/health')
      setHealth(await response.json())
      setError(null)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : '演练记录暂时不可用')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <div className={styles.eyebrow}><BarChart3 size={14} aria-hidden="true" /> 演练记录</div>
          <h1>演练记录</h1>
          <p>记录本地演练中的故障、证据和处置结果，不展示生产系统指标。</p>
        </div>
        <button className={styles.refresh} type="button" onClick={load} disabled={loading} title="刷新演练记录状态">
          <RefreshCw size={15} aria-hidden="true" /> 刷新
        </button>
      </header>
      {error ? (
        <div className={styles.error} role="alert"><CircleAlert size={17} aria-hidden="true" />{error}</div>
      ) : (
        <div className={styles.grid}>
            <article className={styles.item}>
              <CheckCircle2 size={18} aria-hidden="true" />
            <div><strong>故障场景</strong><span>场景定义和处置时间线可回看</span></div>
            <b>可回看</b>
          </article>
          <article className={styles.item}>
            <FileText size={18} aria-hidden="true" />
            <div><strong>调查证据</strong><span>来源、序号和摘要随时间线保存</span></div>
            <b>可查看</b>
          </article>
          <article className={styles.item}>
            <CircleAlert size={18} aria-hidden="true" />
            <div><strong>效果指标</strong><span>生产恢复速度和诊断准确度尚未采集</span></div>
            <b>未采集</b>
          </article>
        </div>
      )}
      <section className={styles.note}>
        <strong>当前模式</strong>
        <span>演练环境 · 恢复操作{health?.actions_enabled ? '需审批' : '已关闭'}</span>
      </section>
    </div>
  )
}
