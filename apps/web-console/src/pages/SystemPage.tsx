import { useEffect, useState } from 'react'
import { CircleAlert, CircleCheck, LockKeyhole, RefreshCw, ServerCog } from 'lucide-react'
import { apiFetch } from '../lib/api'
import styles from './SystemPage.module.css'

interface HealthData { status?: string; version?: string; environment?: string; profile?: string; actions_enabled?: boolean; registered_runbooks?: number }

export function SystemPage() {
  const [health, setHealth] = useState<HealthData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const load = async () => {
    setLoading(true)
    try { const response = await apiFetch('/health'); setHealth(await response.json()); setError(null) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '健康检查失败') }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div><div className={styles.eyebrow}><ServerCog size={14} aria-hidden="true" /> 环境状态 / 安全边界</div><h1>环境状态</h1><p>确认控制面是否在线，以及当前演练环境是否允许恢复动作。</p></div>
        <button className={styles.refresh} type="button" onClick={load} disabled={loading} title="刷新健康状态"><RefreshCw size={15} aria-hidden="true" /> 刷新</button>
      </header>
      {error ? <div className={styles.error} role="alert"><CircleAlert size={17} aria-hidden="true" />{error}</div> : <div className={styles.grid}>
        <StatusRow label="控制面" value={health?.status === 'ok' ? '已连接' : '未知'} ok={health?.status === 'ok'} />
        <StatusRow label="运行环境" value={health?.profile || health?.environment || 'light'} ok />
        <StatusRow label="恢复动作" value={health?.actions_enabled ? '已显式开启' : '已关闭（安全开关）'} ok={!health?.actions_enabled} />
        <StatusRow label="可用操作手册" value={String(health?.registered_runbooks ?? '控制面未提供')} ok />
      </div>}
      <div className={styles.safety}><LockKeyhole size={17} aria-hidden="true" /><span>安全边界：高风险动作禁止，真实生产写操作不在本地演练环境执行。</span></div>
    </div>
  )
}

function StatusRow({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return <div className={styles.row}><span>{ok ? <CircleCheck size={16} aria-hidden="true" /> : <CircleAlert size={16} aria-hidden="true" />}</span><strong>{label}</strong><code>{value}</code></div>
}
