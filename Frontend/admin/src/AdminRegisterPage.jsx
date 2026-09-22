import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { useAuth } from '../../src/context/AuthContext'

export default function AdminRegisterPage() {
  const { register, handleSubmit, watch, formState: { errors } } = useForm()
  const { registerAdmin } = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const onSubmit = async ({ name, email, password, confirm, bootstrapKey }) => {
    setError('')
    setSubmitting(true)
    try {
      await registerAdmin(email, password, name, bootstrapKey)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err.detail || 'Unable to create the administrator account.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="admin-login-page">
      <section className="admin-login-card">
        <div className="admin-brand"><span><i className="bi bi-command" /></span><div><strong>Orbit</strong><small>PLATFORM ADMIN</small></div></div>
        <div className="admin-login-heading"><span><i className="bi bi-shield-plus" /> First-time setup</span><h1>Create admin</h1><p>Create the first administrator directly from the admin console.</p></div>
        <form onSubmit={handleSubmit(onSubmit)} noValidate>
          {error && <div className="admin-login-error" role="alert"><i className="bi bi-exclamation-circle" />{error}</div>}
          <label>Full name</label>
          <div className={`admin-login-input ${errors.name ? 'invalid' : ''}`}><i className="bi bi-person" /><input autoComplete="name" placeholder="Admin name" {...register('name', { required: 'Name is required.' })} /></div>
          {errors.name && <small className="admin-field-error">{errors.name.message}</small>}
          <label>Email address</label>
          <div className={`admin-login-input ${errors.email ? 'invalid' : ''}`}><i className="bi bi-envelope" /><input type="email" autoComplete="username" placeholder="admin@company.com" {...register('email', { required: 'Email is required.', pattern: { value: /^\S+@\S+\.\S+$/, message: 'Enter a valid email.' } })} /></div>
          {errors.email && <small className="admin-field-error">{errors.email.message}</small>}
          <label>Password</label>
          <div className={`admin-login-input ${errors.password ? 'invalid' : ''}`}><i className="bi bi-lock" /><input type="password" autoComplete="new-password" placeholder="At least 6 characters" {...register('password', { required: 'Password is required.', minLength: { value: 6, message: 'Password must be at least 6 characters.' } })} /></div>
          {errors.password && <small className="admin-field-error">{errors.password.message}</small>}
          <label>Confirm password</label>
          <div className={`admin-login-input ${errors.confirm ? 'invalid' : ''}`}><i className="bi bi-lock" /><input type="password" autoComplete="new-password" placeholder="Repeat password" {...register('confirm', { required: 'Please confirm the password.', validate: value => value === watch('password') || 'Passwords do not match.' })} /></div>
          {errors.confirm && <small className="admin-field-error">{errors.confirm.message}</small>}
          <label>Bootstrap key</label>
          <div className={`admin-login-input ${errors.bootstrapKey ? 'invalid' : ''}`}><i className="bi bi-key" /><input type="password" autoComplete="one-time-code" placeholder="Configured by the platform owner" {...register('bootstrapKey', { required: 'Bootstrap key is required.' })} /></div>
          {errors.bootstrapKey && <small className="admin-field-error">{errors.bootstrapKey.message}</small>}
          <button className="admin-login-submit" disabled={submitting}>{submitting ? 'Creating admin...' : 'Create admin account'} <i className="bi bi-arrow-right" /></button>
        </form>
        <p className="admin-auth-switch"><Link to="/login">Back to admin sign in</Link></p>
        <small className="admin-login-note"><i className="bi bi-info-circle" /> This one-time setup is separate from User registration.</small>
      </section>
    </main>
  )
}
