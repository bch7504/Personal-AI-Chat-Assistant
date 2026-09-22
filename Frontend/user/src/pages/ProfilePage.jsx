import { useEffect, useState } from 'react'
import PageHeader from '../components/common/PageHeader'
import SettingsSection from '../components/profile/SettingsSection'
import { useAuth } from '../context/AuthContext'
import { useWorkspace } from '../context/WorkspaceContext'
import { getNotificationPermission, isNotificationSupported, requestNotificationPermission } from '../utils/browserNotifications'
import { useTheme } from '../context/ThemeContext'

const DEFAULT_PREFS = { language: 'English', theme: 'system', default_reminder_lead_minutes: 30, auto_task_reminders: false, desktop_notifications: true, email_digest: false, ai_suggestion_alerts: false, permission_scope: '20 latest messages', ai_response_detail: 'Balanced', personalized_suggestions: true }
const PROFILE_SECTIONS = [
  { id: 'basic', icon: 'bi-person', label: 'Basic information' },
  { id: 'preferences', icon: 'bi-sliders', label: 'Preferences' },
  { id: 'notifications', icon: 'bi-bell', label: 'Notifications' },
  { id: 'ai', icon: 'bi-stars', label: 'AI settings' },
  { id: 'security', icon: 'bi-shield-lock', label: 'Security' },
]

