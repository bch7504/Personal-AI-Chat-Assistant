import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../../src/context/AuthContext'

export default function AdminLoginPage() {
  const { register, handleSubmit, formState: { errors } } = useForm()
  const { loginAdmin, logout } = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const onSubmit = async ({ email, password }) => {
    setError('')
    setSubmitting(true)
    try {
      const data = await loginAdmin(email, password)
      if (data.user.platform_role !== 'platform_admin') {
        logout()
        setError('This account is not a platform administrator.')
        return
      }
      navigate('/', { replace: true })
    } catch (err) {
      setError(err.detail || 'Email or password is incorrect.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="admin-login-page">
      <section className="admin-login-card">
        <div className="admin-brand"><span><i className="bi bi-command" /></span><div><strong>Orbit</strong><small>PLATFORM ADMIN</small></div></div>
        <div className="admin-login-heading"><span><i className="bi bi-shield-lock" /> Secure console</span><h1>Welcome back</h1><p>Sign in with an administrator account.</p></div>
        <form onSubmit={handleSubmit(onSubmit)} noValidate>
          {error && <div className="admin-login-error" role="alert"><i className="bi bi-exclamation-circle" />{error}</div>}
          <label>Email address</label>
          <div className={`admin-login-input ${errors.email ? 'invalid' : ''}`}><i className="bi bi-envelope" /><input type="email" autoComplete="username" placeholder="admin@company.com" {...register('email', { required: 'Email is required.', pattern: { value: /^\S+@\S+\.\S+$/, message: 'Enter a valid email.' } })} /></div>
          {errors.email && <small className="admin-field-error">{errors.email.message}</small>}
          <label>Password</label>
          <div className={`admin-login-input ${errors.password ? 'invalid' : ''}`}><i className="bi bi-lock" /><input type="password" autoComplete="current-password" placeholder="Enter your password" {...register('password', { required: 'Password is required.' })} /></div>
          {errors.password && <small className="admin-field-error">{errors.password.message}</small>}
          <button className="admin-login-submit" disabled={submitting}>{submitting ? 'Signing in...' : 'Sign in to console'} <i className="bi bi-arrow-right" /></button>
        </form>
        <p className="admin-auth-switch">First time setting up the platform? <Link to="/register">Create the first admin</Link></p>
        <small className="admin-login-note"><i className="bi bi-info-circle" /> This console manages the Orbit platform only.</small>
      </section>
    </main>
  )
}
