import { useState } from 'react'
import PageHeader from '../components/common/PageHeader'
import MemoryModal from '../components/memory/MemoryModal'
import { useAuth } from '../context/AuthContext'
import { deleteMemory } from '../api/memories'
import { useMemoriesQuery } from '../hooks/usePersonalData'
import { formatDateShort } from '../utils/datetime'

const CATEGORY_STYLE = {
  Work: { icon: 'bi-briefcase', color: '#526ff5' },
  Preference: { icon: 'bi-sliders', color: '#8b5cf6' },
  People: { icon: 'bi-people', color: '#ef5675' },
  Language: { icon: 'bi-translate', color: '#10b981' },
  Routine: { icon: 'bi-clock', color: '#f59e0b' },
}
const DEFAULT_STYLE = { icon: 'bi-stars', color: '#64748b' }

export default function MemoryPage() {
  const { token } = useAuth()
  const { items: memories, setItems: setMemories, loading, error: queryError } = useMemoriesQuery(token)
  const [query, setQuery] = useState('')
  const [tab, setTab] = useState('All')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [error, setError] = useState('')

  const categories = ['All', ...new Set(memories.map(m => m.category))]
  const shown = memories
    .filter(m => tab === 'All' || m.category === tab)
    .filter(m => (m.title + m.category).toLowerCase().includes(query.toLowerCase()))

  const openAdd = () => { setEditing(null); setModalOpen(true) }
  const openEdit = (m) => { setEditing(m); setModalOpen(true) }
  const onSaved = (saved) => setMemories(prev => {
    const exists = prev.some(m => m.id === saved.id)
    return exists ? prev.map(m => m.id === saved.id ? saved : m) : [saved, ...prev]
  })
  const remove = (m) => deleteMemory(token, m.id).then(() => setMemories(prev => prev.filter(x => x.id !== m.id))).catch(err => setError(err.detail || 'Could not delete memory.'))

  return <div className="page-container">
    <PageHeader eyebrow="Personal context" title="Memory" description="The helpful details Orbit remembers to personalize your experience." action={<button className="btn btn-primary" onClick={openAdd}><i className="bi bi-plus-lg me-2"/>Add memory</button>}/>
    {(error || queryError) && <div className="auth-error mb-3">{error || queryError.detail || 'Could not load memories.'}</div>}
    <div className="memory-toolbar"><div className="memory-search"><i className="bi bi-search"/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search memories..."/></div><div className="memory-tabs">{categories.map(c=><button key={c} className={tab===c?'active':''} onClick={()=>setTab(c)}>{c} {c==='All'&&<span>{memories.length}</span>}</button>)}</div></div>
    {loading ? <p className="text-muted small">Loading...</p> : <div className="memory-grid">{shown.map(m=>{
      const style = CATEGORY_STYLE[m.category] || DEFAULT_STYLE
      return <div className="memory-card" key={m.id}><div className="memory-card-top"><div className="memory-icon" style={{background:`${style.color}12`,color:style.color}}><i className={`bi ${style.icon}`}/></div><span>{m.category}</span><div className="dropdown ms-auto"><button className="icon-btn" data-bs-toggle="dropdown"><i className="bi bi-three-dots"/></button><ul className="dropdown-menu dropdown-menu-end"><li><button className="dropdown-item" onClick={()=>openEdit(m)}><i className="bi bi-pencil me-2"/>Edit</button></li><li><button className="dropdown-item text-danger" onClick={()=>remove(m)}><i className="bi bi-trash me-2"/>Delete</button></li></ul></div></div><h3>{m.title}</h3><p>{m.detail}</p><div className="memory-footer"><span><i className="bi bi-clock"/> Remembered {formatDateShort(m.created_at)}</span><i className="bi bi-stars"/></div></div>
    })}
      {!shown.length && <p className="text-muted small mb-0">No memories yet — add one, or they'll build up as Orbit learns from your conversations.</p>}
    </div>}
    <div className="memory-info"><i className="bi bi-shield-check"/><div><strong>Your memory is private</strong><p>You control what Orbit remembers. Edit or delete anything at any time.</p></div></div>
    <MemoryModal open={modalOpen} onClose={()=>setModalOpen(false)} onSaved={onSaved} memory={editing}/>
  </div>
}
