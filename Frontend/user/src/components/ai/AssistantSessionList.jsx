import { useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useAuth } from '../../context/AuthContext'
import { deleteAssistantThread, listAssistantThreads } from '../../api/assistant'
import { formatDateShort, formatClock } from '../../utils/datetime'
import { queryClient, queryKeys } from '../../query/queryClient'
import ConfirmDialog from '../common/ConfirmDialog'

const formatThreadTime = (iso) => {
  if (!iso) return ''
  const sameDay = new Date(iso).toDateString() === new Date().toDateString()
  return sameDay ? formatClock(iso) : formatDateShort(iso)
}

export default function AssistantSessionList({ activeThreadId, onSelectThread, onNewThread, refreshSignal }) {
  const { token } = useAuth()
  const [search, setSearch] = useState('')
  const [deleteError, setDeleteError] = useState('')
  const [deleteTarget, setDeleteTarget] = useState(null)
  const threadsQuery = useQuery({
    queryKey: queryKeys.assistantThreads,
    queryFn: () => listAssistantThreads(token),
    enabled: Boolean(token),
    staleTime: 30_000,
  })
  const threads = threadsQuery.data || []
  const loading = threadsQuery.isPending
  const deleteMutation = useMutation({
    mutationFn: threadId => deleteAssistantThread(token, threadId),
    onSuccess: (_result, threadId) => {
      queryClient.setQueryData(queryKeys.assistantThreads, current =>
        (current || []).filter(thread => thread.thread_id !== threadId)
      )
      queryClient.removeQueries({ queryKey: queryKeys.assistantMessages(threadId), exact: true })
      queryClient.removeQueries({ queryKey: queryKeys.assistantPending(threadId), exact: true })
      if (threadId === activeThreadId) onNewThread()
      setDeleteTarget(null)
      setDeleteError('')
    },
    onError: error => setDeleteError(error.detail || 'Không xóa được cuộc trò chuyện. Vui lòng thử lại.'),
  })

  useEffect(() => {
    if (refreshSignal > 0) threadsQuery.refetch()
  }, [refreshSignal]) // eslint-disable-line react-hooks/exhaustive-deps

  const visible = threads.filter(t => t.title.toLowerCase().includes(search.toLowerCase()))

  const requestDelete = (event, thread) => {
    event.stopPropagation()
    if (deleteMutation.isPending) return
    setDeleteError('')
    setDeleteTarget(thread)
  }

  return <><aside className="assistant-sessions">
    <div className="assistant-session-head"><div><span>Personal space</span><h2>Trợ lý của tôi</h2></div><button className="icon-btn primary-soft" aria-label="Cuộc trò chuyện mới" onClick={onNewThread}><i className="bi bi-plus-lg" /></button></div>
    <div className="session-search"><i className="bi bi-search"/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Tìm cuộc trò chuyện"/></div>
    <div className="session-caption">Gần đây</div>
    <div className="session-items">
      {!loading && visible.length === 0 && <p className="session-empty">Chưa có cuộc trò chuyện nào với Trợ lý.</p>}
      {visible.map(t=><div className={`session-item-row ${t.thread_id===activeThreadId?'active':''}`} key={t.thread_id}>
        <button className={`session-item ${t.thread_id===activeThreadId?'active':''}`} onClick={()=>onSelectThread(t.thread_id)}><span className="session-item-icon"><i className="bi bi-chat-square-text"/></span><span className="session-item-copy"><strong>{t.title}</strong><small>{t.preview}</small></span><time>{formatThreadTime(t.updated_at)}</time></button>
        <button className="session-delete" type="button" aria-label={`Xóa cuộc trò chuyện ${t.title}`} title="Xóa cuộc trò chuyện" disabled={deleteMutation.isPending} onClick={event=>requestDelete(event,t)}><i className="bi bi-trash3"/></button>
      </div>)}
      {deleteError && <p className="session-delete-error" role="alert">{deleteError}</p>}
    </div>
    <div className="assistant-private"><i className="bi bi-shield-check"/><div><strong>Không gian riêng tư</strong><small>Chỉ bạn có thể xem nội dung tại đây.</small></div></div>
  </aside><ConfirmDialog
    open={Boolean(deleteTarget)}
    title="Xóa cuộc trò chuyện?"
    message={deleteTarget ? `Lịch sử “${deleteTarget.title}” sẽ bị xóa vĩnh viễn và không thể khôi phục.` : ''}
    confirmLabel={deleteMutation.isPending ? 'Đang xóa…' : 'Xóa cuộc trò chuyện'}
    busy={deleteMutation.isPending}
    onCancel={()=>{ if (!deleteMutation.isPending) setDeleteTarget(null) }}
    onConfirm={()=>{ if (deleteTarget && !deleteMutation.isPending) deleteMutation.mutate(deleteTarget.thread_id) }}
  /></>
}
