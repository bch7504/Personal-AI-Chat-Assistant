import { useEffect, useState } from 'react'
import PageHeader from '../../components/common/PageHeader'
import ConversationTable from '../../components/admin/ConversationTable'
import ConversationMessagesModal from '../../components/admin/ConversationMessagesModal'
import { useAuth } from '../../context/AuthContext'
import { listConversations, deleteConversation } from '../../api/admin'

export default function AdminConversationsPage() {
  const { token } = useAuth()
  const [conversations, setConversations] = useState([])
  const [loading, setLoading] = useState(true)
  const [viewing, setViewing] = useState(null)

  const refresh = () => {
    setLoading(true)
    listConversations(token).then(setConversations).finally(() => setLoading(false))
  }

  useEffect(() => { refresh() }, [token])

  const onDelete = async (c) => {
    if (!window.confirm(`Delete this conversation? This removes all its messages permanently.`)) return
    await deleteConversation(token, c.id)
    setConversations(list => list.filter(x => x.id !== c.id))
  }

  return (
    <div className="page-container">
      <PageHeader eyebrow="Admin" title="Conversations" description="Review and moderate 1-1 and group conversations." />
      <section className="content-card">
        <div className="card-toolbar"><div><h3>All conversations</h3><span>{conversations.length} conversations</span></div></div>
        {loading ? <p className="text-muted small p-3 mb-0">Loading...</p> : (
          <ConversationTable conversations={conversations} onView={setViewing} onDelete={onDelete} />
        )}
      </section>
      <ConversationMessagesModal conversation={viewing} onClose={() => setViewing(null)} />
    </div>
  )
}
