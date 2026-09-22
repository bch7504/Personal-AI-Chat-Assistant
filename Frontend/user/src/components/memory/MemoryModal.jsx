import { useEffect, useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import { createMemory, updateMemory } from '../../api/memories'

const CATEGORIES = ['Work', 'Preference', 'People', 'Language', 'Routine']
const memoryTypeForCategory = (category) => {
  if (['Preference', 'Language', 'Routine'].includes(category)) return 'preference'
  if (category === 'People') return 'relationship'
  return 'semantic'
}

export default function MemoryModal({ open, onClose, onSaved, memory = null }) {
  const { token } = useAuth()
  const [category, setCategory] = useState('Preference')
  const [title, setTitle] = useState('')
  const [detail, setDetail] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setCategory(memory?.category || 'Preference')
    setTitle(memory?.title || '')
    setDetail(memory?.detail || '')
    setError('')
  }, [open, memory])

  if (!open) return null

  const submit = async (e) => {
    e.preventDefault()
    if (!title.trim()) return
    setSubmitting(true); setError('')
    try {
      const memory_type = memoryTypeForCategory(category)
      const saved = memory
        ? await updateMemory(token, memory.id, { category, title: title.trim(), detail: detail.trim(), memory_type })
        : await createMemory(token, { category, title: title.trim(), detail: detail.trim(), memory_type })
      onSaved(saved)
      onClose()
    } catch (err) { setError(err.detail || 'Could not save this memory.') }
    finally { setSubmitting(false) }
  }

  return (
    <div className="modal show d-block" tabIndex="-1" style={{ background: 'rgba(20,30,50,.32)' }} onClick={onClose}>
      <div className="modal-dialog modal-dialog-centered" onClick={e => e.stopPropagation()}>
        <div className="modal-content">
          <div className="modal-header"><h5 className="modal-title">{memory ? 'Edit memory' : 'Add memory'}</h5><button className="btn-close" onClick={onClose} /></div>
          <form onSubmit={submit}>
            <div className="modal-body d-flex flex-column gap-3">
              {error && <div className="auth-error">{error}</div>}
              <select className="form-select" value={category} onChange={e => setCategory(e.target.value)}>
                {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
              <input className="form-control" placeholder="Ví dụ: Gọi tôi là sếp" value={title} onChange={e => setTitle(e.target.value)} required />
              <textarea className="form-control" placeholder="Chi tiết bổ sung (không bắt buộc)" value={detail} onChange={e => setDetail(e.target.value)} rows={3} />
              <div className="form-text">
                Preference, Language và Routine được áp dụng trong các cuộc trò chuyện Personal Agent.
                Work và People được lấy ra khi câu hỏi có liên quan.
              </div>
            </div>
            <div className="modal-footer">
              <button type="button" className="btn btn-light" onClick={onClose}>Cancel</button>
              <button type="submit" className="btn btn-primary" disabled={submitting}>{submitting ? 'Saving...' : memory ? 'Save changes' : 'Add memory'}</button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}
