import { Activity, Circle, FlaskConical, LockKeyhole, Radio, ShieldCheck } from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'
import styles from './AppLayout.module.css'

const navigation = [
  { to: '/', label: '事故指挥室', icon: Activity, end: true, shortcut: '01' },
  { to: '/scenarios', label: '演练场景', icon: FlaskConical, shortcut: '02' },
]

export function AppLayout() {
  return (
    <div className={styles.layout}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <div className={styles.brandMark} aria-hidden="true">
            <ShieldCheck size={22} strokeWidth={2.4} />
          </div>
          <div>
            <div className={styles.brandName}>Sentinel-X</div>
            <div className={styles.brandCaption}>incident control</div>
          </div>
          <span className={styles.brandBadge}>D1</span>
        </div>

        <div className={styles.navBlock}>
          <p className={styles.navLabel}>WORKSPACE</p>
          <nav className={styles.nav} aria-label="主导航">
            {navigation.map(({ to, label, icon: Icon, end, shortcut }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) => isActive ? styles.navLinkActive : styles.navLink}
              >
                <Icon size={17} strokeWidth={2} aria-hidden="true" />
                <span>{label}</span>
                <span className={styles.navShortcut}>{shortcut}</span>
              </NavLink>
            ))}
          </nav>
        </div>

        <div className={styles.sidebarFooter}>
          <div className={styles.environmentStatus}>
            <span className={styles.statusDot} aria-hidden="true" />
            <div>
              <strong>LOCAL LAB</strong>
              <span>Profile / light</span>
            </div>
          </div>
          <div className={styles.safetyNote}>
            <LockKeyhole size={14} aria-hidden="true" />
            <span>R1 actions require approval</span>
          </div>
        </div>
      </aside>

      <div className={styles.contentShell}>
        <header className={styles.topbar}>
          <div className={styles.topbarContext}>
            <span className={styles.topbarKicker}>SENTINEL-X / CONTROL PLANE</span>
            <span className={styles.topbarDivider}>/</span>
            <span>Local exercise environment</span>
          </div>
          <div className={styles.streamStatus}>
            <Radio size={14} aria-hidden="true" />
            <span>Live stream ready</span>
            <Circle size={7} fill="currentColor" aria-hidden="true" />
          </div>
        </header>
        <main className={styles.main}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
