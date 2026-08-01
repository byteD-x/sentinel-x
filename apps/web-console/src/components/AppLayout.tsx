import { Outlet, NavLink } from 'react-router-dom'
import styles from './AppLayout.module.css'

export function AppLayout() {
  return (
    <div className={styles.layout}>
      <header className={styles.header}>
        <div className={styles.logo}>
          <span className={styles.logoIcon}>🛡️</span>
          <span className={styles.logoText}>Sentinel-X</span>
          <span className={styles.logoBadge}>MVP</span>
        </div>
        <nav className={styles.nav}>
          <NavLink to="/" className={({ isActive }) => isActive ? styles.navLinkActive : styles.navLink}>
            事故面板
          </NavLink>
          <NavLink to="/scenarios" className={({ isActive }) => isActive ? styles.navLinkActive : styles.navLink}>
            演练场景
          </NavLink>
        </nav>
        <div className={styles.status}>
          <span className={styles.statusDot} />
          <span className={styles.statusText}>本地演练环境</span>
        </div>
      </header>
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  )
}
