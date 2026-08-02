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
          <div className={styles.eyebrow}><BarChart3 size={14} aria-hidden="true" /> 验证记录</div>
          <h1>验证记录</h1>
          <p>这里展示本地演练中可以复查的证据，不把固定演示结果包装成生产指标。</p>
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
            <div><strong>固定场景</strong><span>场景目录和处理时间线可以复查</span></div>
            <b>可复查</b>
          </article>
          <article className={styles.item}>
            <FileText size={18} aria-hidden="true" />
            <div><strong>调查证据</strong><span>来源、序号和摘要随事故时间线保存</span></div>
            <b>可用</b>
          </article>
          <article className={styles.item}>
            <CircleAlert size={18} aria-hidden="true" />
            <div><strong>生产指标</strong><span>根因准确率、恢复时间和模型成本尚未测量</span></div>
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
