import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PageHeader from '../components/common/PageHeader'
import { createConversation } from '../api/chat'
import {
  archiveRelationship,
  createExternalContact,
  createRelationship,
  listPeopleInsights,
  listRelationships,
  updatePeoplePreference,
  updateRelationship,
} from '../api/relationships'
import { addWorkspaceMember, listWorkspaceMembers } from '../api/workspaces'
import { useAuth } from '../context/AuthContext'
import { useWorkspace } from '../context/WorkspaceContext'

const SEGMENTS = [
  ['all', 'All people'],
  ['frequent', 'Frequent'],
  ['recent', 'Recent'],
  ['pinned', 'Pinned'],
  ['follow_up', 'Follow up'],
  ['external', 'External'],
]

const EXTERNAL_TYPES = [
  ['client', 'Client'],
  ['partner', 'Partner'],
  ['vendor', 'Vendor'],
  ['mentor', 'Mentor'],
  ['other', 'Other'],
]

const EMPTY_MEMBER = { email: '', role: 'member' }
const EMPTY_EXTERNAL = { display_name: '', email: '', organization: '', relationship_type: 'client', custom_label: '', notes: '' }

const initials = name => (name || '?').trim().split(/\s+/).map(word => word[0]).slice(0, 2).join('').toUpperCase()

const localDateTime = value => {
  if (!value) return ''
  const date = new Date(value)
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

const relativeTime = value => {
  if (!value) return 'No shared activity yet'
  const days = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 86_400_000))
  if (days === 0) return 'Active today'
  if (days === 1) return 'Active yesterday'
  if (days < 30) return `Active ${days} days ago`
  const months = Math.floor(days / 30)
  return `Active ${months} month${months === 1 ? '' : 's'} ago`
}

function PersonModal({ person, open, onClose, onSave, saving }) {
  const [form, setForm] = useState({ is_pinned: false, private_note: '', follow_up_at: '' })

  useEffect(() => {
    if (!person) return
    setForm({
      is_pinned: person.is_pinned,
      private_note: person.private_note || '',
      follow_up_at: localDateTime(person.follow_up_at),
    })
  }, [person])

  if (!open || !person) return null
  const submit = event => {
    event.preventDefault()
    onSave(person.user_id, {
      is_pinned: form.is_pinned,
      private_note: form.private_note || null,
      follow_up_at: form.follow_up_at ? new Date(form.follow_up_at).toISOString() : null,
    })
  }
  return <div className="relationship-modal-backdrop" onClick={onClose}>
    <div className="relationship-modal relationship-contact-modal" onClick={event => event.stopPropagation()}>
      <div className="relationship-modal-head"><div><span>Private context</span><h3>{person.display_name}</h3></div><button className="icon-btn" onClick={onClose} aria-label="Close"><i className="bi bi-x-lg" /></button></div>
      <form onSubmit={submit}>
        <label className="people-pin-toggle"><input type="checkbox" checked={form.is_pinned} onChange={event => setForm(current => ({...current,is_pinned:event.target.checked}))} /><span><strong>Pin this person</strong><small>Keep them at the top of your People view.</small></span></label>
        <label className="relationship-field"><span>Private note <small>Only you and your AI context can use this</small></span><textarea className="form-control" maxLength="2000" value={form.private_note} onChange={event => setForm(current => ({...current,private_note:event.target.value}))} placeholder="Working preferences, useful context, or what to remember." /></label>
        <label className="relationship-field"><span>Follow up at</span><input className="form-control" type="datetime-local" value={form.follow_up_at} onChange={event => setForm(current => ({...current,follow_up_at:event.target.value}))} /></label>
        <div className="people-privacy-note"><i className="bi bi-shield-lock" /> Interaction metrics use message/task metadata, not message content.</div>
        <div className="relationship-modal-actions"><button type="button" className="btn btn-light" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={saving}>{saving ? 'Saving...' : 'Save context'}</button></div>
      </form>
    </div>
  </div>
}

