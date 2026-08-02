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
      setError(cause instanceof ApiError ? cause.message : '评测状态不可用')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <div className={styles.eyebrow}><BarChart3 size={14} aria-hidden="true" /> EVALUATION EVIDENCE</div>
          <h1>评测证据</h1>
          <p>当前 light profile 只展示可复查的演练 fixture 状态，不把固定输出包装成生产指标。</p>
        </div>
        <button className={styles.refresh} type="button" onClick={load} disabled={loading} title="刷新评测状态">
          <RefreshCw size={15} aria-hidden="true" /> 刷新
        </button>
      </header>
      {error ? (
        <div className={styles.error} role="alert"><CircleAlert size={17} aria-hidden="true" />{error}</div>
      ) : (
        <div className={styles.grid}>
          <article className={styles.item}>
            <CheckCircle2 size={18} aria-hidden="true" />
            <div><strong>场景 ground truth</strong><span>固定场景目录和时间线事件可复查</span></div>
            <b>light fixture</b>
          </article>
          <article className={styles.item}>
            <FileText size={18} aria-hidden="true" />
            <div><strong>证据账本</strong><span>来源、序号和摘要随事故时间线保存</span></div>
            <b>可用</b>
          </article>
          <article className={styles.item}>
            <CircleAlert size={18} aria-hidden="true" />
            <div><strong>生产 benchmark</strong><span>根因准确率、MTTR、模型成本尚未测量</span></div>
            <b>未声明</b>
          </article>
        </div>
      )}
      <section className={styles.note}>
        <strong>运行上下文</strong>
        <span>profile: {health?.profile || 'unknown'} · actions: {health?.actions_enabled ? 'enabled by explicit config' : 'disabled / kill switch'}</span>
      </section>
    </div>
  )
}

