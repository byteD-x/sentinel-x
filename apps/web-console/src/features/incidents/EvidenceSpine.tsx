import { ChevronDown } from 'lucide-react'
import { useState } from 'react'
import type { IncidentMilestone, IncidentPhase, MilestoneSourceKind, MilestoneState } from './contracts'
import styles from './EvidenceSpine.module.css'

export interface EvidenceSpineProps {
  milestones: IncidentMilestone[]
}

const PHASE_LABELS: Record<IncidentPhase, string> = {
  detect: '发现',
  investigate: '调查',
  plan: '方案',
  approve: '审批',
  execute: '执行',
  verify: '验证',
}

const STATE_LABELS: Record<MilestoneState, string> = {
  complete: '已完成',
  current: '当前阶段',
  upcoming: '待进行',
  failed: '阶段失败',
}

const SOURCE_LABELS: Record<MilestoneSourceKind, string> = {
  alert: '告警',
  evidence: '调查证据',
  hypothesis: '调查判断',
  plan: '恢复方案',
  approval: '审批记录',
  action: '执行记录',
  verification: '验证记录',
}

function formatTimestamp(value: string) {
  const timestamp = new Date(value)
  if (Number.isNaN(timestamp.getTime())) return value
  return timestamp.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function EvidenceSpine({ milestones }: EvidenceSpineProps) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set())

  if (milestones.length === 0) {
    return <p className={styles.empty} role="status">暂无处置证据，系统会在收到调查结果后更新。</p>
  }

  const toggleMilestone = (milestoneId: string) => {
    setExpandedIds(previous => {
      const next = new Set(previous)
      if (next.has(milestoneId)) next.delete(milestoneId)
      else next.add(milestoneId)
      return next
    })
  }

  return (
    <ol className={styles.spine} aria-label="处置证据链">
      {milestones.map(milestone => {
        const expanded = expandedIds.has(milestone.id)
        const detailsId = `milestone-details-${milestone.id}`

        return (
          <li
            key={milestone.id}
            className={styles.milestone}
            aria-current={milestone.state === 'current' ? 'step' : undefined}
            data-state={milestone.state}
          >
            <span className={styles.marker} aria-hidden="true" />
            <button
              className={styles.toggle}
              type="button"
              aria-controls={detailsId}
              aria-expanded={expanded}
              aria-label={`${expanded ? '收起' : '查看'}详情：${milestone.summary}`}
              onClick={() => toggleMilestone(milestone.id)}
            >
              <span className={styles.topline}>
                <span className={styles.phase}>{PHASE_LABELS[milestone.phase]}</span>
                <span className={styles.state}>{STATE_LABELS[milestone.state]}</span>
                <span className={styles.source}>{SOURCE_LABELS[milestone.source_kind]}</span>
                {milestone.source_mode === 'fixture' && <span className={styles.fixture}>演练数据</span>}
                <time className={styles.time} dateTime={milestone.occurred_at}>{formatTimestamp(milestone.occurred_at)}</time>
              </span>
              <span className={styles.summary}>{milestone.summary}</span>
              <ChevronDown className={styles.chevron} size={16} aria-hidden="true" />
            </button>

            {expanded && (
              <div className={styles.details} id={detailsId}>
                {milestone.evidence_refs.length > 0 && (
                  <div className={styles.detailGroup}>
                    <span className={styles.detailLabel}>关联证据</span>
                    <ul className={styles.references} aria-label="关联证据">
                      {milestone.evidence_refs.map(reference => <li key={reference}><code>{reference}</code></li>)}
                    </ul>
                  </div>
                )}
                {milestone.evidence_refs.length === 0 && <span className={styles.noReferences}>该阶段暂无独立证据编号。</span>}
              </div>
            )}
          </li>
        )
      })}
    </ol>
  )
}
