import './NoteList.css'

const VIS_OPTIONS = [
  { value: '',        label: 'All' },
  { value: 'private', label: 'Private' },
  { value: 'team',    label: 'Team' },
  { value: 'org',     label: 'Org' },
  { value: 'public',  label: 'Public' },
]

const VIS_ICONS = { private: '🔒', team: '👥', org: '🏢', public: '🌐' }

function formatDate(iso) {
  const d = new Date(iso)
  const now = new Date()
  const diff = now - d
  if (diff < 60_000)       return 'just now'
  if (diff < 3_600_000)    return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000)   return `${Math.floor(diff / 3_600_000)}h ago`
  if (diff < 604_800_000)  return `${Math.floor(diff / 86_400_000)}d ago`
  return d.toLocaleDateString()
}

export default function NoteList({
  notes, loading, selectedId,
  filterVis, filterTag,
  onFilterVis, onFilterTag,
  onSelect, onNew,
}) {
  return (
    <aside className="note-list">
      {/* Top bar */}
      <div className="note-list-top">
        <span className="note-list-title">Notes</span>
        <button className="btn-new" onClick={onNew} title="New note">＋</button>
      </div>

      {/* Filters */}
      <div className="note-list-filters">
        <div className="filter-tabs">
          {VIS_OPTIONS.map(o => (
            <button
              key={o.value}
              className={`filter-tab ${filterVis === o.value ? 'active' : ''}`}
              onClick={() => onFilterVis(o.value)}
            >
              {o.label}
            </button>
          ))}
        </div>
        <input
          className="tag-filter"
          placeholder="Filter by tag…"
          value={filterTag}
          onChange={e => onFilterTag(e.target.value)}
        />
      </div>

      {/* List */}
      <ul className="note-items">
        {loading && <li className="note-empty">Loading…</li>}
        {!loading && notes.length === 0 && (
          <li className="note-empty">No notes found.</li>
        )}
        {!loading && notes.map(note => (
          <li
            key={note.id}
            className={`note-item ${note.id === selectedId ? 'selected' : ''}`}
            onClick={() => onSelect(note)}
          >
            <div className="note-item-top">
              <span className="note-item-title">{note.title || 'Untitled'}</span>
              <span className="note-item-vis" title={note.visibility}>
                {VIS_ICONS[note.visibility] || ''}
              </span>
            </div>
            <div className="note-item-meta">
              <span className="note-item-date">{formatDate(note.updated_at)}</span>
              {note.tags?.length > 0 && (
                <div className="note-item-tags">
                  {note.tags.slice(0, 3).map(t => (
                    <span key={t} className="tag">{t}</span>
                  ))}
                  {note.tags.length > 3 && (
                    <span className="tag">+{note.tags.length - 3}</span>
                  )}
                </div>
              )}
            </div>
          </li>
        ))}
      </ul>
    </aside>
  )
}
