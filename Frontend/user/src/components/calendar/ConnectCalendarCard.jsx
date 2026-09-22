import { useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import { getCalendarConnection, getCalendarOAuthUrl } from '../../api/calendar'
import { API_BASE_URL } from '../../api/client'

const backendUrl = new URL(API_BASE_URL)
const TRUSTED_BACKEND_ORIGINS = new Set([backendUrl.origin])

// Google requires the registered redirect URI to match exactly. During local
// development the API may be opened through 127.0.0.1 while OAuth redirects to
// localhost (or the reverse), even though both addresses reach the same backend.
if (backendUrl.hostname === '127.0.0.1' || backendUrl.hostname === 'localhost') {
  const loopbackAlias = new URL(backendUrl.origin)
  loopbackAlias.hostname = backendUrl.hostname === 'localhost' ? '127.0.0.1' : 'localhost'
  TRUSTED_BACKEND_ORIGINS.add(loopbackAlias.origin)
}

export default function ConnectCalendarCard({ onConnected }) {
  const { token } = useAuth()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const connect = async () => {
    setBusy(true); setError('')
    try {
      const { url } = await getCalendarOAuthUrl(token)
      const popup = window.open(url, 'google-calendar-oauth', 'width=520,height=640')
      if (!popup) throw new Error('Popup blocked')

      let finished = false
      let checking = false
      let timer

      const cleanup = () => {
        window.removeEventListener('message', onMessage)
        if (timer) window.clearInterval(timer)
      }
      const finish = (connected, message = '') => {
        if (finished) return
        finished = true
        cleanup()
        setBusy(false)
        if (connected) onConnected?.()
        else setError(message || 'Could not connect Google Calendar.')
      }
      const verifyConnection = async () => {
        if (finished || checking) return
        checking = true
        try {
          const result = await getCalendarConnection(token)
          if (result.connected) finish(true)
        } finally {
          checking = false
        }
      }
      const onMessage = event => {
        if (!TRUSTED_BACKEND_ORIGINS.has(event.origin) || event.data?.type !== 'calendar_oauth') return
        if (event.data.ok) verifyConnection()
        else finish(false, event.data.message)
      }
      window.addEventListener('message', onMessage)
      timer = window.setInterval(async () => {
        if (popup.closed) {
          await verifyConnection()
          if (!finished) finish(false)
        }
      }, 500)
    } catch (err) {
      setError(err.detail?.message || err.detail || 'Could not open Google authorization.')
      setBusy(false)
    }
  }

  return <section className="content-card text-center py-5 px-3">
    <i className="bi bi-calendar-plus display-4 text-muted d-block mb-3" />
    <h3>Connect your Google Calendar</h3>
    <p className="text-muted mb-4">Events stay private to your account. Orbit stores the refresh token encrypted.</p>
    {error && <div className="auth-error mb-3">{error}</div>}
    <button className="btn btn-primary" onClick={connect} disabled={busy}><i className="bi bi-google me-2" />{busy ? 'Waiting for Google...' : 'Connect Google Calendar'}</button>
  </section>
}
