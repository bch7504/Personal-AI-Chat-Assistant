import { useState } from 'react'
import { submitTask } from '../../api/tasks'
import { useAuth } from '../../context/AuthContext'

export default function TaskSubmissionModal({ task, onClose, onSubmitted }) {
  const { token } = useAuth()
  const [note, setNote] = useState(task?.submission_note || '')
  const [urls, setUrls] = useState((task?.evidence_urls || []).join('\n'))
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  if (!task) return null

  const submit = async event => {
    event.preventDefault()
    setSubmitting(true); setError('')
    try {
      const evidence_urls = urls.split('\n').map(value => value.trim()).filter(Boolean)
      const updated = await submitTask(token, task.id, {
        submission_note: note.trim() || null,
        evidence_urls,
        expected_row_version: task.row_version,
      })
      onSubmitted(updated)
      onClose()
    } catch (err) {
      setError(err.detail || 'Không thể nộp task. Vui lòng kiểm tra evidence và thử lại.')
    } finally { setSubmitting(false) }
  }

  return <div className="modal show d-block" tabIndex="-1" style={{ background: 'rgba(20,30,50,.42)' }} onClick={onClose}>
    <div className="modal-dialog modal-dialog-centered" onClick={event => event.stopPropagation()}><div className="modal-content">
      <div className="modal-header"><div><small className="text-muted">Submit for Lead review</small><h5 className="modal-title">{task.title}</h5></div><button className="btn-close" onClick={onClose} /></div>
      <form onSubmit={submit}><div className="modal-body d-flex flex-column gap-3">
        {task.status === 'changes_requested' && task.review_note && <div className="alert alert-warning mb-0"><strong>Lead yêu cầu chỉnh sửa:</strong> {task.review_note}</div>}
        {error && <div className="auth-error">{error}</div>}
        <label className="form-label mb-0">Kết quả thực hiện<textarea className="form-control mt-1" rows="4" maxLength="4000" value={note} onChange={event => setNote(event.target.value)} placeholder="Mô tả kết quả, phạm vi đã kiểm tra và lưu ý cho reviewer." /></label>
        <label className="form-label mb-0">Evidence URLs<textarea className="form-control mt-1" rows="4" value={urls} onChange={event => setUrls(event.target.value)} placeholder={'https://github.../pull/42\nhttps://docs.../report'} /></label>
        <small className="text-muted">Mỗi dòng một URL PR, tài liệu, test report hoặc ticket. Cần ít nhất ghi chú hoặc một URL.</small>
      </div><div className="modal-footer"><button type="button" className="btn btn-light" onClick={onClose}>Hủy</button><button className="btn btn-primary" disabled={submitting}>{submitting ? 'Đang nộp...' : 'Submit for review'}</button></div></form>
    </div></div>
  </div>
}