function ExternalModal({ open, editing, onClose, onSubmit, saving }) {
  const [form, setForm] = useState(EMPTY_EXTERNAL)
  useEffect(() => {
    setForm(editing ? {
      display_name: editing.display_name,
      email: editing.email,
      organization: editing.organization || '',
      relationship_type: editing.relationship_type,
      custom_label: editing.custom_label || '',
      notes: editing.notes || '',
    } : EMPTY_EXTERNAL)
  }, [editing, open])
  if (!open) return null
  const submit = event => { event.preventDefault(); onSubmit(form, editing) }
  return <div className="relationship-modal-backdrop" onClick={onClose}>
    <div className="relationship-modal relationship-contact-modal" onClick={event => event.stopPropagation()}>
      <div className="relationship-modal-head"><div><span>External network</span><h3>{editing ? `Update ${editing.display_name}` : 'Add external contact'}</h3></div><button className="icon-btn" onClick={onClose} aria-label="Close"><i className="bi bi-x-lg" /></button></div>
      <form onSubmit={submit}>
        {!editing && <><label className="relationship-field"><span>Name</span><input className="form-control" required maxLength="120" value={form.display_name} onChange={event => setForm({...form,display_name:event.target.value})} /></label><label className="relationship-field"><span>Email</span><input className="form-control" type="email" required value={form.email} onChange={event => setForm({...form,email:event.target.value})} /></label><label className="relationship-field"><span>Company</span><input className="form-control" maxLength="160" value={form.organization} onChange={event => setForm({...form,organization:event.target.value})} /></label></>}
        <label className="relationship-field"><span>Business context</span><select className="form-select" value={form.relationship_type} onChange={event => setForm({...form,relationship_type:event.target.value})}>{EXTERNAL_TYPES.map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        {form.relationship_type === 'other' && <label className="relationship-field"><span>Custom label</span><input className="form-control" required maxLength="80" value={form.custom_label} onChange={event => setForm({...form,custom_label:event.target.value})} /></label>}
        <label className="relationship-field"><span>Private note</span><textarea className="form-control" maxLength="2000" value={form.notes} onChange={event => setForm({...form,notes:event.target.value})} /></label>
        <div className="relationship-modal-actions"><button type="button" className="btn btn-light" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={saving}>{saving ? 'Saving...' : editing ? 'Save changes' : 'Add contact'}</button></div>
      </form>
    </div>
  </div>
}

function TeamModal({ open, members, canManage, form, setForm, onClose, onSubmit, saving }) {
  if (!open) return null
  return <div className="relationship-modal-backdrop" onClick={onClose}>
    <div className="relationship-modal" onClick={event => event.stopPropagation()}>
      <div className="relationship-modal-head"><div><span>Team workspace</span><h3>Members</h3></div><button className="icon-btn" onClick={onClose} aria-label="Close"><i className="bi bi-x-lg" /></button></div>
      <div className="relationship-member-list">{members.map(member => <div key={member.id}><div className="relationship-avatar">{initials(member.display_name)}</div><span><strong>{member.display_name}</strong><small>{member.email}</small></span><em>{member.role.replace('_', ' ')}</em></div>)}</div>
      {canManage ? <form onSubmit={onSubmit} className="relationship-member-form"><h4>Add a registered user</h4><label className="relationship-field"><span>Email</span><input className="form-control" type="email" required value={form.email} onChange={event => setForm({...form,email:event.target.value})} placeholder="name@company.com" /></label><label className="relationship-field"><span>Workspace access</span><select className="form-select" value={form.role} onChange={event => setForm({...form,role:event.target.value})}><option value="member">Member</option><option value="admin">Workspace admin</option><option value="guest">Guest</option></select></label><div className="relationship-modal-actions"><button type="button" className="btn btn-light" onClick={onClose}>Close</button><button className="btn btn-primary" disabled={saving}>{saving ? 'Adding...' : 'Add member'}</button></div></form> : <div className="relationship-notice"><i className="bi bi-info-circle" /><div><strong>Read-only directory</strong><span>Only workspace owners and admins can add members.</span></div></div>}
    </div>
  </div>
}

function ArchiveModal({ item, onClose, onConfirm, saving }) {
  if (!item) return null
  return <div className="relationship-modal-backdrop" onClick={onClose}><div className="relationship-modal people-confirm-modal" onClick={event => event.stopPropagation()}><div className="people-confirm-icon"><i className="bi bi-archive" /></div><h3>Archive {item.display_name}?</h3><p>This removes the contact from the active view without deleting its historical record.</p><div className="relationship-modal-actions"><button className="btn btn-light" onClick={onClose}>Cancel</button><button className="btn btn-danger" onClick={onConfirm} disabled={saving}>{saving ? 'Archiving...' : 'Archive'}</button></div></div></div>
}

export default function RelationshipsPage() {
  const { token } = useAuth()
  const { workspaces, workspace, workspaceId, selectWorkspace } = useWorkspace()
  const navigate = useNavigate()
  const [insights, setInsights] = useState([])
  const [external, setExternal] = useState([])
  const [query, setQuery] = useState('')
  const [segment, setSegment] = useState('all')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [person, setPerson] = useState(null)
  const [externalOpen, setExternalOpen] = useState(false)
  const [editingExternal, setEditingExternal] = useState(null)
  const [archiveTarget, setArchiveTarget] = useState(null)
  const [teamOpen, setTeamOpen] = useState(false)
  const [members, setMembers] = useState([])
  const [memberForm, setMemberForm] = useState(EMPTY_MEMBER)
  const loadRequestRef = useRef(0)
  const loadedWorkspaceIdRef = useRef(null)

  const load = async () => {
    const requestId = ++loadRequestRef.current
    loadedWorkspaceIdRef.current = null
    if (!token || !workspaceId) {
      setInsights([])
      setExternal([])
      setLoading(false)
      return
    }
    setLoading(true); setError('')
    try {
      const [peopleItems, relationshipItems] = await Promise.all([
        workspace?.type === 'organization' ? listPeopleInsights(token, workspaceId) : Promise.resolve([]),
        listRelationships(token, workspaceId),
      ])
      if (requestId !== loadRequestRef.current) return
      setInsights(peopleItems)
      setExternal(relationshipItems.filter(item => item.subject_kind === 'external_contact'))
      loadedWorkspaceIdRef.current = workspaceId
    } catch (requestError) {
      if (requestId === loadRequestRef.current) setError(requestError.detail || requestError.message || 'Could not load the people directory.')
    } finally {
      if (requestId === loadRequestRef.current) setLoading(false)
    }
  }

  useEffect(() => { load() }, [token, workspaceId, workspace?.type])

  const visibleInsights = useMemo(() => insights.filter(item => {
    const matchesQuery = `${item.display_name} ${item.email} ${item.job_title} ${item.private_note || ''}`.toLowerCase().includes(query.toLowerCase())
    const matchesSegment = segment === 'all' || segment === 'external' ? segment !== 'external' : item.tags.includes(segment)
    return matchesQuery && matchesSegment
  }), [insights, query, segment])

  const visibleExternal = useMemo(() => external.filter(item => {
    if (!['all', 'external'].includes(segment)) return false
    return `${item.display_name} ${item.email} ${item.organization || ''} ${item.notes || ''}`.toLowerCase().includes(query.toLowerCase())
  }), [external, query, segment])

  const savePreference = async (userId, body) => {
    setSaving(true); setError('')
    try {
      const updated = await updatePeoplePreference(token, workspaceId, userId, body)
      setInsights(current => current.map(item => item.user_id === userId ? updated : item))
      setPerson(null)
    } catch (requestError) { setError(requestError.detail || 'Could not save private context.') }
    finally { setSaving(false) }
  }

  const togglePin = async item => {
    try {
      const updated = await updatePeoplePreference(token, workspaceId, item.user_id, {is_pinned:!item.is_pinned})
      setInsights(current => current.map(value => value.user_id === item.user_id ? updated : value))
    } catch (requestError) { setError(requestError.detail || 'Could not update pin.') }
  }

  const messagePerson = async item => {
    if (!workspaceId || workspace?.type !== 'organization') {
      setError('Direct conversations are only available in a team workspace.')
      return
    }
    if (loadedWorkspaceIdRef.current !== workspaceId) {
      setError('The selected workspace is still loading. Please try again in a moment.')
      return
    }
    setSaving(true); setError('')
    try {
      const conversation = await createConversation(token, {type:'direct',participant_ids:[item.user_id],name:null,workspace_id:workspaceId})
      navigate('/chat', {state:{conversationId:conversation.id}})
    } catch (requestError) { setError(requestError.detail || requestError.message || 'Could not start a conversation.') }
    finally { setSaving(false) }
  }

  const submitExternal = async (form, editing) => {
    setSaving(true); setError('')
    try {
      const relationshipBody = {relationship_type:form.relationship_type,custom_label:form.relationship_type === 'other' ? form.custom_label : null,strength:3,notes:form.notes || null}
      if (editing) await updateRelationship(token, workspaceId, editing.id, relationshipBody)
      else {
        const contact = await createExternalContact(token, workspaceId, {display_name:form.display_name,email:form.email,organization:form.organization || null})
        await createRelationship(token, workspaceId, {...relationshipBody,subject_kind:'external_contact',subject_id:contact.id})
      }
      setExternalOpen(false); setEditingExternal(null); await load()
    } catch (requestError) { setError(requestError.detail || 'Could not save external contact.') }
    finally { setSaving(false) }
  }

  const confirmArchive = async () => {
    if (!archiveTarget) return
    setSaving(true); setError('')
    try { await archiveRelationship(token, workspaceId, archiveTarget.id); setExternal(current => current.filter(item => item.id !== archiveTarget.id)); setArchiveTarget(null) }
    catch (requestError) { setError(requestError.detail || 'Could not archive contact.') }
    finally { setSaving(false) }
  }

  const openTeam = async () => {
    setTeamOpen(true); setError('')
    try { setMembers(await listWorkspaceMembers(token, workspaceId)) }
    catch (requestError) { setTeamOpen(false); setError(requestError.detail || 'Could not load workspace members.') }
  }

  const submitMember = async event => {
    event.preventDefault(); setSaving(true); setError('')
    try { const created = await addWorkspaceMember(token, workspaceId, memberForm.email, memberForm.role); setMembers(current => [...current,created]); setMemberForm(EMPTY_MEMBER); await load() }
    catch (requestError) { setError(requestError.detail || 'Could not add member.') }
    finally { setSaving(false) }
  }

  const counts = {
    total: insights.length + external.length,
    frequent: insights.filter(item => item.tags.includes('frequent')).length,
    recent: insights.filter(item => item.tags.includes('recent')).length,
    followUp: insights.filter(item => item.tags.includes('follow_up')).length,
  }
  const canManageTeam = ['owner', 'admin'].includes(workspace?.current_user_role)

  return <div className="page-container relationships-page">
    <PageHeader eyebrow="People intelligence" title="People" description="A focused directory powered by real collaboration signals. No manual relationship setup required." action={<div className="relationship-header-actions"><select className="form-select" value={workspaceId || ''} onChange={event => selectWorkspace(event.target.value)}>{workspaces.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select>{workspace?.type === 'organization' && <button className="btn btn-light" onClick={openTeam}><i className="bi bi-people me-2" />Members</button>}<button className="btn btn-primary" onClick={() => {setEditingExternal(null);setExternalOpen(true)}}><i className="bi bi-person-plus me-2" />External contact</button></div>} />
    {workspace?.type === 'personal' && <div className="relationship-notice"><i className="bi bi-info-circle" /><div><strong>Personal workspace</strong><span>External contacts live here. Select a team workspace to see automatic coworker insights.</span></div></div>}
    {error && <div className="auth-error mb-3">{error}</div>}
    <div className="relationship-stats"><div><span><i className="bi bi-people" /></span><strong>{counts.total}</strong><small>People in view</small></div><div><span><i className="bi bi-lightning-charge" /></span><strong>{counts.frequent}</strong><small>Frequent collaborators</small></div><div><span><i className="bi bi-clock-history" /></span><strong>{counts.recent}</strong><small>Recent collaborators</small></div><div><span><i className="bi bi-arrow-repeat" /></span><strong>{counts.followUp}</strong><small>Follow-ups due</small></div></div>
    <div className="people-toolbar"><div className="relationship-search"><i className="bi bi-search" /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search name, email, role, or private note" /></div><div className="people-segments">{SEGMENTS.map(([value,label]) => <button key={value} className={segment === value ? 'active' : ''} onClick={() => setSegment(value)}>{label}</button>)}</div></div>
    {loading ? <div className="relationship-empty"><span className="spinner-border spinner-border-sm" /><p>Calculating collaboration signals...</p></div> : visibleInsights.length || visibleExternal.length ? <div className="relationship-grid">
      {visibleInsights.map(item => <article className="relationship-card people-insight-card" key={item.user_id}><div className="relationship-card-top"><div className="relationship-avatar">{initials(item.display_name)}</div><div><h3>{item.display_name}</h3><p>{item.job_title || item.email}</p></div><button className={`people-pin ${item.is_pinned ? 'active' : ''}`} onClick={() => togglePin(item)} aria-label={item.is_pinned ? 'Unpin person' : 'Pin person'}><i className={`bi ${item.is_pinned ? 'bi-star-fill' : 'bi-star'}`} /></button></div><div className="relationship-tags">{item.tags.filter(tag => tag !== 'directory').map(tag => <span key={tag} className={`people-tag ${tag}`}>{tag.replace('_',' ')}</span>)}<span>{item.workspace_role}</span></div><div className="people-score"><div><span>Collaboration score</span><strong>{item.interaction_score}</strong></div><div className="progress"><div className="progress-bar" style={{width:`${item.interaction_score}%`}} /></div><small>v1 · rolling 30-day signals</small></div><ul className="people-signals">{item.explanations.map(detail => <li key={detail}><i className="bi bi-check2" />{detail}</li>)}</ul><p className={`relationship-note ${item.private_note ? '' : 'empty'}`}>{item.private_note || 'No private note. Add context only when it is useful.'}</p><footer><span><i className="bi bi-clock" />{relativeTime(item.last_interaction_at)}</span><div><button onClick={() => setPerson(item)}>Context</button><button onClick={() => messagePerson(item)}>Message</button></div></footer></article>)}
      {visibleExternal.map(item => <article className="relationship-card" key={item.id}><div className="relationship-card-top"><div className="relationship-avatar external">{initials(item.display_name)}</div><div><h3>{item.display_name}</h3><p>{item.email}</p></div></div><div className="relationship-tags"><span>{item.custom_label || item.relationship_type}</span><span className="external-tag">External</span></div>{item.organization && <p className="relationship-organization"><i className="bi bi-building" />{item.organization}</p>}<p className={`relationship-note ${item.notes ? '' : 'empty'}`}>{item.notes || 'No private note yet.'}</p><footer><span><i className="bi bi-shield-lock" />Private</span><div><button onClick={() => {setEditingExternal(item);setExternalOpen(true)}}>Edit</button><button className="text-danger" onClick={() => setArchiveTarget(item)}>Archive</button></div></footer></article>)}
    </div> : <div className="relationship-empty"><div><i className="bi bi-people" /></div><h3>{query || segment !== 'all' ? 'No matching people' : 'Your directory is ready to grow'}</h3><p>{workspace?.type === 'organization' ? 'Add workspace members or start conversations. Collaboration metrics appear automatically.' : 'Add an external client, partner, or mentor when you need private context.'}</p></div>}
    <PersonModal person={person} open={Boolean(person)} onClose={() => setPerson(null)} onSave={savePreference} saving={saving} />
    <ExternalModal open={externalOpen} editing={editingExternal} onClose={() => {setExternalOpen(false);setEditingExternal(null)}} onSubmit={submitExternal} saving={saving} />
    <TeamModal open={teamOpen} members={members} canManage={canManageTeam} form={memberForm} setForm={setMemberForm} onClose={() => setTeamOpen(false)} onSubmit={submitMember} saving={saving} />
    <ArchiveModal item={archiveTarget} onClose={() => setArchiveTarget(null)} onConfirm={confirmArchive} saving={saving} />
  </div>
}
