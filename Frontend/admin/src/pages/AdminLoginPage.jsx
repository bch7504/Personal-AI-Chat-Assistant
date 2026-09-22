import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function AdminLoginPage() {
  const { user, isAdmin, login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  if (user && isAdmin) return <Navigate to="/admin" replace />

  const submit = async (event) => {
    event.preventDefault(); setSubmitting(true); setError('')
    try { await login(email, password); navigate('/admin', { replace: true }) }
    catch (err) { setError(err.detail || err.message || 'Could not sign in.') }
    finally { setSubmitting(false) }
  }

  return (
    <main className="admin-login-page"><section className="admin-login-card"><div className="admin-login-brand"><span><i className="bi bi-command" /></span><div><strong>Orbit</strong><small>PLATFORM ADMINISTRATION</small></div></div><div className="admin-login-heading"><span>Restricted area</span><h1>Welcome back</h1><p>Sign in with a platform administrator account.</p></div>{error && <div className="admin-inline-alert"><i className="bi bi-exclamation-circle" />{error}</div>}<form onSubmit={submit}><label>Email address</label><div className="admin-login-input"><i className="bi bi-envelope" /><input type="email" value={email} onChange={event=>setEmail(event.target.value)} required autoComplete="email" /></div><label>Password</label><div className="admin-login-input"><i className="bi bi-lock" /><input type="password" value={password} onChange={event=>setPassword(event.target.value)} required autoComplete="current-password" /></div><button className="admin-login-submit" disabled={submitting}>{submitting ? <><span className="spinner-border spinner-border-sm" /> Signing in...</> : <>Sign in <i className="bi bi-arrow-right" /></>}</button></form><a className="admin-login-note" href={import.meta.env.VITE_USER_APP_URL || 'http://localhost:5173'}>Back to Orbit user application</a></section></main>
  )
}
