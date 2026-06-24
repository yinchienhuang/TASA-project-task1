import React from 'react'
import type { EventUpdate } from '../api/client'
import '../styles/EventUpdateNotification.css'

interface Update {
  event_id: string
  status: 'created' | 'updated'
  satellite_label: string
  type: string
  changes: EventUpdate[]
  summary: string
  is_significant: boolean
  source_file: string
}

interface Props {
  updates: Update[]
  onClose?: () => void
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) {
    return '∅'
  }
  if (typeof value === 'object') {
    return JSON.stringify(value)
  }
  return String(value)
}

function FieldChange({ change }: { change: EventUpdate }) {
  return (
    <div className={`field-change ${change.type}`}>
      <span className="field-name">{change.field}:</span>
      {change.type === 'added' && (
        <span className="change-value added">+ {formatValue(change.new)}</span>
      )}
      {change.type === 'updated' && (
        <>
          <span className="old-value">{formatValue(change.old)}</span>
          <span className="arrow">→</span>
          <span className="new-value">{formatValue(change.new)}</span>
        </>
      )}
      {change.type === 'removed' && (
        <span className="change-value removed">- {formatValue(change.old)}</span>
      )}
    </div>
  )
}

function UpdateCard({ update }: { update: Update }) {
  const [expanded, setExpanded] = React.useState(false)

  return (
    <div className="update-card">
      <div className="card-header">
        <div className="header-info">
          <span className="satellite-label">{update.satellite_label}</span>
          <span className="event-type">{update.type}</span>
          <span className={`status-badge ${update.status}`}>
            {update.status === 'updated' ? '🔄 UPDATED' : '✨ NEW'}
          </span>
        </div>
        <button
          className="expand-btn"
          onClick={() => setExpanded(!expanded)}
          aria-label={expanded ? 'Collapse' : 'Expand'}
        >
          {expanded ? '▼' : '▶'}
        </button>
      </div>

      {(expanded || update.is_significant) && (
        <div className="card-content">
          <p className="summary">{update.summary}</p>

          <div className="changes-container">
            {update.changes.slice(0, 5).map((c, i) => (
              <FieldChange key={i} change={c} />
            ))}
            {update.changes.length > 5 && (
              <p className="more-changes">+{update.changes.length - 5} more field(s)</p>
            )}
          </div>

          <p className="source-file">Source: {update.source_file}</p>
        </div>
      )}
    </div>
  )
}

export function EventUpdateNotification({ updates, onClose }: Props) {
  const significant = updates.filter(u => u.is_significant)
  const created = updates.filter(u => u.status === 'created')
  const updated = updates.filter(u => u.status === 'updated')

  if (updates.length === 0) {
    return null
  }

  return (
    <div className="event-update-notification">
      <div className="notification-header">
        <div className="title-section">
          <h3>Processing Complete</h3>
          <span className="summary-stat">
            {created.length > 0 && <span className="stat-item">Created: {created.length}</span>}
            {updated.length > 0 && <span className="stat-item">Updated: {updated.length}</span>}
          </span>
        </div>
        {onClose && (
          <button className="close-btn" onClick={onClose} aria-label="Close">
            ✕
          </button>
        )}
      </div>

      {significant.length > 0 && (
        <div className="significant-section">
          <h4>⚠️ {significant.length} Significant Update(s)</h4>
          <div className="updates-list">
            {significant.map(u => (
              <UpdateCard key={u.event_id} update={u} />
            ))}
          </div>
        </div>
      )}

      {updates.length > significant.length && (
        <div className="all-updates-section">
          <h4>Other Updates ({updates.length - significant.length})</h4>
          <div className="updates-list compact">
            {updates
              .filter(u => !u.is_significant)
              .map(u => (
                <UpdateCard key={u.event_id} update={u} />
              ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default EventUpdateNotification
