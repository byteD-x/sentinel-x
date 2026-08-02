import { Activity, BarChart3, Circle, ClipboardCheck, FlaskConical, LockKeyhole, Radio, ShieldCheck, TerminalSquare } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { apiFetch, currentRole } from '../lib/api'
import styles from './AppLayout.module.css'

const navigation = [
  { to: '/', label: '事故总览', icon: Activity, end: true },
  { to: '/approvals', label: '待处理审批', icon: ClipboardCheck },
  { to: '/scenarios', label: '故障演练', icon: FlaskConical },
  { to: '/evaluations', label: '验证记录', icon: BarChart3 },
  { to: '/system', label: '环境状态', icon: TerminalSquare },
]

const ROLE_LABELS: Record<string, string> = {
  viewer: '只读观察员',
  approver: '审批人',
  scenario_operator: '演练操作员',
  planner: '方案规划员',
  system: '系统服务',
}

export function AppLayout() {
  const role = currentRole()
  const [health, setHealth] = useState<{ state: 'loading' | 'online' | 'offline'; profile?: string; actionsEnabled?: boolean }>({ state: 'loading' })

  useEffect(() => {
    let active = true
    const check = async () => {
      try {
        const response = await apiFetch('/health')
        const data = await response.json() as { profile?: string; actions_enabled?: boolean }
        if (active) setHealth({ state: 'online', profile: data.profile || 'light', actionsEnabled: data.actions_enabled })
      } catch {
        if (active) setHealth({ state: 'offline' })
      }
    }
    check()
    const timer = window.setInterval(check, 15000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])

  const healthLabel = health.state === 'online' ? '控制面已连接' : health.state === 'loading' ? '正在连接控制面' : '控制面离线'
  const healthClass = health.state === 'online' ? styles.streamOnline : health.state === 'loading' ? styles.streamChecking : styles.streamOffline

  return (
    <div className={styles.layout}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <div className={styles.brandMark} aria-hidden="true"><ShieldCheck size={20} strokeWidth={2.3} /></div>
          <div>
            <div className={styles.brandName}>Sentinel-X</div>
            <div className={styles.brandCaption}>事故响应控制台</div>
          </div>
          <span className={styles.brandBadge}>演示</span>
        </div>

        <div className={styles.navBlock}>
          <p className={styles.navLabel}>工作区</p>
          <nav className={styles.nav} aria-label="主导航">
            {navigation.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) => isActive ? styles.navLinkActive : styles.navLink}
              >
                <Icon size={17} strokeWidth={2} aria-hidden="true" />
                <span>{label}</span>
              </NavLink>
            ))}
          </nav>
        </div>

        <div className={styles.sidebarFooter}>
          <div className={styles.environmentStatus}>
            <span className={`${styles.statusDot} ${health.state === 'offline' ? styles.statusDotOffline : ''}`} aria-hidden="true" />
            <div>
              <strong>本地隔离环境</strong>
              <span>{health.profile || 'light'} · {ROLE_LABELS[role] || role}</span>
            </div>
          </div>
          <div className={styles.safetyNote}>
            <LockKeyhole size={14} aria-hidden="true" />
            <span>{health.actionsEnabled ? '恢复动作需要审批' : '恢复动作已被安全开关关闭'}</span>
          </div>
        </div>
      </aside>

      <div className={styles.contentShell}>
        <header className={styles.topbar}>
          <div className={styles.topbarContext}>
            <span className={styles.topbarKicker}>事故响应工作台</span>
            <span className={styles.topbarDivider}>·</span>
            <span>本地演练环境</span>
          </div>
          <div className={`${styles.streamStatus} ${healthClass}`} role="status" aria-live="polite">
            <Radio size={14} aria-hidden="true" />
            <span>{healthLabel}</span>
            <Circle size={7} fill="currentColor" aria-hidden="true" />
            <span className={styles.roleBadge}>{ROLE_LABELS[role] || role}</span>
          </div>
        </header>
        <main className={styles.main}><Outlet /></main>
      </div>
    </div>
  )
}
