import Avatar from '../common/Avatar'
import { getInitials, getColor, formatTime } from '../../utils/avatar'

const ATTACHMENT_MARKER = '[[orbit-attachment]]'

function renderContent(content) {
  const lines = String(content || '').split(/\\n|\r?\n/)
  return lines.map((line, index) => {
    if (!line.startsWith(ATTACHMENT_MARKER)) return <span key={`text-${index}`}>{line}{index < lines.length - 1 && <br />}</span>
    try {
      const file = JSON.parse(line.slice(ATTACHMENT_MARKER.length))
      if (!file?.name || !String(file.dataUrl || '').startsWith('data:')) throw new Error('Invalid attachment')
      return <span className="message-attachment" key={`file-${index}`}>
        {file.type?.startsWith('image/') ? <img src={file.dataUrl} alt={file.name} /> : <i className="bi bi-file-earmark" />}
        <a href={file.dataUrl} download={file.name}>{file.name}</a>
      </span>
    } catch {
      return <span key={`text-${index}`}>{line}</span>
    }
  })
}

function ReadReceipts({ readers }) {
  if (!readers.length) return null
  const visible = readers.slice(0, 5)
  const remaining = readers.length - visible.length
  return <div className="message-readers" aria-label={`Đã xem bởi ${readers.map(reader => reader.display_name).join(', ')}`}>
    {visible.map(reader => <span className="message-reader" title={`Đã xem: ${reader.display_name}`} key={reader.user_id}>
      <Avatar initials={getInitials(reader.display_name)} color={getColor(reader.user_id)} size={18} />
    </span>)}
    {remaining > 0 && <span className="message-reader-more" title={`${remaining} người khác đã xem`}>+{remaining}</span>}
  </div>
}

export default function MessageBubble({ message, own, readers = [] }) {
  const body = renderContent(message.content)
  if (own) return (
    <div className="message-row own"><div className="message-content"><div className="message-bubble">{body}</div><div className="message-time">{formatTime(message.created_at)} <i className="bi bi-check2-all" /></div><ReadReceipts readers={readers} /></div></div>
  )
  return (
    <div className="message-row"><Avatar initials={getInitials(message.sender_name)} color={getColor(message.sender_id)} size={34} /><div className="message-content"><div className="message-sender">{message.sender_name}</div><div className="message-bubble">{body}</div><div className="message-time">{formatTime(message.created_at)}</div></div></div>
  )
}
