import { useState, useEffect } from 'react'
import { marked } from 'marked'
import './NoteEditor.css'

// Configure marked — safe defaults
marked.setOptions({ breaks: true, gfm: true })

const VIS_OPTIONS = [
  { value: 'private', label: '🔒 Private',  desc: 'Only you' },
  { value: 'team',    label: '👥 Team',     desc: 'Your team' },
  { value: 'org',     label: '🏢 Org',      desc: 'Whole org' },
  { value: 'public',  label: '🌐 Public',   desc: 'Everyone' },
]

export default function NoteEditor({ draft, onChange, onSave, onDelete, saving, isDirty, isNew }) {
  const [mode, setMode] = useState('edit')   // 'edit' | 'preview' | 'split'
  const [tagInput, setTagInput] = useState('')

  // Reset tag input when switching notes
  useEffect(() => { setTagInput('') }, [draft.title])

  const set = (field, val) => onChange({ ...draft, [field]: val })

  const addTag = () => {
    const t = tagInput.trim().toLowerCase().replace(/\s+/g, '-')
    if (t && !draft.tags.includes(t)) {
      set('tags', [...draft.tags, t])
    }
    setTagInput('')
  }

  const removeTag = (tag) => set('tags', draft.tags.filter(t => t !== tag))

  const handleTagKey = (e) => {
    if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); addTag() }
    if (e.key === 'Backspace' && !tagInput && draft.tags.length) {
      set('tags', draft.tags.slice(0, -1))
    }
  }

  const html = marked.parse(draft.content || '')

  return (
    <div className="note-editor">
      {/* ── Toolbar ── */}
      <div className="editor-toolbar">
        <input
          className="title-input"
          placeholder="Note title…"
          value={draft.title}
          onChange={e => set('title', e.target.value)}
        />

        <div className="toolbar-right">
          {/* Visibility selector */}
          <select
            className="vis-select"
            value={draft.visibility}
            onChange={e => set('visibility', e.target.value)}
          >
            {VIS_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>

          {/* View mode toggle */}
          <div className="mode-toggle">
            {['edit', 'split', 'preview'].map(m => (
              <button
                key={m}
                className={`mode-btn ${mode === m ? 'active' : ''}`}
                onClick={() => setMode(m)}
                title={m.charAt(0).toUpperCase() + m.slice(1)}
              >
                {m === 'edit' ? '✏️' : m === 'preview' ? '👁' : '⬛⬜'}
              </button>
            ))}
          </div>

          {onDelete && (
            <button className="btn-danger" onClick={onDelete} title="Delete note">
              🗑
            </button>
          )}

          <button
            className="btn-primary"
            onClick={onSave}
            disabled={saving || !isDirty}
          >
            {saving ? 'Saving…' : isNew ? 'Create' : 'Save'}
          </button>
        </div>
      </div>

      {/* ── Tags bar ── */}
      <div className="tags-bar">
        <div className="tags-list">
          {draft.tags.map(t => (
            <span key={t} className="tag tag-removable">
              {t}
              <button className="tag-remove" onClick={() => removeTag(t)}>×</button>
            </span>
          ))}
          <input
            className="tag-input"
            placeholder={draft.tags.length ? '' : 'Add tags…'}
            value={tagInput}
            onChange={e => setTagInput(e.target.value)}
            onKeyDown={handleTagKey}
            onBlur={addTag}
          />
        </div>
        <span className="tags-hint">Enter or comma to add</span>
      </div>

      {/* ── Editor / Preview ── */}
      <div className={`editor-body mode-${mode}`}>
        {(mode === 'edit' || mode === 'split') && (
          <textarea
            className="content-textarea"
            placeholder="Write in Markdown…"
            value={draft.content}
            onChange={e => set('content', e.target.value)}
            spellCheck
          />
        )}
        {(mode === 'preview' || mode === 'split') && (
          <div
            className="content-preview"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        )}
      </div>
    </div>
  )
}