export default function ProfilePage(){
  const { user, updateProfile, changePassword } = useAuth()
  const { themeMode, setThemeMode } = useTheme()
  const [form, setForm] = useState(() => ({ display_name: user?.display_name || '', job_title: user?.job_title || '', timezone: user?.timezone || 'Asia/Ho_Chi_Minh', ...DEFAULT_PREFS, ...(user?.preferences || {}) }))
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')
  const [pw, setPw] = useState({ current_password: '', new_password: '' })
  const [pwStatus, setPwStatus] = useState('')
  const [pwSaving, setPwSaving] = useState(false)
  const [notificationPermission, setNotificationPermission] = useState(() => getNotificationPermission())
  const [activeSection, setActiveSection] = useState(() => {
    const initial = window.location.hash.slice(1)
    return PROFILE_SECTIONS.some(section => section.id === initial) ? initial : 'basic'
  })

  useEffect(() => {
    let frame = null
    const updateActiveSection = () => {
      frame = null
      const anchor = Math.min(220, window.innerHeight * 0.3)
      const atPageBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 8
      if (atPageBottom) {
        setActiveSection(PROFILE_SECTIONS.at(-1).id)
        return
      }
      let current = PROFILE_SECTIONS[0].id
      for (const section of PROFILE_SECTIONS) {
        const element = document.getElementById(section.id)
        if (element && element.getBoundingClientRect().top <= anchor) current = section.id
      }
      setActiveSection(current)
    }
    const onScroll = () => {
      if (frame === null) frame = window.requestAnimationFrame(updateActiveSection)
    }
    updateActiveSection()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      if (frame !== null) window.cancelAnimationFrame(frame)
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
    }
  }, [])

  const navigateToSection = (event, sectionId) => {
    event.preventDefault()
    const section = document.getElementById(sectionId)
    if (!section) return
    setActiveSection(sectionId)
    window.history.replaceState(null, '', `#${sectionId}`)
    section.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const set = key => e => setForm(f => ({ ...f, [key]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))
  const setAppearance = event => {
    setThemeMode(event.target.value)
    setForm(current => ({ ...current, theme: event.target.value }))
  }

  const setAiSuggestionAlerts = async event => {
    const enabled = event.target.checked
    if (enabled && isNotificationSupported() && getNotificationPermission() === 'default') {
      setNotificationPermission(await requestNotificationPermission())
    }
    setForm(current => ({ ...current, ai_suggestion_alerts: enabled }))
  }

  const setDesktopNotifications = async event => {
    const enabled = event.target.checked
    if (enabled && isNotificationSupported() && getNotificationPermission() === 'default') {
      setNotificationPermission(await requestNotificationPermission())
    }
    setForm(current => ({ ...current, desktop_notifications: enabled }))
  }

  const save = async () => {
    setSaving(true); setError('')
    try {
      const { display_name, job_title, timezone, ...preferences } = form
      await updateProfile({ display_name, job_title, timezone, preferences: { ...preferences, theme: themeMode } })
      setSaved(true); setTimeout(() => setSaved(false), 1800)
    } catch (err) { setError(err.detail || 'Could not save changes.') }
    finally { setSaving(false) }
  }

  const submitPassword = async () => {
    setPwSaving(true); setPwStatus('')
    try {
      await changePassword(pw)
      setPw({ current_password: '', new_password: '' })
      setPwStatus('Password updated.')
    } catch (err) { setPwStatus(err.detail || 'Could not change password.') }
    finally { setPwSaving(false) }
  }

  const initials = (user?.display_name || '?').trim().split(/\s+/).map(w => w[0]).slice(0, 2).join('').toUpperCase()
  const filled = [form.display_name, form.job_title, form.timezone, user?.email].filter(Boolean).length
  const completion = Math.round((filled / 4) * 100)

  return <div className="page-container profile-page"><PageHeader eyebrow="Account" title="Profile & settings" description="Manage your personal details and Orbit preferences." action={<button className="btn btn-primary" onClick={save} disabled={saving}><i className={`bi ${saved?'bi-check2':'bi-floppy'} me-2`}/>{saving?'Saving...':saved?'Saved':'Save changes'}</button>}/>
    {error && <div className="auth-error">{error}</div>}
    <div className="profile-layout"><aside className="profile-card"><div className="profile-avatar">{initials}</div><h2>{user?.display_name}</h2><p>{user?.email}</p><span>{form.job_title || 'No job title set'}</span><div className="profile-completion"><div><strong>Profile completion</strong><b>{completion}%</b></div><div className="progress"><div className="progress-bar" style={{width:`${completion}%`}}/></div></div><nav aria-label="Profile settings sections">{PROFILE_SECTIONS.map(section => <a key={section.id} href={`#${section.id}`} className={activeSection === section.id ? 'active' : ''} aria-current={activeSection === section.id ? 'location' : undefined} onClick={event => navigateToSection(event, section.id)}><i className={`bi ${section.icon}`}/>{section.label}</a>)}</nav></aside><div className="settings-stack">
      <SettingsSection icon="bi-person" title="Basic information" description="Your personal details and contact information."><div className="form-grid"><label><span>Full name</span><input className="form-control" value={form.display_name} onChange={set('display_name')}/></label><label><span>Email address</span><input className="form-control" value={user?.email || ''} disabled/></label><label><span>Job title</span><input className="form-control" value={form.job_title} onChange={set('job_title')}/></label><label><span>Timezone</span><select className="form-select" value={form.timezone} onChange={set('timezone')}><option value="Asia/Ho_Chi_Minh">Bangkok/Hanoi (GMT+7)</option><option value="Europe/London">London (GMT+0)</option><option value="America/New_York">New York (GMT-5)</option></select></label></div></SettingsSection>
      <SettingsSection icon="bi-sliders" title="Preferences" description="Customize how Orbit works for you."><div className="form-grid"><label><span>Preferred language</span><select className="form-select" value={form.language} onChange={set('language')}><option>English</option><option>Tiếng Việt</option><option>Thai</option><option>Spanish</option></select></label><label><span>Appearance</span><select className="form-select" value={themeMode} onChange={setAppearance}><option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option></select></label><label><span>Default task reminder</span><select className="form-select" value={form.default_reminder_lead_minutes} onChange={event=>setForm(current=>({...current,default_reminder_lead_minutes:Number(event.target.value)}))}><option value={15}>15 minutes before</option><option value={30}>30 minutes before</option><option value={60}>1 hour before</option><option value={1440}>1 day before</option></select></label></div></SettingsSection>
      <SettingsSection icon="bi-bell" title="Notifications" description="Choose where and when you want to be notified."><SettingToggle title="Automatic task deadline reminders" detail="Create one private reminder for each accepted task assigned to you, and keep it synchronized when the deadline changes" checked={form.auto_task_reminders} onChange={set('auto_task_reminders')}/><SettingToggle title="Desktop notifications" detail="Show a browser notification when a reminder fires while Orbit is in the background" checked={form.desktop_notifications} onChange={setDesktopNotifications} warning={form.desktop_notifications && notificationPermission === 'denied' ? 'Browser notifications are blocked for this site.' : form.desktop_notifications && notificationPermission === 'unsupported' ? 'This browser only supports in-app alerts.' : null}/><SettingToggle title="Email digest" detail="Not available until an email delivery provider is configured" checked={false} onChange={()=>{}} disabled/><SettingToggle title="AI suggestion alerts" detail="When Orbit finds a new task or event" checked={form.ai_suggestion_alerts} onChange={setAiSuggestionAlerts} warning={form.ai_suggestion_alerts && notificationPermission === 'denied' ? 'Browser notifications are blocked for this site.' : form.ai_suggestion_alerts && notificationPermission === 'unsupported' ? 'This browser only supports in-app alerts.' : null}/></SettingsSection>
      <SettingsSection icon="bi-stars" title="AI settings" description="Control Orbit's access and defaults."><div className="form-grid"><label><span>Default permission scope</span><select className="form-select" value={form.permission_scope} onChange={set('permission_scope')}><option>20 latest messages</option><option>50 latest messages</option><option>Unread messages</option></select></label><label><span>AI response detail</span><select className="form-select" value={form.ai_response_detail} onChange={set('ai_response_detail')}><option>Concise</option><option>Balanced</option><option>Detailed</option></select></label></div><SettingToggle title="Personalized suggestions" detail="Use memory to make AI results more relevant" checked={form.personalized_suggestions} onChange={set('personalized_suggestions')}/></SettingsSection>
      <SettingsSection icon="bi-shield-lock" title="Security" description="Keep your account safe."><div className="security-row"><div><strong>Change password</strong><p>{pwStatus || 'Choose a new password for your account.'}</p></div></div><div className="form-grid"><label><span>Current password</span><input type="password" className="form-control" value={pw.current_password} onChange={e=>setPw(p=>({...p,current_password:e.target.value}))}/></label><label><span>New password</span><input type="password" className="form-control" value={pw.new_password} onChange={e=>setPw(p=>({...p,new_password:e.target.value}))}/></label></div><button className="btn btn-light mt-2" onClick={submitPassword} disabled={pwSaving || !pw.current_password || pw.new_password.length<6}>{pwSaving?'Updating...':'Update password'}</button></SettingsSection>
    </div></div></div>
}

function SettingToggle({title,detail,checked=false,onChange,warning,disabled=false}){return <div className={`setting-toggle ${disabled?'opacity-75':''}`}><div><strong>{title}</strong><p>{detail}</p>{warning && <p className="text-warning small mb-0"><i className="bi bi-exclamation-triangle me-1"/>{warning}</p>}</div><div className="form-check form-switch"><input className="form-check-input" type="checkbox" checked={checked} onChange={onChange} disabled={disabled}/></div></div>}
