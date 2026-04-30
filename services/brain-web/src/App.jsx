import { useState, useEffect, useCallback } from 'react'
import keycloak from './keycloak'
import { listNotes, getNote, createNote, updateNote, deleteNote } from './api/notes'
import Header from './components/Header'
import NoteList from './components/NoteList'
import NoteEditor from './components/NoteEditor'
import './App.css'

const EMPTY_NOTE = { title: '', content: '', visibility: 'private', tags: [] }

export default function App() {
  const [notes, setNotes]           = useState([])
  const [selected, setSelected]     = useState(null)   // full NoteDetailResponse
  const [isNew, setIsNew]           = useState(false)
  const [draft, setDraft]           = useState(EMPTY_NOTE)
  const [loading, setLoading]       = useState(false)
  const [saving, setSaving]         = useState(false)
  const [error, setError]           = useState(null)
  const [filterVis, setFilterVis]   = useState('')
  const [filterTag, setFilterTag]   = useState('')

  // ── Load note list ─────────────────────────────────────────────────────────
  const loadNotes = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listNotes({ visibility: filterVis || undefined, tag: filterTag || undefined })
      setNotes(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [filterVis, filterTag])

  useEffect(() => { loadNotes() }, [loadNotes])

  // ── Select existing note ───────────────────────────────────────────────────
  const handleSelect = async (note) => {
    setIsNew(false)
    setError(null)
    try {
      const full = await getNote(note.id)
      setSelected(full)
      setDraft({ title: full.title, content: full.content, visibility: full.visibility, tags: full.tags })
    } catch (e) {
      setError(e.message)
    }
  }

  // ── New note ───────────────────────────────────────────────────────────────
  const handleNew = () => {
    setSelected(null)
    setIsNew(true)
    setDraft(EMPTY_NOTE)
    setError(null)
  }

  // ── Save (create or update) ────────────────────────────────────────────────
  const handleSave = async () => {
    if (!draft.title.trim()) { setError('Title is required.'); return }
    setSaving(true)
    setError(null)
    try {
      if (isNew) {
        const created = await createNote(draft)
        setIsNew(false)
        setSelected({ ...created, content: draft.content })
        await loadNotes()
      } else {
        const updated = await updateNote(selected.id, draft)
        setSelected({ ...updated, content: draft.content })
        setNotes(prev => prev.map(n => n.id === updated.id ? updated : n))
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  // ── Delete ─────────────────────────────────────────────────────────────────
  const handleDelete = async (noteId) => {
    if (!confirm('Delete this note? This cannot be undone.')) return
    setError(null)
    try {
      await deleteNote(noteId)
      setSelected(null)
      setIsNew(false)
      setDraft(EMPTY_NOTE)
      setNotes(prev => prev.filter(n => n.id !== noteId))
    } catch (e) {
      setError(e.message)
    }
  }

  const isDirty = selected
    ? draft.title !== selected.title ||
      draft.content !== selected.content ||
      draft.visibility !== selected.visibility ||
      JSON.stringify(draft.tags) !== JSON.stringify(selected.tags)
    : isNew && (draft.title || draft.content)

  return (
    <div className="app-shell">
      <Header
        user={keycloak.tokenParsed}
        onLogout={() => keycloak.logout({ redirectUri: window.location.origin })}
      />

      <div className="app-body">
        <NoteList
          notes={notes}
          loading={loading}
          selectedId={selected?.id}
          filterVis={filterVis}
          filterTag={filterTag}
          onFilterVis={setFilterVis}
          onFilterTag={setFilterTag}
          onSelect={handleSelect}
          onNew={handleNew}
        />

        <main className="editor-pane">
          {error && <div className="error-banner">{error}</div>}

          {(selected || isNew) ? (
            <NoteEditor
              draft={draft}
              onChange={setDraft}
              onSave={handleSave}
              onDelete={selected ? () => handleDelete(selected.id) : null}
              saving={saving}
              isDirty={!!isDirty}
              isNew={isNew}
            />
          ) : (
            <EmptyState onNew={handleNew} />
          )}
        </main>
      </div>
    </div>
  )
}

function EmptyState({ onNew }) {
  return (
    <div className="empty-state">
      <div className="empty-icon">🧠</div>
      <h2>Bedrock Brain</h2>
      <p>Select a note from the sidebar or create a new one.</p>
      <button className="btn-primary" onClick={onNew}>New note</button>
    </div>
  )
}
