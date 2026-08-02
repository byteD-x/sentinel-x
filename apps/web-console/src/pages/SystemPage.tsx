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
        <div><div className={styles.eyebrow}><ServerCog size={14} aria-hidden="true" /> SYSTEM / SAFETY GATE</div><h1>系统状态</h1><p>显示控制面和动作网关的配置状态；light profile 默认关闭写动作。</p></div>
        <button className={styles.refresh} type="button" onClick={load} disabled={loading} title="刷新健康状态"><RefreshCw size={15} aria-hidden="true" /> 刷新</button>
      </header>
      {error ? <div className={styles.error} role="alert"><CircleAlert size={17} aria-hidden="true" />{error}</div> : <div className={styles.grid}>
        <StatusRow label="Control API" value={health?.status === 'ok' ? 'connected' : 'unknown'} ok={health?.status === 'ok'} />
        <StatusRow label="Profile" value={health?.profile || health?.environment || 'light'} ok />
        <StatusRow label="Action Gateway" value={health?.actions_enabled ? 'explicitly enabled' : 'kill switch / disabled'} ok={!health?.actions_enabled} />
        <StatusRow label="Registered runbooks" value={String(health?.registered_runbooks ?? 'not exposed by control api')} ok />
      </div>}
      <div className={styles.safety}><LockKeyhole size={17} aria-hidden="true" /><span>安全边界：R2/R3 禁止，真实 Kubernetes 写操作不在 light fixture 中执行。</span></div>
    </div>
  )
}

function StatusRow({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return <div className={styles.row}><span>{ok ? <CircleCheck size={16} aria-hidden="true" /> : <CircleAlert size={16} aria-hidden="true" />}</span><strong>{label}</strong><code>{value}</code></div>
}

